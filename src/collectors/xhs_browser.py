"""小红书浏览器采集器（Playwright CDP 模式）。

核心策略:
1. 连接已运行的真实 Chrome (CDP 模式) — 绕过 Playwright 特征检测
2. 拦截 XHR/API 响应获取 JSON 数据 — 比 HTML 解析更稳定
3. 降级方案: 解析 window.__INITIAL_STATE__ 嵌入数据

使用前准备:
1. 在本地 Chrome 登录小红书
2. 启动 Chrome 时添加: --remote-debugging-port=9222
3. 确保 .browser_state/storage.json 保存了登录态

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
from urllib.parse import urljoin

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
XHS_SEARCH_URL = f"{XHS_BASE_URL}/search_result/"

# API 响应匹配模式
XHS_API_PATTERNS = [
    "**/api/sns/web/v1/user/otherinfo**",     # 用户信息
    "**/api/sns/web/v1/note/feed**",           # 笔记列表
    "**/api/sns/web/v1/feed**",                 # 笔记详情
    "**/api/sns/web/v2/note/page**",           # 笔记分页
]


class XHSBrowserCollector(BaseCollector):
    """基于 Playwright CDP 的小红书数据采集器。

    Args:
        cdp_endpoint: Chrome DevTools Protocol 端点
        headless: 是否无头模式（推荐 False 以降低检测）
        min_delay: 最小操作间隔（秒）
        max_delay: 最大操作间隔（秒）
        timeout: 请求超时（秒）
        max_notes: 单次最大采集笔记数
        storage_state_path: 浏览器登录态持久化路径
    """

    def __init__(
        self,
        cdp_endpoint: str = "http://localhost:9222",
        headless: bool = False,
        min_delay: float = 1.5,
        max_delay: float = 5.0,
        timeout: int = 30,
        max_notes: int = 100,
        storage_state_path: str = ".browser_state/storage.json",
    ):
        super().__init__()
        self.cdp_endpoint = cdp_endpoint
        self.headless = headless
        self.min_delay = min_delay
        self.max_delay = max_delay
        self.timeout = timeout
        self.max_notes = max_notes
        self.storage_state_path = Path(storage_state_path)

        # 运行时状态
        self._browser = None
        self._context = None
        self._page = None
        self._api_responses: list[dict] = []
        self._is_logged_in = False

    # ── 浏览器生命周期 ──

    async def _ensure_browser(self):
        """确保浏览器连接可用。"""
        if self._browser and self._page:
            return

        try:
            from playwright.async_api import async_playwright
        except ImportError:
            raise CollectorError(
                "playwright 库未安装。请运行: pip install playwright && playwright install chromium"
            )

        self._playwright = await async_playwright().start()

        try:
            self._browser = await self._playwright.chromium.connect_over_cdp(
                self.cdp_endpoint
            )
            logger.info("已连接到 Chrome CDP: %s", self.cdp_endpoint)
        except Exception as e:
            raise BrowserConnectionError(
                f"无法连接到 Chrome CDP ({self.cdp_endpoint})。\n"
                f"请确保 Chrome 已启动并带有 --remote-debugging-port=9222 参数。\n"
                f"错误: {e}"
            ) from e

        # 创建上下文
        contexts = self._browser.contexts
        if contexts:
            self._context = contexts[0]
            logger.info("复用现有浏览器上下文")
        else:
            self._context = await self._browser.new_context(
                viewport={"width": 1920, "height": 1080},
                locale="zh-CN",
            )

        # 加载登录态
        if self.storage_state_path.exists():
            try:
                await self._context.storage_state(path=str(self.storage_state_path))
                logger.info("已加载浏览器登录态: %s", self.storage_state_path)
            except Exception as e:
                logger.warning("加载登录态失败: %s", e)

        pages = self._context.pages
        if pages:
            self._page = pages[0]
        else:
            self._page = await self._context.new_page()

        # 设置 API 响应拦截
        await self._setup_api_interception()

    async def _setup_api_interception(self):
        """拦截小红书 API 响应，获取结构化 JSON 数据。"""
        for pattern in XHS_API_PATTERNS:
            await self._page.route(
                pattern,
                lambda route, response: self._handle_api_response(route, response),
            )

    async def _handle_api_response(self, route, response):
        """处理拦截到的 API 响应。"""
        try:
            body = await response.text()
            data = json.loads(body)
            self._api_responses.append({
                "url": response.url,
                "status": response.status,
                "data": data,
                "timestamp": datetime.now(),
            })
        except (json.JSONDecodeError, Exception):
            pass
        await route.continue_()

    async def _random_delay(self, min_s: Optional[float] = None, max_s: Optional[float] = None):
        """操作间随机延迟，模拟人类行为。"""
        delay = random.uniform(
            min_s or self.min_delay,
            max_s or self.max_delay,
        )
        await asyncio.sleep(delay)

    async def _save_storage_state(self):
        """保存浏览器登录态。"""
        if self._context:
            try:
                self.storage_state_path.parent.mkdir(parents=True, exist_ok=True)
                await self._context.storage_state(
                    path=str(self.storage_state_path)
                )
                logger.debug("已保存登录态到: %s", self.storage_state_path)
            except Exception as e:
                logger.warning("保存登录态失败: %s", e)

    # ── 登录检测 ──

    async def _check_login_state(self) -> bool:
        """检测当前是否已登录小红书。"""
        await self._ensure_browser()
        try:
            await self._page.goto(
                f"{XHS_BASE_URL}/explore",
                wait_until="domcontentloaded",
                timeout=self.timeout * 1000,
            )
            await self._random_delay(2, 4)

            # 检查页面中是否存在登录按钮或用户信息
            is_logged_in = await self._page.evaluate("""() => {
                const loginBtn = document.querySelector('.login-btn, [class*="login"]');
                const userAvatar = document.querySelector('.user .avatar, [class*="avatar"]');
                return !loginBtn && !!userAvatar;
            }""")

            self._is_logged_in = is_logged_in
            if not is_logged_in:
                raise LoginSessionExpiredError(
                    "小红书登录态已过期。请在 Chrome 中重新登录小红书后重试。"
                )
            logger.info("✓ 小红书登录态正常")
            return True
        except LoginSessionExpiredError:
            raise
        except Exception as e:
            logger.warning("登录状态检测异常: %s", e)
            return False

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
        """采集账号概览数据。"""
        await self._check_login_state()
        self._api_responses.clear()

        profile_url = f"{XHS_USER_PROFILE_URL}{account.xhs_user_id}"
        logger.info("访问账号主页: %s (%s)", account.display_name, profile_url)

        try:
            response = await self._page.goto(
                profile_url,
                wait_until="domcontentloaded",
                timeout=self.timeout * 1000,
            )
            if response and response.status == 404:
                raise AccountNotFoundError(
                    f"账号不存在: {account.xhs_user_id} ({account.display_name})"
                )
            if response and response.status == 429:
                raise RateLimitError("请求频率过高，请稍后重试")

            await self._random_delay(3, 6)

            # 等待关键元素加载
            try:
                await self._page.wait_for_selector(
                    '[class*="user"], [class*="profile"]',
                    timeout=15_000,
                )
            except Exception:
                logger.warning("页面加载超时，尝试从 API 响应获取数据")

            # 检查验证码
            await self._detect_captcha()

            # 1. 优先从拦截的 API 响应中提取数据
            profile = self._extract_profile_from_api(account)

            # 2. 降级: 从 __INITIAL_STATE__ 提取
            if not profile or profile.follower_count == 0:
                logger.info("API 响应未获取到数据，尝试从页面状态获取")
                profile = await self._extract_profile_from_page(account)

            # 3. 即使数据为空也返回基础信息
            if not profile:
                profile = AccountProfile(
                    account_id=account.account_id,
                    xhs_user_id=account.xhs_user_id,
                    username=account.xhs_username,
                    display_name=account.display_name,
                    competitor=account.competitor,
                )

            return profile

        except (AccountNotFoundError, RateLimitError, CaptchaDetectedError):
            raise
        except Exception as e:
            raise CollectorError(f"采集账号概览失败: {e}") from e

    async def collect_notes_data(
        self, account: AccountInfo, target_date: Optional[date] = None
    ) -> list[NoteMetrics]:
        """采集账号的笔记数据。"""
        await self._check_login_state()
        self._api_responses.clear()

        logger.info(
            "采集笔记数据: %s (目标日期: %s, 最多 %d 篇)",
            account.display_name,
            target_date or "不限",
            self.max_notes,
        )

        try:
            # 1. 优先从 API 响应中获取笔记数据
            notes = self._extract_notes_from_api(account)

            # 2. 降级: 从 __INITIAL_STATE__ 获取
            if not notes:
                logger.info("API 响应未获取到笔记，尝试从页面获取")
                notes = await self._extract_notes_from_page(account)

            # 3. 如果数据不足，逐篇访问详情页获取
            if len(notes) < min(10, self.max_notes):
                logger.info("笔记数据不足，补充采集详情页...")
                api_note_ids = {n.note_id for n in notes}
                detail_notes = await self._collect_notes_from_profile_page(
                    account, api_note_ids
                )
                notes.extend(detail_notes)

            # 按目标日期过滤
            if target_date:
                notes = [
                    n for n in notes
                    if n.publish_date and n.publish_date == target_date
                ]

            # 限制数量
            notes = notes[:self.max_notes]
            logger.info(
                "笔记采集完成: %s — %d 篇",
                account.display_name, len(notes)
            )
            return notes

        except Exception as e:
            raise CollectorError(f"采集笔记数据失败: {e}") from e

    # ── 数据提取 (API 响应) ──

    def _extract_profile_from_api(
        self, account: AccountInfo
    ) -> Optional[AccountProfile]:
        """从拦截的 API 响应中提取账号概览数据。"""
        for resp in self._api_responses:
            data = resp.get("data", {})
            if not data.get("success", True):
                continue

            result = data.get("data", {})

            # user/otherinfo 接口
            if "user" in resp.get("url", ""):
                user = result.get("user", result)
                if user.get("userid") == account.xhs_user_id or not account.xhs_user_id:
                    return AccountProfile(
                        account_id=account.account_id,
                        xhs_user_id=user.get("userid", account.xhs_user_id),
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
        for resp in self._api_responses:
            data = resp.get("data", {})
            if not data.get("success", True):
                continue
            result = data.get("data", {})

            # scan or search notes
            items = result.get("notes", result.get("items", []))
            for item in items:
                note_card = item.get("note_card", item)
                note_id = note_card.get("note_id", item.get("id", ""))
                if not note_id:
                    continue

                interact = note_card.get("interact_info", {})
                note = NoteMetrics(
                    note_id=str(note_id),
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
                if note.note_id:
                    notes.append(note)

        return notes

    # ── 数据提取 (页面 JS) ──

    async def _extract_profile_from_page(
        self, account: AccountInfo
    ) -> Optional[AccountProfile]:
        """从 window.__INITIAL_STATE__ 提取账号概览。"""
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
        """从 window.__INITIAL_STATE__ 提取笔记列表。"""
        try:
            state = await self._get_initial_state()
            if not state:
                return []

            notes_data = (
                state.get("user", {})
                .get("notes", {})
                .get("notesList", [])
            )
            notes: list[NoteMetrics] = []
            for item in notes_data[:self.max_notes]:
                note_id = str(item.get("noteId", item.get("id", "")))
                if not note_id:
                    continue

                note = NoteMetrics(
                    note_id=note_id,
                    account_id=account.account_id,
                    title=item.get("displayTitle", item.get("title", "")),
                    note_type=item.get("type", "image"),
                    publish_date=self._parse_timestamp(
                        item.get("time", item.get("createTime", 0))
                    ),
                    url=f"{XHS_NOTE_DETAIL_URL}{note_id}",
                    views=self._safe_int(item.get("viewCount", 0)),
                    likes=self._safe_int(item.get("likedCount", 0)),
                    favorites=self._safe_int(item.get("collectedCount", 0)),
                    comments=self._safe_int(item.get("commentCount", 0)),
                    shares=self._safe_int(item.get("shareCount", 0)),
                )
                notes.append(note)

            return notes
        except Exception as e:
            logger.debug("__INITIAL_STATE__ 笔记解析失败: %s", e)
            return []

    async def _collect_notes_from_profile_page(
        self, account: AccountInfo, exclude_ids: set[str]
    ) -> list[NoteMetrics]:
        """通过滚动账号主页的笔记列表，点击进入详情页采集数据。"""
        notes: list[NoteMetrics] = []

        try:
            # 滚动加载笔记列表
            for scroll_i in range(5):  # 最多滚动5屏
                await self._page.evaluate(
                    "window.scrollBy(0, window.innerHeight * 0.8)"
                )
                await self._random_delay(1, 3)

            # 获取笔记链接
            note_links = await self._page.evaluate("""() => {
                const links = document.querySelectorAll(
                    'a[href*="/explore/"], a[href*="/discovery/item/"]'
                );
                return [...new Set(
                    Array.from(links).map(a => a.href).filter(h => h)
                )].slice(0, 50);
            }""")

            collected = 0
            for link in note_links:
                if collected >= self.max_notes:
                    break

                note_id = self._extract_note_id_from_url(link)
                if not note_id or note_id in exclude_ids:
                    continue

                try:
                    await self._page.goto(
                        link,
                        wait_until="domcontentloaded",
                        timeout=self.timeout * 1000,
                    )
                    await self._random_delay(1.5, 4)
                    await self._detect_captcha()

                    note = await self._extract_single_note(account, note_id, link)
                    if note:
                        notes.append(note)
                        collected += 1
                except Exception as e:
                    logger.warning("笔记详情页采集失败 %s: %s", note_id, e)
                    continue

        except Exception as e:
            logger.warning("从页面滚动采集笔记时出错: %s", e)

        return notes

    async def _extract_single_note(
        self, account: AccountInfo, note_id: str, url: str
    ) -> Optional[NoteMetrics]:
        """从笔记详情页提取单篇笔记数据。"""
        try:
            # 优先从 API 响应获取
            for resp in self._api_responses[-5:]:  # 最近5个响应
                data = resp.get("data", {}).get("data", {})
                note_data = data.get("note", data.get("items", [{}])[0] if data.get("items") else {})
                raw_id = str(note_data.get("note_id", note_data.get("id", "")))
                if raw_id == note_id:
                    interact = note_data.get("interact_info", {})
                    return NoteMetrics(
                        note_id=note_id,
                        account_id=account.account_id,
                        title=note_data.get("display_title", note_data.get("title", "")),
                        note_type=note_data.get("type", "image"),
                        publish_date=self._parse_timestamp(
                            note_data.get("time", note_data.get("create_time", 0))
                        ),
                        url=url,
                        views=self._safe_int(interact.get("view_count", 0)),
                        likes=self._safe_int(interact.get("liked_count", 0)),
                        favorites=self._safe_int(interact.get("collected_count", 0)),
                        comments=self._safe_int(interact.get("comment_count", 0)),
                        shares=self._safe_int(interact.get("share_count", 0)),
                    )

            # 降级: 从页面 JS 提取
            state = await self._get_initial_state()
            if state:
                note_detail = (
                    state.get("note", {})
                    .get("noteDetailMap", {})
                    .get(note_id, {})
                    .get("note", {})
                )
                if note_detail:
                    interact = note_detail.get("interactInfo", {})
                    return NoteMetrics(
                        note_id=note_id,
                        account_id=account.account_id,
                        title=note_detail.get("displayTitle", note_detail.get("title", "")),
                        note_type=note_detail.get("type", "image"),
                        publish_date=self._parse_timestamp(
                            note_detail.get("time", note_detail.get("createTime", 0))
                        ),
                        url=url,
                        views=self._safe_int(interact.get("viewCount", 0)),
                        likes=self._safe_int(interact.get("likedCount", 0)),
                        favorites=self._safe_int(interact.get("collectedCount", 0)),
                        comments=self._safe_int(interact.get("commentCount", 0)),
                        shares=self._safe_int(interact.get("shareCount", 0)),
                    )
        except Exception as e:
            logger.debug("提取笔记详情失败 %s: %s", note_id, e)

        return None

    # ── 辅助方法 ──

    async def _get_initial_state(self) -> Optional[dict]:
        """获取页面的 window.__INITIAL_STATE__ 数据。"""
        try:
            state_text = await self._page.evaluate("""() => {
                try {
                    const state = window.__INITIAL_STATE__;
                    return JSON.stringify(state);
                } catch(e) {
                    return null;
                }
            }""")
            if state_text and state_text != "null":
                # 修复已知的小红书 __INITIAL_STATE__ bug:
                # undefined 值被替换为 ""（空字符串）
                fixed = re.sub(
                    r':\s*""\s*([,}])', r': null\1', state_text
                )
                return json.loads(fixed)
        except Exception as e:
            logger.debug("获取 __INITIAL_STATE__ 失败: %s", e)
        return None

    async def _detect_captcha(self) -> None:
        """检测是否触发了验证码。"""
        try:
            has_captcha = await self._page.evaluate("""() => {
                const body = document.body.innerText || '';
                const captchaKeywords = ['验证码', '滑块验证', '请完成验证', 'captcha', 'verify'];
                return captchaKeywords.some(kw => body.includes(kw));
            }""")
            if has_captcha:
                raise CaptchaDetectedError(
                    "检测到验证码！请在 Chrome 浏览器中手动完成验证后重试。"
                )
        except CaptchaDetectedError:
            raise
        except Exception:
            pass

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

    @staticmethod
    def _extract_note_id_from_url(url: str) -> str:
        """从笔记 URL 中提取笔记 ID。"""
        patterns = [
            r"/explore/([a-f0-9]{24})",
            r"/discovery/item/([a-f0-9]{24})",
            r"/note/([a-f0-9]{24})",
        ]
        for pattern in patterns:
            match = re.search(pattern, url)
            if match:
                return match.group(1)
        return ""

    # ── 资源清理 ──

    async def close(self):
        """关闭浏览器连接。"""
        await self._save_storage_state()
        if hasattr(self, "_playwright") and self._playwright:
            await self._playwright.stop()
        self._browser = None
        self._page = None
        self._context = None
        logger.info("浏览器连接已关闭")


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
        """按优先级降级采集笔记。"""
        last_error = None
        for collector in self.fallback_chain:
            try:
                logger.info(
                    "尝试用 %s 采集笔记: %s",
                    collector.name, account.display_name,
                )
                notes = await collector.collect_notes_data(account, target_date)
                if notes:
                    return notes
            except Exception as e:
                last_error = e
                logger.warning("%s 采集失败: %s", collector.name, e)
                continue

        raise CollectorError(
            f"所有采集器均未获取到笔记: {account.display_name}"
        ) from last_error

    async def validate_connection(self) -> bool:
        """只要有一种方式连接成功即可。"""
        for collector in self.fallback_chain:
            try:
                if await collector.validate_connection():
                    return True
            except Exception:
                continue
        return False
