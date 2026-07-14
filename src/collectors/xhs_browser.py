"""小红书浏览器采集器（Chrome CDP 直连模式）。

核心策略:
1. 连接已运行的真实 Chrome (CDP 协议) — 绕过反爬检测
2. 拦截 Network 响应获取 API JSON 数据 — 比 HTML 解析更稳定
3. 降级方案: 解析 window.__INITIAL_STATE__ 嵌入数据

使用前准备:
1. 在本地 Chrome 登录小红书
2. 启动 Chrome 时添加: --remote-debugging-port=9222
3. 确保 Chrome 已登录 xiaohongshu.com

技术栈: websockets + httpx（纯 Python，无 C 扩展依赖，兼容 Python 3.14+）。

注意事项:
- 每日请求量控制在 100 次/账号以内
- 操作间隔 1.5-5 秒随机延迟
- 检测到验证码时暂停并提示用户
"""

import asyncio
import json
import logging
import random
import re
from datetime import date, datetime
from pathlib import Path
from typing import Optional

import httpx
import websockets
from websockets.asyncio.client import ClientConnection

from src.collectors.base import BaseCollector
from src.collectors.models import AccountProfile, NoteMetrics
from src.core.config import AccountInfo
from src.core.exceptions import (
    AccountNotFoundError,
    AntiCrawlBlockedError,
    BrowserConnectionError,
    CaptchaDetectedError,
    CollectorError,
    LoginSessionExpiredError,
    RateLimitError,
)

logger = logging.getLogger(__name__)

# 小红书页面 URL
XHS_BASE_URL = "https://www.xiaohongshu.com"
XHS_USER_PROFILE_URL = f"{XHS_BASE_URL}/user/profile/"
XHS_NOTE_DETAIL_URL = f"{XHS_BASE_URL}/explore/"

# CDP API 响应匹配模式（过滤 Network 事件）
XHS_API_URL_PATTERNS = [
    # 创作者中心 - 账号数据
    "/api/galaxy/creator/home/personal_info",
    # 创作者中心 - 笔记数据
    "/api/galaxy/creator/data/note_detail_new",
    "/api/galaxy/creator/data/note",
    # 创作者中心 - 统计页（data-analysis / fans-data / account/v2）
    "/api/galaxy/creator/statistics/",
    "/api/galaxy/creator/data/statistics/",
    # 创作者中心 - 笔记分析列表（每篇笔记的互动数据）
    "/api/galaxy/creator/datacenter/note/analyze/list",
    # 创作者中心 - 直播数据
    "/api/galaxy/v2/creator/live_rooms",
    # 创作者中心 - 数据中心
    "/api/galaxy/v2/creator/datacenter/account",
    "/api/galaxy/v2/creator/datacenter/livedata",
    "/api/galaxy/v2/creator/datacenter/leaderboard",
    "/api/galaxy/v2/creator/datacenter",
    # 个人主页 - 用户信息
    "/api/sns/web/v1/user/otherinfo",
    "/api/sns/web/v2/user/me",
    # 个人主页 - 笔记列表
    "/api/sns/web/v1/note/feed",
    "/api/sns/web/v1/feed",
    "/api/sns/web/v2/note/page",
]

# 创作者中心 URL
XHS_CREATOR_URL = "https://creator.xiaohongshu.com"
XHS_CREATOR_NOTE_ANALYSIS_URL = "https://creator.xiaohongshu.com/statistics/data-analysis"
XHS_CREATOR_FANS_URL = "https://creator.xiaohongshu.com/statistics/fans-data"
XHS_CREATOR_ACCOUNT_URL = "https://creator.xiaohongshu.com/statistics/account/v2"


class XHSBrowserCollector(BaseCollector):
    """基于 Chrome CDP 的小红书数据采集器。

    Args:
        cdp_endpoint: Chrome DevTools Protocol 端点 (HTTP)
        min_delay: 最小操作间隔（秒）
        max_delay: 最大操作间隔（秒）
        timeout: 请求超时（秒）
        max_notes: 单次最大采集笔记数
    """

    def __init__(
        self,
        cdp_endpoint: str = "http://localhost:9222",
        headless: bool = False,  # 保留兼容，CDP 模式下忽略
        min_delay: float = 1.5,
        max_delay: float = 5.0,
        timeout: int = 30,
        max_notes: int = 100,
        storage_state_path: str = ".browser_state/storage.json",
    ):
        super().__init__()
        self.cdp_endpoint = cdp_endpoint.rstrip("/")
        self.min_delay = min_delay
        self.max_delay = max_delay
        self.timeout = timeout
        self.max_notes = max_notes

        # 运行时状态
        self._ws: Optional[ClientConnection] = None
        self._msg_id: int = 0
        self._pending: dict[int, asyncio.Future] = {}
        self._api_responses: list[dict] = []
        self._pending_api_requests: dict[str, str] = {}  # requestId → url
        self._is_logged_in: bool = False
        self._logged_in_user_id: Optional[str] = None  # 从页面提取的登录用户ID（hex）
        self._http: Optional[httpx.AsyncClient] = None
        self._listen_task: Optional[asyncio.Task] = None
        self._cached_creator_notes: list[NoteMetrics] = []
        # API 发现模式：记录所有网络请求 URL（用于发现新 API 路径）
        self._discover_mode: bool = False
        self._discovered_urls: list[str] = []

    # ── CDP 底层通信 ──

    async def _send_cdp(self, method: str, params: dict | None = None) -> dict:
        """发送 CDP 命令并等待响应。"""
        self._msg_id += 1
        msg_id = self._msg_id
        msg = {"id": msg_id, "method": method, "params": params or {}}

        future: asyncio.Future = asyncio.get_event_loop().create_future()
        self._pending[msg_id] = future

        try:
            await self._ws.send(json.dumps(msg))
            result = await asyncio.wait_for(future, timeout=self.timeout)
            if "error" in result:
                raise CollectorError(
                    f"CDP 命令失败 {method}: {result['error'].get('message', 'unknown')}"
                )
            return result.get("result", {})
        except asyncio.TimeoutError:
            raise CollectorError(f"CDP 命令超时: {method}")
        finally:
            self._pending.pop(msg_id, None)

    async def _listen_cdp(self):
        """持续监听 CDP WebSocket 消息，分发响应和事件。"""
        try:
            async for raw in self._ws:
                try:
                    msg = json.loads(raw)
                except json.JSONDecodeError:
                    continue

                msg_id = msg.get("id")
                if msg_id is not None and msg_id in self._pending:
                    # 命令响应
                    self._pending[msg_id].set_result(msg)
                elif "method" in msg:
                    # CDP 事件
                    await self._handle_cdp_event(msg["method"], msg.get("params", {}))
        except websockets.ConnectionClosed:
            logger.debug("CDP WebSocket 连接已关闭")
        except Exception as e:
            logger.debug("CDP 监听异常: %s", e)

    async def _handle_cdp_event(self, method: str, params: dict):
        """处理 CDP 事件——仅收集 requestId，不在此处获取 body（避免死锁）。"""
        if method == "Network.responseReceived":
            response = params.get("response", {})
            url = response.get("url", "")
            # API 发现模式：记录所有 API 请求 URL
            if self._discover_mode:
                self._discovered_urls.append(url)
            if any(pattern in url for pattern in XHS_API_URL_PATTERNS):
                rid = params["requestId"]
                self._pending_api_requests[rid] = url
                logger.info("✓ 拦截到目标 API: %s", url[:120])

    async def _fetch_pending_api_bodies(self):
        """获取已拦截的 API 响应体（在导航完成后调用）。"""
        fetched = 0
        for rid, url in list(self._pending_api_requests.items()):
            if fetched >= 20:  # 限制单次获取数量
                break
            try:
                body_result = await self._send_cdp(
                    "Network.getResponseBody",
                    {"requestId": rid},
                )
                body = body_result.get("body", "")
                if body:
                    try:
                        data = json.loads(body)
                        self._api_responses.append({
                            "url": url,
                            "status": 200,
                            "data": data,
                            "timestamp": datetime.now(),
                        })
                        fetched += 1
                    except json.JSONDecodeError:
                        pass
            except Exception:
                pass  # 某些响应体可能已被清除
            finally:
                self._pending_api_requests.pop(rid, None)

    async def _ensure_browser(self):
        """确保 CDP 浏览器连接可用。"""
        if self._ws and self._listen_task:
            return

        self._http = httpx.AsyncClient(timeout=httpx.Timeout(self.timeout))

        try:
            # 获取可用的页面列表
            resp = await self._http.get(f"{self.cdp_endpoint}/json")
            pages = resp.json()
        except Exception as e:
            raise BrowserConnectionError(
                f"无法连接到 Chrome CDP ({self.cdp_endpoint})。\n"
                f"请确保 Chrome 已启动并带有 --remote-debugging-port=9222 参数。\n"
                f"错误: {e}"
            ) from e

        # 过滤出小红书页面
        target_page = None
        for page in pages:
            if "xiaohongshu.com" in page.get("url", ""):
                target_page = page
                break

        if not target_page:
            # 取第一个普通页面
            for page in pages:
                if page.get("type") == "page":
                    target_page = page
                    break

        if not target_page:
            raise BrowserConnectionError("未找到可用的浏览器页面，请在 Chrome 中打开一个页面后重试")

        ws_url = target_page.get("webSocketDebuggerUrl")
        if not ws_url:
            raise BrowserConnectionError("无法获取页面 WebSocket 调试 URL")

        try:
            self._ws = await websockets.connect(
                ws_url,
                max_size=10 * 1024 * 1024,  # 10MB，支持大响应
            )
            logger.info("已连接到 Chrome CDP: %s", target_page.get("url", "unknown"))
        except Exception as e:
            raise BrowserConnectionError(f"CDP WebSocket 连接失败: {e}") from e

        # ★ 必须先启动监听器，再发送 CDP 命令
        self._listen_task = asyncio.create_task(self._listen_cdp())

        # 启动 Network 监听（拦截 API 响应）
        await self._send_cdp("Network.enable")
        # 启动 Page 域（导航控制）
        await self._send_cdp("Page.enable")
        # 启动 Runtime 域（JS 执行）
        await self._send_cdp("Runtime.enable")

        logger.info("CDP 连接就绪，Network/Runtime/Page 域已启用")

    async def _navigate(self, url: str, wait_dom: bool = True) -> int:
        """导航到指定 URL，返回 HTTP 状态码。"""
        await self._ensure_browser()

        # 清空之前的 API 响应和待拉取请求
        self._api_responses.clear()
        self._pending_api_requests.clear()

        result = await self._send_cdp("Page.navigate", {"url": url})
        error_text = result.get("errorText", "")

        if error_text:
            logger.warning("页面导航错误: %s", error_text)

        # 等待页面加载完成
        if wait_dom:
            await self._wait_for_load()

        # 等待额外时间让 JS 渲染和 API 调用发出
        await self._random_delay(1, 2)

        # 拉取拦截到的 API 响应体
        await self._fetch_pending_api_bodies()

        return 200  # CDP 不直接返回 HTTP 状态码

    async def _wait_for_load(self, timeout_ms: int = 15000):
        """等待页面加载完成。"""
        try:
            future: asyncio.Future = asyncio.get_event_loop().create_future()

            async def _wait():
                while True:
                    await asyncio.sleep(0.3)
                    try:
                        result = await self._send_cdp(
                            "Runtime.evaluate",
                            {"expression": "document.readyState", "returnByValue": True},
                        )
                        state = result.get("result", {}).get("value", "")
                        if state == "complete":
                            future.set_result(True)
                            return
                    except Exception:
                        pass

            await asyncio.wait_for(_wait(), timeout=timeout_ms / 1000)
        except asyncio.TimeoutError:
            logger.debug("页面加载等待超时")

    async def _evaluate(self, expression: str) -> dict:
        """执行 JavaScript 表达式并返回结果。"""
        await self._ensure_browser()
        return await self._send_cdp(
            "Runtime.evaluate",
            {"expression": expression, "returnByValue": True},
        )

    async def _random_delay(self, min_s: Optional[float] = None, max_s: Optional[float] = None):
        """操作间随机延迟，模拟人类行为。"""
        delay = random.uniform(
            min_s or self.min_delay,
            max_s or self.max_delay,
        )
        await asyncio.sleep(delay)

    # ── 登录检测 ──

    async def _check_login_state(self) -> bool:
        """检测当前是否已登录小红书。"""
        await self._ensure_browser()

        try:
            await self._navigate(f"{XHS_BASE_URL}/explore")
            await self._random_delay(2, 4)

            result = await self._evaluate("""(() => {
                const hasLoginBtn = document.querySelector('.login-btn, [class*="login"]');
                const hasAvatar = document.querySelector('.user .avatar, [class*="avatar"]');
                return !hasLoginBtn && !!hasAvatar;
            })()""")

            is_logged_in = result.get("result", {}).get("value", False)
            self._is_logged_in = is_logged_in

            if not is_logged_in:
                raise LoginSessionExpiredError(
                    "小红书登录态已过期。请在 Chrome 中重新登录小红书后重试。"
                )
            logger.info("✓ 小红书登录态正常")

            # 提取登录用户 ID（用于后续身份校验）
            if self._logged_in_user_id is None:
                self._logged_in_user_id = await self._extract_logged_in_user_id()
                if self._logged_in_user_id:
                    logger.info("   Chrome 登录账号 ID: %s", self._logged_in_user_id)

            return True
        except LoginSessionExpiredError:
            raise
        except Exception as e:
            logger.warning("登录状态检测异常: %s", e)
            return False

    async def _extract_logged_in_user_id(self) -> Optional[str]:
        """从页面 __INITIAL_STATE__ 提取当前登录的小红书用户 ID（32位 hex）。

        在 explore 或 creator 页面调用，提取后缓存供身份校验使用。
        """
        try:
            result = await self._evaluate("""(() => {
                const state = window.__INITIAL_STATE__;
                if (!state) return '';
                const user = state.user || state.profile || state.creator || {};
                return String(user.userId || user.id || user.user_id || user.red_id || '');
            })()""")
            uid = result.get("result", {}).get("value", "")
            uid = str(uid).strip() if uid else ""
            return uid if uid and len(uid) >= 10 else None
        except Exception as e:
            logger.debug("提取登录用户 ID 失败: %s", e)
            return None

    async def _verify_account_identity(self, account: AccountInfo) -> Optional[str]:
        """校验 Chrome 登录账号与配置账号是否一致。

        Returns:
            实际登录的 user_id（hex），无法提取则返回 None。
        """
        logged_in_id = self._logged_in_user_id
        if not logged_in_id:
            return None

        configured_id = account.xhs_user_id.strip() if account.xhs_user_id else ""

        if configured_id and logged_in_id != configured_id:
            logger.warning(
                "⚠️ 账号不匹配！Chrome 登录的是 %s，但配置采集的是 %s (%s)。"
                "采集到的创作者中心数据属于 Chrome 登录账号，而非配置账号。"
                "请在 Chrome 调试窗口中切换到账号 %s 后重试。",
                logged_in_id, configured_id, account.display_name,
                configured_id,
            )
        elif configured_id and logged_in_id == configured_id:
            logger.info("✓ 身份校验通过: %s", account.display_name)

        return logged_in_id

    # ── 公共方法 ──

    async def validate_connection(self) -> bool:
        """验证数据源连接。"""
        try:
            await self._ensure_browser()
            await self._check_login_state()
            return True
        except Exception as e:
            logger.error("连接验证失败: %s", e)
            return False

    async def collect_account_profile(
        self, account: AccountInfo
    ) -> AccountProfile:
        """采集账号概览数据（粉丝数、关注数、获赞收藏等）。

        优先从创作者中心 API 获取，降级到个人主页 __INITIAL_STATE__。
        """
        self._api_responses.clear()

        try:
            # 方案1: 创作者中心（官方数据 API，最可靠）
            profile = await self._collect_profile_from_creator(account)
            if profile and profile.follower_count > 0:
                # 身份校验：Chrome 登录账号必须与配置账号一致
                actual_user_id = await self._verify_account_identity(account)
                if actual_user_id and actual_user_id != account.xhs_user_id:
                    profile.actual_xhs_user_id = actual_user_id
                return profile

            # 方案2: 个人主页 __INITIAL_STATE__
            logger.info("创作者中心未获取到数据，尝试个人主页...")
            profile = await self._collect_profile_from_profile_page(account)
            if profile:
                return profile
        except (AccountNotFoundError, RateLimitError, CaptchaDetectedError):
            raise
        except Exception as e:
            logger.warning("采集账号概览异常: %s", e)

        # 兜底：返回基础信息
        return AccountProfile(
            account_id=account.account_id,
            xhs_user_id=account.xhs_user_id,
            username=account.xhs_username,
            display_name=account.display_name,
            competitor=account.competitor,
        )

    async def _collect_profile_from_creator(
        self, account: AccountInfo
    ) -> Optional[AccountProfile]:
        """从创作者中心获取账号数据。"""
        await self._check_login_state()
        self._api_responses.clear()

        logger.info("访问创作者中心: %s", account.display_name)
        await self._navigate(XHS_CREATOR_URL)
        await self._random_delay(5, 8)  # 等待 API 调用触发
        await self._detect_captcha()

        # 再次拉取任何新到达的 API 响应
        await self._fetch_pending_api_bodies()

        logger.info("共拦截 %d 个 API 响应，%d 个待拉取",
                     len(self._api_responses), len(self._pending_api_requests))

        # 同时提取笔记数据（note_detail_new API）
        notes = self._extract_notes_from_creator_api(account)
        if notes:
            self._cached_creator_notes = notes
            logger.info("从创作者中心缓存 %d 篇笔记数据", len(notes))

        return self._extract_profile_from_creator_api(account)

    async def _collect_profile_from_profile_page(
        self, account: AccountInfo
    ) -> Optional[AccountProfile]:
        """从个人主页获取账号数据（降级方案）。"""
        profile_url = f"{XHS_USER_PROFILE_URL}{account.xhs_user_id}"
        logger.info("访问账号主页: %s (%s)", account.display_name, profile_url)

        await self._navigate(profile_url)
        await self._random_delay(3, 6)
        await self._detect_captcha()

        # 等待 API 响应
        await self._random_delay(1, 2)
        profile = self._extract_profile_from_api(account)

        if not profile or profile.follower_count == 0:
            profile = await self._extract_profile_from_page(account)

        return profile

    async def _wait_for_user_page_content(self):
        """等待账号主页的用户信息区域出现。"""
        for _ in range(10):
            result = await self._evaluate("""(() => {
                const el = document.querySelector('[class*="user"], [class*="profile"]');
                return !!el;
            })()""")
            if result.get("result", {}).get("value", False):
                return
            await asyncio.sleep(1)

    async def collect_notes_data(
        self, account: AccountInfo, target_date: Optional[date] = None
    ) -> list[NoteMetrics]:
        """采集账号的笔记数据（三级策略）。

        策略 1: 复用 _collect_profile_from_creator 缓存的笔记（note_detail_new API）
        策略 2: 导航到创作者中心 statistics/data-analysis 页面拦截 API
        策略 3: 降级到个人主页 public API + __INITIAL_STATE__
        """
        await self._check_login_state()

        logger.info(
            "采集笔记数据: %s (目标日期: %s, 最多 %d 篇)",
            account.display_name,
            target_date or "不限",
            self.max_notes,
        )

        # ── 策略 1: 使用创作者中心缓存的笔记 ──
        if self._cached_creator_notes:
            notes = self._cached_creator_notes
            self._cached_creator_notes = []
            logger.info("使用创作者中心缓存: %d 篇笔记", len(notes))
            return self._filter_notes(notes, target_date)

        # ── 策略 2: 导航到 statistics/data-analysis ──
        notes = await self._collect_notes_from_creator_center(account)
        if notes:
            return self._filter_notes(notes, target_date)

        # ── 策略 3: 个人主页降级 ──
        try:
            self._api_responses.clear()
            profile_url = f"{XHS_USER_PROFILE_URL}{account.xhs_user_id}"
            await self._navigate(profile_url)
            await self._random_delay(3, 6)
            await asyncio.sleep(2)
            await self._detect_captcha()

            notes = self._extract_notes_from_api(account)
            if not notes:
                logger.info("API 响应未获取到笔记，尝试从页面获取")
                notes = await self._extract_notes_from_page(account)

            if len(notes) < min(10, self.max_notes):
                logger.info("笔记数据不足（%d篇），尝试滚动加载...", len(notes))
                await self._scroll_page(times=5)
                await self._random_delay(2, 4)
                more_notes = self._extract_notes_from_api(account)
                if not more_notes:
                    more_notes = await self._extract_notes_from_page(account)
                existing_ids = {n.note_id for n in notes}
                for n in more_notes:
                    if n.note_id and n.note_id not in existing_ids:
                        notes.append(n)
        except Exception as e:
            raise CollectorError(f"采集笔记数据失败: {e}") from e

        return self._filter_notes(notes, target_date)

    def _filter_notes(
        self, notes: list[NoteMetrics], target_date: Optional[date] = None
    ) -> list[NoteMetrics]:
        """按目标日期过滤并限制数量。"""
        if target_date:
            notes = [n for n in notes if n.publish_date and n.publish_date == target_date]
        notes = notes[:self.max_notes]
        logger.info("笔记采集完成: %d 篇", len(notes))
        return notes

    async def _collect_notes_from_creator_center(
        self, account: AccountInfo
    ) -> list[NoteMetrics]:
        """导航到创作者中心 statistics/data-analysis 页面采集笔记数据。

        该页面加载时会自动调用笔记数据 API，我们拦截并解析响应。
        启用 API 发现模式，记录所有网络请求 URL 用于后续分析。
        """
        self._api_responses.clear()
        self._discovered_urls.clear()
        self._discover_mode = True

        try:
            logger.info("访问创作者中心数据分析页: %s", account.display_name)
            await self._navigate(XHS_CREATOR_NOTE_ANALYSIS_URL)
            await self._random_delay(5, 8)  # 等待 SPA 渲染 + API 调用
            await self._detect_captcha()

            # 发现模式：捕获所有 API 请求的 body（不限于已知 patterns）
            await self._fetch_pending_api_bodies()
            await self._fetch_discovered_api_bodies()

            logger.info("数据分析页拦截: %d 个 API 响应, %d 个待拉取, %d 个全部网络请求",
                         len(self._api_responses), len(self._pending_api_requests),
                         len(self._discovered_urls))

            # Dump 所有发现的 URL 供分析
            self._dump_discovered_urls()

            # 尝试从所有拦截到的 API 中提取笔记
            notes = self._extract_notes_from_creator_api(account)

            # 也从公开页 API 结构尝试（兼容多种数据源）
            if not notes:
                notes = self._extract_notes_from_api(account)

            return notes
        except (AccountNotFoundError, RateLimitError, CaptchaDetectedError):
            raise
        except Exception as e:
            logger.warning("创作者中心笔记采集异常: %s", e)
            return []
        finally:
            self._discover_mode = False

    async def _fetch_discovered_api_bodies(self):
        """发现模式：拉取所有未被已知 patterns 覆盖的 API 响应体。"""
        import re
        # 筛选出创作者中心 API 调用（在 _pending_api_requests 中未覆盖的）
        api_pattern = re.compile(r"api/galaxy|api/sns|api/edith")
        new_urls = []
        for url in self._discovered_urls:
            if api_pattern.search(url):
                # 检查是否已被已知 patterns 覆盖
                if not any(pattern in url for pattern in XHS_API_URL_PATTERNS):
                    new_urls.append(url)

        if new_urls:
            logger.info("发现 %d 个新的 API 路径（未被已知 patterns 覆盖）", len(new_urls))
            # 保存到文件供分析
            discover_file = Path("data/debug/discovered_api_urls.txt")
            discover_file.parent.mkdir(parents=True, exist_ok=True)
            discover_file.write_text("\n".join(sorted(set(new_urls))), encoding="utf-8")

    def _dump_discovered_urls(self):
        """将发现模式收集到的全部网络请求 URL 写入文件。"""
        if not self._discovered_urls:
            return
        seen = set()
        unique = []
        for url in self._discovered_urls:
            if url not in seen:
                seen.add(url)
                unique.append(url)
        filepath = Path("data/debug/all_network_urls.txt")
        filepath.parent.mkdir(parents=True, exist_ok=True)
        filepath.write_text("\n".join(sorted(unique)), encoding="utf-8")
        logger.info("✓ 全部网络请求 URL 已保存: %s (%d 条)", filepath, len(unique))

    async def _scroll_page(self, times: int = 3):
        """滚动页面加载更多内容。"""
        for i in range(times):
            await self._evaluate(
                "window.scrollBy(0, window.innerHeight * 0.8)"
            )
            await self._random_delay(1, 2)

    # ── 数据提取 (API 响应) ──

    def _extract_profile_from_creator_api(
        self, account: AccountInfo
    ) -> Optional[AccountProfile]:
        """从创作者中心 personal_info API 提取账号数据。"""
        for resp in self._api_responses:
            url = resp.get("url", "")
            if "personal_info" not in url:
                continue

            data = resp.get("data", {})
            result = data.get("data", data)

            if result.get("red_num") or result.get("name"):
                logger.info(
                    "从创作者中心获取账号数据: fans=%s, follow=%s, faved=%s",
                    result.get("fans_count"), result.get("follow_count"), result.get("faved_count"),
                )
                return AccountProfile(
                    account_id=account.account_id,
                    xhs_user_id=account.xhs_user_id,
                    username=result.get("name", account.xhs_username),
                    display_name=account.display_name,
                    follower_count=self._safe_int(result.get("fans_count", 0)),
                    following_count=self._safe_int(result.get("follow_count", 0)),
                    total_likes=self._safe_int(result.get("faved_count", 0)),
                    total_collections=0,  # 创作者中心 merged into faved_count
                    competitor=account.competitor,
                )

        return None

    def _extract_notes_from_creator_api(
        self, account: AccountInfo
    ) -> list[NoteMetrics]:
        """从创作者中心 API 响应中提取笔记数据。

        解析 note_detail_new / datacenter 等 API 的响应结构。
        不认识的字段结构会 dump 到 data/debug/ 供人工分析。
        """
        notes: list[NoteMetrics] = []
        seen_ids: set[str] = set()

        for resp in self._api_responses:
            url = resp.get("url", "")
            data = resp.get("data", {})

            # ── 分支 1: note_detail_new ──
            if "note_detail_new" in url:
                parsed = self._parse_note_detail_new(data, account)
                if parsed:
                    logger.info("note_detail_new 解析到 %d 篇笔记", len(parsed))
                else:
                    # 结构未知 → dump 到文件
                    self._dump_debug_response("note_detail_new", data)
                for n in parsed:
                    if n.note_id and n.note_id not in seen_ids:
                        notes.append(n)
                        seen_ids.add(n.note_id)

            # ── 分支 2: datacenter/account 概览数据 ──
            elif "datacenter/account" in url:
                self._dump_debug_response("datacenter_account", data)

            # ── 分支 3: datacenter/livedata ──
            elif "datacenter/livedata" in url:
                self._dump_debug_response("datacenter_livedata", data)

            # ── 分支 4: datacenter/leaderboard ──
            elif "datacenter/leaderboard" in url:
                self._dump_debug_response("datacenter_leaderboard", data)

            # ── 分支 5: datacenter/note/analyze/list（单篇笔记数据）──
            elif "datacenter/note/analyze" in url:
                self._dump_debug_response("note_analyze_list", data)
                parsed = self._parse_note_analyze_list(data, account)
                if parsed:
                    logger.info("note/analyze/list 解析到 %d 篇笔记", len(parsed))
                for n in parsed:
                    if n.note_id and n.note_id not in seen_ids:
                        notes.append(n)
                        seen_ids.add(n.note_id)

            # ── 分支 6: 未知的创作者中心 API（dump 供分析）──
            elif "api/galaxy" in url:
                name = url.split("/api/galaxy/")[-1].split("?")[0].replace("/", "_")[:60]
                self._dump_debug_response(f"unknown_{name}", data)

        return notes

    def _parse_note_detail_new(
        self, data: dict, account: AccountInfo
    ) -> list[NoteMetrics]:
        """尝试解析 note_detail_new 响应（多种可能结构）。"""
        notes: list[NoteMetrics] = []

        # 创作者中心 API 常见外层: {"code": 0, "success": true, "data": {...}}
        inner = data.get("data", data)

        # ── 尝试 1: 直接是笔记列表 ──
        note_list = inner.get("notes", inner.get("note_list", inner.get("list", [])))

        # ── 尝试 2: 嵌套在 data 字段内 ──
        if not note_list:
            nested = inner.get("data", {})
            note_list = nested.get("notes", nested.get("note_list", nested.get("list", [])))

        # ── 尝试 3: note_detail 或 noteDetail ──
        if not note_list:
            note_list = inner.get("note_detail", inner.get("noteDetail", []))

        # ── 尝试 4: items 字段 ──
        if not note_list:
            note_list = inner.get("items", [])

        # ── 尝试 5: 整个 inner 可能是 dict，按 key 找数组 ──
        if not note_list and isinstance(inner, dict):
            for key, val in inner.items():
                if isinstance(val, list) and len(val) > 0:
                    if isinstance(val[0], dict) and any(
                        k in val[0] for k in ("note_id", "id", "title", "view", "like")
                    ):
                        note_list = val
                        logger.debug("note_detail_new: 从字段 '%s' 发现笔记列表", key)
                        break

        if not note_list:
            logger.debug("note_detail_new: 未识别到笔记列表结构，keys=%s",
                         list(inner.keys())[:10] if isinstance(inner, dict) else type(inner))
            return []

        # 解析每条笔记 — 尝试多种字段名
        for item in note_list:
            if not isinstance(item, dict):
                continue

            note_id = str(
                item.get("note_id", item.get("noteId", item.get("id", "")))
            )
            if not note_id:
                continue

            # 互动数据: 优先 item 顶层，其次 interact_info / note_stat
            stats = item.get("interact_info", item.get("interactInfo",
                    item.get("note_stat", item.get("noteStat", item))))

            note = NoteMetrics(
                note_id=note_id,
                account_id=account.account_id,
                title=item.get("title", item.get("display_title", item.get("displayTitle", ""))),
                note_type=self._safe_note_type(item),
                publish_date=self._parse_timestamp(
                    item.get("publish_time", item.get("time", item.get("create_time", 0)))
                ),
                url=item.get("url", item.get("note_url", f"{XHS_NOTE_DETAIL_URL}{note_id}")),
                views=self._safe_int(stats.get("view_count", stats.get("viewCount",
                                     item.get("view_count", item.get("viewCount", 0))))),
                likes=self._safe_int(stats.get("like_count", stats.get("likeCount",
                                     item.get("liked_count", item.get("likedCount",
                                     stats.get("liked_count", stats.get("likedCount", 0))))))),
                favorites=self._safe_int(stats.get("collect_count", stats.get("collectCount",
                                         item.get("collected_count", item.get("collectedCount",
                                         stats.get("collected_count", stats.get("collectedCount", 0))))))),
                comments=self._safe_int(stats.get("comment_count", stats.get("commentCount",
                                        item.get("comment_count", item.get("commentCount", 0))))),
                shares=self._safe_int(stats.get("share_count", stats.get("shareCount",
                                       item.get("share_count", item.get("shareCount", 0))))),
            )
            notes.append(note)

        return notes

    def _parse_note_analyze_list(
        self, data: dict, account: AccountInfo
    ) -> list[NoteMetrics]:
        """解析 datacenter/note/analyze/list 响应（单篇笔记互动数据）。

        已知响应结构 (2026-07-13):
        {
          "data": {
            "total": 1,
            "note_infos": [
              {
                "id": "xxx",
                "title": "xxx",
                "type": 1,           // 1=图文, 2=视频
                "post_time": 1769746170000,
                "read_count": 57,     // 浏览量
                "like_count": 2,
                "fav_count": 1,       // 收藏
                "comment_count": 4,
                "share_count": 0,
                "imp_count": 240      // 曝光量
              }
            ]
          }
        }
        """
        notes: list[NoteMetrics] = []

        inner = data.get("data", data)

        # 笔记数组: note_infos > notes > note_list > list
        note_list = (
            inner.get("note_infos")
            or inner.get("notes")
            or inner.get("note_list")
            or inner.get("list")
            or []
        )

        if not note_list and isinstance(inner, dict):
            for key, val in inner.items():
                if isinstance(val, list) and len(val) > 0:
                    if isinstance(val[0], dict) and any(
                        k in val[0] for k in ("id", "note_id", "title", "read_count", "like_count")
                    ):
                        note_list = val
                        logger.debug("note_analyze: 从字段 '%s' 发现笔记列表", key)
                        break

        if not note_list:
            logger.debug("note_analyze: 未识别到笔记列表结构, keys=%s",
                         list(inner.keys())[:8] if isinstance(inner, dict) else type(inner))
            return []

        for item in note_list:
            if not isinstance(item, dict):
                continue

            # note_id: 创作者中心用 "id" 而非 "note_id"
            note_id = str(
                item.get("id", item.get("note_id", item.get("noteId", "")))
            )
            if not note_id:
                continue

            # 互动数据: 创作者中心字段在 item 顶层
            note = NoteMetrics(
                note_id=note_id,
                account_id=account.account_id,
                title=item.get("title", item.get("display_title", item.get("displayTitle", ""))),
                note_type=self._safe_note_type(item),
                publish_date=self._parse_timestamp(
                    item.get("post_time", item.get("publish_time", item.get("time",
                    item.get("create_time", item.get("createTime", 0)))))
                ),
                url=item.get("url", item.get("note_url",
                    f"{XHS_NOTE_DETAIL_URL}{note_id}")),
                views=self._safe_int(item.get("read_count", item.get("view_count",
                                     item.get("viewCount", 0)))),
                likes=self._safe_int(item.get("like_count", item.get("likeCount",
                                     item.get("liked_count", item.get("likedCount", 0))))),
                favorites=self._safe_int(item.get("fav_count", item.get("collect_count",
                                         item.get("collectCount", item.get("collected_count",
                                         item.get("collectedCount", 0)))))),
                comments=self._safe_int(item.get("comment_count", item.get("commentCount",
                                        item.get("comment_count", item.get("commentCount", 0))))),
                shares=self._safe_int(item.get("share_count", item.get("shareCount",
                                       item.get("share_count", item.get("shareCount", 0))))),
            )
            notes.append(note)

        return notes

    @staticmethod
    def _dump_debug_response(name: str, data: dict):
        """将未知结构的 API 响应 dump 到文件，供人工分析。

        文件路径: data/debug/{name}.json
        仅在 debug 日志级别启用时写入，不覆盖已有文件（保留首次抓取的结构）。
        """
        import os
        debug_dir = Path("data/debug")
        debug_dir.mkdir(parents=True, exist_ok=True)
        filepath = debug_dir / f"{name}.json"
        # 不覆盖已有文件，确保保留首次抓取的完整结构
        if filepath.exists():
            return
        try:
            filepath.write_text(
                json.dumps(data, ensure_ascii=False, indent=2, default=str),
                encoding="utf-8",
            )
            logger.info("✓ 调试数据已保存: %s (%d keys)", filepath, len(data) if isinstance(data, dict) else 0)
        except Exception as e:
            logger.debug("保存调试数据失败 %s: %s", name, e)

    def _extract_profile_from_api(
        self, account: AccountInfo
    ) -> Optional[AccountProfile]:
        """从个人主页 API 响应中提取账号概览数据（降级方案）。"""
        for resp in self._api_responses:
            data = resp.get("data", {})
            if not data.get("success", True):
                continue

            result = data.get("data", {})

            # user/otherinfo 或 user/me 接口
            if "/user/" in resp.get("url", ""):
                user = result.get("user", result)
                uid = str(user.get("userid", user.get("user_id", "")))
                if uid == account.xhs_user_id or not account.xhs_user_id:
                    return AccountProfile(
                        account_id=account.account_id,
                        xhs_user_id=uid or account.xhs_user_id,
                        username=user.get("nickname", account.xhs_username),
                        display_name=account.display_name,
                        follower_count=self._safe_int(user.get("fans", 0)),
                        following_count=self._safe_int(user.get("follows", 0)),
                        total_likes=self._safe_int(user.get("liked", 0)),
                        total_collections=self._safe_int(user.get("collected", 0)),
                        competitor=account.competitor,
                    )

        return None

    def _extract_notes_from_api(
        self, account: AccountInfo
    ) -> list[NoteMetrics]:
        """从拦截的 API 响应中提取笔记数据。"""
        notes: list[NoteMetrics] = []
        seen_ids: set[str] = set()

        for resp in self._api_responses:
            data = resp.get("data", {})
            if not data.get("success", True):
                continue
            result = data.get("data", {})

            # 多种可能的响应结构
            items = result.get("notes", result.get("items", []))
            for item in items:
                note_card = item.get("note_card", item)
                note_id = str(note_card.get("note_id", item.get("id", "")))
                if not note_id or note_id in seen_ids:
                    continue
                seen_ids.add(note_id)

                interact = note_card.get("interact_info", {})
                note = NoteMetrics(
                    note_id=note_id,
                    account_id=account.account_id,
                    title=note_card.get("display_title", note_card.get("title", "")),
                    note_type=note_card.get("type", "image"),
                    publish_date=self._parse_timestamp(
                        note_card.get("time", note_card.get("create_time", 0))
                    ),
                    url=f"{XHS_NOTE_DETAIL_URL}{note_id}",
                    views=self._safe_int(interact.get("view_count", 0)),
                    likes=self._safe_int(interact.get("liked_count", 0)),
                    favorites=self._safe_int(interact.get("collected_count", 0)),
                    comments=self._safe_int(interact.get("comment_count", 0)),
                    shares=self._safe_int(interact.get("share_count", 0)),
                )
                notes.append(note)

            if len(notes) >= self.max_notes:
                break

        return notes[:self.max_notes]

    # ── 数据提取 (页面 __INITIAL_STATE__) ──

    async def _get_initial_state(self) -> Optional[dict]:
        """获取页面的 window.__INITIAL_STATE__ 数据。"""
        try:
            result = await self._evaluate("""(() => {
                try {
                    const state = window.__INITIAL_STATE__;
                    return JSON.stringify(state);
                } catch(e) {
                    return null;
                }
            })()""")
            state_text = result.get("result", {}).get("value")
            if state_text and state_text != "null":
                fixed = re.sub(r':\s*""\s*([,}])', r': null\1', state_text)
                return json.loads(fixed)
        except Exception as e:
            logger.debug("获取 __INITIAL_STATE__ 失败: %s", e)
        return None

    async def _extract_profile_from_page(
        self, account: AccountInfo
    ) -> Optional[AccountProfile]:
        """从 __INITIAL_STATE__ 提取账号概览。"""
        try:
            state = await self._get_initial_state()
            if not state:
                return None

            user_data = state.get("user", {}).get("userPageData", {})
            fan_data = state.get("user", {}).get("userInteractData", {})

            return AccountProfile(
                account_id=account.account_id,
                xhs_user_id=account.xhs_user_id,
                username=user_data.get("nickname", account.xhs_username),
                display_name=account.display_name,
                follower_count=self._safe_int(fan_data.get("fansCount", 0)),
                following_count=self._safe_int(fan_data.get("followCount", 0)),
                total_likes=self._safe_int(fan_data.get("interactCount", 0)),
                competitor=account.competitor,
            )
        except Exception as e:
            logger.debug("__INITIAL_STATE__ 解析失败: %s", e)
            return None

    async def _extract_notes_from_page(
        self, account: AccountInfo
    ) -> list[NoteMetrics]:
        """从 __INITIAL_STATE__ 提取笔记列表（兼容新旧版数据结构）。"""
        try:
            state = await self._get_initial_state()
            if not state:
                return []

            notes: list[NoteMetrics] = []
            user_data = state.get("user", {})

            # 新版小红书: Vue 3 ref 结构 — notes._value 是数组
            notes_ref = user_data.get("notes", {})
            if isinstance(notes_ref, dict):
                notes_list = notes_ref.get("_value", notes_ref.get("_rawValue", []))
            else:
                notes_list = []

            # 旧版兼容: user.notes.notesList
            if not notes_list:
                notes_list = notes_ref.get("notesList", [])

            for item in notes_list[:self.max_notes]:
                # 新版：笔记数据在 noteCard 里
                note_card = item.get("noteCard", item)
                note_id = str(note_card.get("noteId", item.get("noteId", item.get("id", ""))))
                if not note_id:
                    continue

                interact = note_card.get("interactInfo", note_card.get("interact_info", {}))
                note = NoteMetrics(
                    note_id=note_id,
                    account_id=account.account_id,
                    title=note_card.get("displayTitle", note_card.get("display_title", item.get("displayTitle", ""))),
                    note_type=note_card.get("type", item.get("type", "image")),
                    publish_date=self._parse_timestamp(
                        note_card.get("time", note_card.get("createTime", item.get("time", item.get("createTime", 0))))
                    ),
                    url=f"{XHS_NOTE_DETAIL_URL}{note_id}",
                    views=self._safe_int(interact.get("viewCount", interact.get("view_count", 0))),
                    likes=self._safe_int(interact.get("likedCount", interact.get("liked_count", 0))),
                    favorites=self._safe_int(interact.get("collectedCount", interact.get("collected_count", 0))),
                    comments=self._safe_int(interact.get("commentCount", interact.get("comment_count", 0))),
                    shares=self._safe_int(interact.get("shareCount", interact.get("share_count", 0))),
                )
                notes.append(note)

            if notes:
                logger.info("从 __INITIAL_STATE__ 提取 %d 篇笔记", len(notes))
            return notes
        except Exception as e:
            logger.debug("__INITIAL_STATE__ 笔记解析失败: %s", e)
            return []

    # ── 验证码检测 ──

    async def _detect_captcha(self) -> None:
        """检测是否触发了验证码。"""
        try:
            result = await self._evaluate("""(() => {
                const body = document.body.innerText || '';
                const keywords = ['验证码', '滑块验证', '请完成验证', 'captcha', 'verify'];
                return keywords.some(kw => body.includes(kw));
            })()""")
            has_captcha = result.get("result", {}).get("value", False)
            if has_captcha:
                raise CaptchaDetectedError(
                    "检测到验证码！请在 Chrome 浏览器中手动完成验证后重试。"
                )
        except CaptchaDetectedError:
            raise
        except Exception:
            pass

    # ── 辅助方法 ──

    @staticmethod
    def _safe_note_type(item: dict) -> str:
        """安全解析笔记类型：兼容整数 (1=图文, 2=视频) 和字符串。"""
        raw = item.get("type", item.get("note_type", item.get("noteType", "image")))
        if isinstance(raw, int) or (isinstance(raw, str) and raw.isdigit()):
            return "video" if int(raw) == 2 else "image"
        return str(raw).lower() if raw else "image"

    @staticmethod
    def _safe_int(value, default: int = 0) -> int:
        """安全转换整数。"""
        if isinstance(value, (int, float)):
            return int(value)
        if isinstance(value, str):
            try:
                return int(float(value.replace(",", "").replace("，", "")))
            except (ValueError, TypeError):
                pass
        return default

    @staticmethod
    def _parse_timestamp(ts) -> Optional[date]:
        """将毫秒时间戳转为 date 对象。"""
        if not ts:
            return None
        try:
            if isinstance(ts, (int, float)):
                if ts > 1_000_000_000_000:
                    ts = ts / 1000
                return datetime.fromtimestamp(ts).date()
            if isinstance(ts, str):
                return date.fromisoformat(ts[:10])
        except (ValueError, TypeError, OSError):
            pass
        return None

    # ── 资源清理 ──

    async def close(self):
        """关闭 CDP 连接。"""
        if self._listen_task and not self._listen_task.done():
            self._listen_task.cancel()
            try:
                await self._listen_task
            except asyncio.CancelledError:
                pass

        if self._ws:
            try:
                await self._ws.close()
            except Exception:
                pass
            self._ws = None

        if self._http:
            try:
                await self._http.aclose()
            except Exception:
                pass
            self._http = None

        self._pending.clear()
        logger.info("CDP 连接已关闭")


class HybridCollector(BaseCollector):
    """混合采集器：依次尝试 API → 浏览器 → CSV。

    按优先级降级采集，确保在一种方式失败时仍能获取数据。
    """

    def __init__(
        self,
        api_collector: Optional[BaseCollector] = None,
        browser_collector: Optional[BaseCollector] = None,
        csv_collector: Optional[BaseCollector] = None,
    ):
        super().__init__()
        self.api_collector = api_collector
        self.browser_collector = browser_collector
        self.csv_collector = csv_collector
        self.fallback_chain: list[BaseCollector] = [
            c for c in [api_collector, browser_collector, csv_collector]
            if c is not None
        ]

    async def collect_account_profile(
        self, account: AccountInfo
    ) -> AccountProfile:
        """按优先级降级采集。"""
        last_error = None
        for collector in self.fallback_chain:
            try:
                logger.info(
                    "尝试用 %s 采集账号概览: %s",
                    collector.name, account.display_name,
                )
                profile = await collector.collect_account_profile(account)
                if profile and profile.follower_count > 0:
                    return profile
            except Exception as e:
                last_error = e
                logger.warning("%s 采集失败: %s", collector.name, e)
                continue

        raise CollectorError(
            f"所有采集器均失败: {account.display_name}"
        ) from last_error

    async def collect_notes_data(
        self, account: AccountInfo, target_date: Optional[date] = None
    ) -> list[NoteMetrics]:
        """采集笔记：浏览器优先 + CSV 补充去重。

        策略:
        1. 优先使用浏览器/API 采集器（含实时互动数据）
        2. CSV 作为补充，仅导入浏览器未覆盖的笔记
        3. 按 note_id 去重，浏览器数据优先
        """
        all_notes: list[NoteMetrics] = []
        seen_ids: set[str] = set()
        csv_collector = None

        # 区分 CSV 和其他采集器
        from src.collectors.csv_import import CSVImportCollector
        primary_collectors = [
            c for c in self.fallback_chain
            if not isinstance(c, CSVImportCollector)
        ]
        csv_collectors = [
            c for c in self.fallback_chain
            if isinstance(c, CSVImportCollector)
        ]
        if csv_collectors:
            csv_collector = csv_collectors[0]

        # 第一阶段: 浏览器/API 采集
        for collector in primary_collectors:
            try:
                logger.info("尝试用 %s 采集笔记: %s", collector.name, account.display_name)
                notes = await collector.collect_notes_data(account, target_date)
                for n in notes:
                    if n.note_id and n.note_id not in seen_ids:
                        all_notes.append(n)
                        seen_ids.add(n.note_id)
                if notes:
                    logger.info("%s 采集到 %d 篇笔记", collector.name, len(notes))
            except Exception as e:
                logger.warning("%s 采集失败: %s", collector.name, e)

        # 第二阶段: CSV 补充浏览器未覆盖的笔记
        if csv_collector and len(all_notes) < 200:
            try:
                logger.info("CSV 补充采集: %s", account.display_name)
                csv_notes = await csv_collector.collect_notes_data(account, target_date)
                added = 0
                for n in csv_notes:
                    if n.note_id and n.note_id not in seen_ids:
                        all_notes.append(n)
                        seen_ids.add(n.note_id)
                        added += 1
                if added:
                    logger.info("CSV 补充 %d 篇笔记（浏览器未覆盖）", added)
            except Exception as e:
                logger.warning("CSV 补充采集失败: %s", e)

        if not all_notes:
            raise CollectorError(
                f"所有采集器均未获取到笔记: {account.display_name}"
            )

        logger.info("笔记合并完成: %d 篇（%d 去重）", len(all_notes), len(seen_ids))
        return all_notes

    async def validate_connection(self) -> bool:
        """只要有一种方式连接成功即可。"""
        for collector in self.fallback_chain:
            try:
                if await collector.validate_connection():
                    return True
            except Exception:
                continue
        return False
