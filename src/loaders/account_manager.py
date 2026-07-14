"""从飞书多维表格 "账号管理" 表加载账号配置。

提供与 load_accounts() YAML 模式兼容的 AccountInfo 列表，
支持通过 Checkbox "启用" 字段过滤。
"""

import logging
from typing import Optional

from src.core.config import AccountInfo
from src.core.exceptions import XHSFeishuSyncError
from src.loaders.bitable_client import BitableClient, get_bitable_client

logger = logging.getLogger(__name__)


class FeishuAccountManager:
    """从飞书 "账号管理" 表读取监控账号配置。

    用法:
        manager = FeishuAccountManager()
        if manager.enabled:
            accounts = manager.load_accounts()  # -> list[AccountInfo]
    """

    TABLE_NAME = "账号管理"

    # ── 字段名常量（与 bitable_schema.yaml 中 account_manager 保持一致）──
    FIELD_ACCOUNT_ID = "账号ID"
    FIELD_XHS_USER_ID = "XHS用户ID"
    FIELD_XHS_USERNAME = "XHS用户名"
    FIELD_DISPLAY_NAME = "显示名称"
    FIELD_ACCOUNT_TYPE = "账号类型"
    FIELD_ENABLED = "启用"
    FIELD_FOLLOWER_COUNT = "粉丝数"
    FIELD_FOLLOWING_COUNT = "关注数"
    FIELD_TOTAL_LIKES = "总获赞"
    FIELD_TOTAL_COLLECTIONS = "总收藏"

    def __init__(self, client: Optional[BitableClient] = None):
        """初始化账号管理器。

        Args:
            client: 可选 BitableClient 实例。None 则使用全局单例。
        """
        self._client: Optional[BitableClient] = None
        self._table_id: Optional[str] = None
        self._enabled: bool = True

        try:
            self._client = client or get_bitable_client()
            self._table_id = self._resolve_table_id()
        except XHSFeishuSyncError as e:
            self._enabled = False
            logger.warning("飞书账号管理不可用: %s", e)

    @property
    def enabled(self) -> bool:
        """是否可用（飞书已连接且 "账号管理" 表存在）。"""
        return self._enabled and self._table_id is not None

    def _resolve_table_id(self) -> Optional[str]:
        """从飞书 Bitable 中查找 "账号管理" 表的 table_id。"""
        if not self._client:
            return None
        try:
            tables = self._client.list_tables()
        except Exception as e:
            logger.warning("获取飞书表列表失败: %s", e)
            return None

        for t in tables:
            if t.get("name") == self.TABLE_NAME:
                return t["table_id"]

        logger.info(
            "飞书中尚未创建 '%s' 表。运行 'xhs-feishu setup' 自动创建。",
            self.TABLE_NAME,
        )
        return None

    def load_accounts(self) -> list[AccountInfo]:
        """从飞书表加载所有启用的账号，转为 AccountInfo 列表。

        Returns:
            list[AccountInfo]: 自有账号在前，竞品账号在后。

        Raises:
            RuntimeError: 飞书不可用或表不存在时。
        """
        if not self.enabled:
            raise RuntimeError(
                "飞书账号管理表不可用。"
                "请先运行 'xhs-feishu setup' 创建表，或使用 --source yaml 模式。"
            )

        records = self._fetch_all_records()
        accounts: list[AccountInfo] = []
        for rec in records:
            account = self._parse_record(rec)
            if account is not None:
                accounts.append(account)

        own = [a for a in accounts if not a.competitor]
        competitors = [a for a in accounts if a.competitor]
        logger.info(
            "从飞书加载账号: %d 自有, %d 竞品（共 %d 条记录扫描）",
            len(own), len(competitors), len(records),
        )
        return own + competitors

    def _fetch_all_records(self) -> list[dict]:
        """分页拉取 "账号管理" 表全部记录。"""
        all_records: list[dict] = []
        page_token: Optional[str] = None

        while True:
            result = self._client.list_records(
                self._table_id, page_token=page_token
            )
            records = result.get("records", [])
            all_records.extend(records)

            if not result.get("has_more"):
                break
            page_token = result.get("page_token")

        return all_records

    def _parse_record(self, record: dict) -> Optional[AccountInfo]:
        """将单行飞书记录转为 AccountInfo，未启用或数据不完整则返回 None。

        校验规则:
        - 「启用」Checkbox 必须勾选
        - 「账号ID」「XHS用户ID」必须非空
        """
        fields = record.get("fields", {})

        # ── 仅处理已启用的账号 ──
        if not fields.get(self.FIELD_ENABLED, False):
            return None

        account_id = str(fields.get(self.FIELD_ACCOUNT_ID, "")).strip()
        xhs_user_id = str(fields.get(self.FIELD_XHS_USER_ID, "")).strip()

        if not account_id or not xhs_user_id:
            logger.warning(
                "跳过缺少必填字段的账号行: account_id=%r, xhs_user_id=%r",
                account_id, xhs_user_id,
            )
            return None

        xhs_username = str(fields.get(self.FIELD_XHS_USERNAME, "")).strip()
        display_name = str(fields.get(self.FIELD_DISPLAY_NAME, "")).strip()

        # ── 账号类型 → competitor ──
        account_type = str(fields.get(self.FIELD_ACCOUNT_TYPE, ""))
        competitor = account_type == "竞品账号"

        return AccountInfo(
            account_id=account_id,
            xhs_user_id=xhs_user_id,
            xhs_username=xhs_username,
            display_name=display_name or account_id,
            competitor=competitor,
            follower_count=self._safe_int(fields.get(self.FIELD_FOLLOWER_COUNT)),
            following_count=self._safe_int(fields.get(self.FIELD_FOLLOWING_COUNT)),
            total_likes=self._safe_int(fields.get(self.FIELD_TOTAL_LIKES)),
            total_collections=self._safe_int(fields.get(self.FIELD_TOTAL_COLLECTIONS)),
        )

    @staticmethod
    def _safe_int(value) -> int:
        """安全转整数，空值/非数字返回 0。"""
        try:
            return int(value)
        except (ValueError, TypeError):
            return 0
