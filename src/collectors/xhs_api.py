"""小红书开放平台 API 采集器。

需要有企业认证 + 专业号蓝V 认证后才能使用。
API 文档参考: https://open.xiaohongshu.com

限制:
- access_token 有效期为 2 小时，需自动刷新
- 默认 QPS ≤ 10，企业认证后 ≤ 100
- 日调用上限 50,000 次
"""

import hashlib
import hmac
import logging
import time
from datetime import date, datetime, timedelta
from typing import Optional
from urllib.parse import urlencode

import httpx

from src.collectors.base import BaseCollector
from src.collectors.models import AccountProfile, NoteMetrics
from src.core.config import AccountInfo
from src.core.exceptions import CollectorError, XHSApiError, XHSAuthError

logger = logging.getLogger(__name__)


class XHSApiCollector(BaseCollector):
    """基于小红书开放平台 API 的数据采集器。

    Args:
        app_key: API App Key
        app_secret: API App Secret
        base_url: API 基础 URL
    """

    def __init__(
        self,
        app_key: str,
        app_secret: str,
        base_url: str = "https://open-api.xiaohongshu.com",
    ):
        super().__init__()
        self.app_key = app_key
        self.app_secret = app_secret
        self.base_url = base_url.rstrip("/")
        self._token: Optional[str] = None
        self._token_expires_at: datetime = datetime.min
        self._client = httpx.AsyncClient(timeout=30.0)

    # ── 鉴权 ──

    async def _get_token(self) -> str:
        """获取 access_token，自动刷新。"""
        if self._token and datetime.now() < self._token_expires_at - timedelta(minutes=5):
            return self._token

        try:
            resp = await self._client.post(
                f"{self.base_url}/oauth2/access_token",
                json={
                    "app_key": self.app_key,
                    "app_secret": self.app_secret,
                    "grant_type": "client_credentials",
                },
            )
            data = resp.json()
            if data.get("code") != 200:
                raise XHSAuthError(
                    f"获取小红书 access_token 失败: {data.get('msg', '')}"
                )
            self._token = data["data"]["access_token"]
            self._token_expires_at = datetime.now() + timedelta(
                seconds=data["data"].get("expires_in", 7200)
            )
            logger.info("✓ 小红书 API token 已刷新")
            return self._token
        except XHSAuthError:
            raise
        except Exception as e:
            raise XHSAuthError(f"小红书 API 鉴权异常: {e}") from e

    def _sign(self, params: dict) -> str:
        """HMAC-SHA256 签名。"""
        sorted_params = sorted(params.items())
        sign_str = "&".join(f"{k}={v}" for k, v in sorted_params)
        sign = hmac.new(
            self.app_secret.encode(),
            sign_str.encode(),
            hashlib.sha256,
        ).hexdigest()
        return sign

    async def _request(
        self, method: str, path: str, params: Optional[dict] = None
    ) -> dict:
        """发送 API 请求（含鉴权和签名）。"""
        token = await self._get_token()

        if params is None:
            params = {}
        params["app_key"] = self.app_key
        params["access_token"] = token
        params["timestamp"] = str(int(time.time()))
        params["sign"] = self._sign(params)

        url = f"{self.base_url}{path}"
        try:
            if method.upper() == "GET":
                resp = await self._client.get(url, params=params)
            else:
                resp = await self._client.post(url, json=params)

            data = resp.json()
            if data.get("code") != 200:
                raise XHSApiError(
                    f"小红书 API 调用失败: code={data.get('code')}, "
                    f"msg={data.get('msg', '')}"
                )
            return data.get("data", {})
        except XHSApiError:
            raise
        except Exception as e:
            raise XHSApiError(f"小红书 API 请求异常: {e}") from e

    # ── 抽象方法实现 ──

    async def collect_account_profile(
        self, account: AccountInfo
    ) -> AccountProfile:
        """通过 API 获取账号概览。"""
        try:
            data = await self._request(
                "GET",
                "/api/sns/v1/user/profile",
                {"user_id": account.xhs_user_id},
            )
            user = data.get("user_info", data)
            return AccountProfile(
                account_id=account.account_id,
                xhs_user_id=user.get("user_id", account.xhs_user_id),
                username=user.get("nickname", account.xhs_username),
                display_name=account.display_name,
                follower_count=user.get("fans_count", 0),
                following_count=user.get("follow_count", 0),
                total_likes=user.get("liked_count", 0),
                total_collections=user.get("collected_count", 0),
                competitor=account.competitor,
            )
        except Exception as e:
            raise CollectorError(f"API 账号概览采集失败: {e}") from e

    async def collect_notes_data(
        self, account: AccountInfo, target_date: Optional[date] = None
    ) -> list[NoteMetrics]:
        """通过 API 获取笔记数据。

        注意：具体 API 端点可能因小红书开放平台权限而异。
        """
        try:
            params = {"user_id": account.xhs_user_id, "page_size": 50}
            if target_date:
                params["start_date"] = target_date.isoformat()
                params["end_date"] = target_date.isoformat()

            data = await self._request(
                "GET",
                "/api/sns/v1/user/notes",
                params,
            )

            notes: list[NoteMetrics] = []
            for item in data.get("notes", data.get("items", [])):
                notes.append(NoteMetrics(
                    note_id=str(item.get("note_id", item.get("id", ""))),
                    account_id=account.account_id,
                    title=item.get("title", ""),
                    note_type=item.get("type", "image"),
                    publish_date=target_date,
                    url=item.get("url", ""),
                    views=item.get("view_count", 0),
                    likes=item.get("liked_count", 0),
                    favorites=item.get("collected_count", 0),
                    comments=item.get("comment_count", 0),
                    shares=item.get("share_count", 0),
                ))

            logger.info(
                "API 笔记采集完成: %s — %d 篇",
                account.display_name, len(notes),
            )
            return notes
        except Exception as e:
            raise CollectorError(f"API 笔记采集失败: {e}") from e

    async def validate_connection(self) -> bool:
        """验证 API 连接。"""
        try:
            await self._get_token()
            return True
        except Exception as e:
            logger.error("API 连接验证失败: %s", e)
            return False

    async def close(self):
        """关闭 HTTP 客户端。"""
        await self._client.aclose()
