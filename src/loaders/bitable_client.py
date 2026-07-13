"""飞书多维表格 API 客户端。

封装：
- tenant_access_token 生命周期管理（自动刷新）
- 批量 CRUD 操作
- 重试 + 指数退避
"""

import time
from datetime import datetime, timedelta
from typing import Any, Optional

import lark_oapi as lark
from lark_oapi.api.bitable.v1 import (
    BatchCreateAppTableRecordRequest,
    BatchCreateAppTableRecordRequestBody,
    BatchUpdateAppTableRecordRequest,
    BatchUpdateAppTableRecordRequestBody,
    CreateAppTableRequest,
    CreateAppTableRequestBody,
    ListAppTableRecordRequest,
    ListAppTableRecordResponse,
    ListAppTableRequest,
    AppTableRecord,
)
from lark_oapi.api.bitable.v1.model.req_table import ReqTable
from lark_oapi.api.auth.v3 import (
    InternalTenantAccessTokenRequest,
    InternalTenantAccessTokenRequestBody,
)
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from src.core.config import FeishuConfig, load_config
from src.core.exceptions import (
    FeishuApiError,
    FeishuAuthError,
    FeishuRateLimitError,
)


class BitableClient:
    """飞书多维表格 API 客户端。

    用法:
        client = BitableClient(config.feishu)
        client.ensure_token()
        records = client.list_records(table_id)
    """

    def __init__(self, config: FeishuConfig | None = None):
        self.config = config or load_config().feishu
        self._client: Optional[lark.Client] = None
        self._token: Optional[str] = None
        self._token_expires_at: datetime = datetime.min

        if not self.config.app_id or not self.config.app_secret:
            raise FeishuAuthError(
                "飞书 App ID 或 App Secret 未配置。"
                "请在 .env 文件中设置 FEISHU_APP_ID 和 FEISHU_APP_SECRET。"
            )

    # ── 鉴权 ──

    def ensure_token(self) -> str:
        """获取有效 token，必要时自动刷新。"""
        if self._token and datetime.now() < self._token_expires_at - timedelta(minutes=5):
            return self._token

        self._client = (
            lark.Client.builder()
            .app_id(self.config.app_id)
            .app_secret(self.config.app_secret)
            .log_level(lark.LogLevel.WARNING)
            .build()
        )

        try:
            # lark-oapi v1.7+ API: internal tenant access token
            body = (
                InternalTenantAccessTokenRequestBody.builder()
                .app_id(self.config.app_id)
                .app_secret(self.config.app_secret)
                .build()
            )
            req = (
                InternalTenantAccessTokenRequest.builder()
                .request_body(body)
                .build()
            )
            resp = self._client.auth.v3.tenant_access_token.internal(req)
            if not resp.success():
                raise FeishuAuthError(
                    f"获取飞书 tenant_access_token 失败: "
                    f"code={resp.code}, msg={resp.msg}"
                )
            # 解析 raw response 获取 token
            import json
            raw_data = json.loads(resp.raw.content) if resp.raw and resp.raw.content else {}
            self._token = raw_data.get("tenant_access_token", "")
            # token 有效期 2 小时，提前 5 分钟刷新
            self._token_expires_at = datetime.now() + timedelta(hours=1, minutes=55)
            return self._token
        except FeishuAuthError:
            raise
        except Exception as e:
            raise FeishuAuthError(f"飞书鉴权异常: {e}") from e

    @property
    def app_token(self) -> str:
        return self.config.bitable_app_token

    # ── 表操作 ──

    def list_tables(self) -> list[dict]:
        """列出多维表格中的所有数据表。"""
        self.ensure_token()
        req = ListAppTableRequest.builder() \
            .app_token(self.app_token) \
            .build()
        resp = self._client.bitable.v1.app_table.list(req)
        if not resp.success():
            raise FeishuApiError(
                f"列出数据表失败: code={resp.code}, msg={resp.msg}"
            )
        items = resp.data.items if resp.data and resp.data.items else []
        return [
            {"table_id": t.table_id, "name": t.name, "revision": t.revision}
            for t in items
        ]

    def create_table(self, name: str, default_view_name: str = "") -> str:
        """创建新数据表并返回 table_id。"""
        self.ensure_token()
        builder = ReqTable.builder().name(name)
        if default_view_name:
            builder.default_view_name(default_view_name)
        table_req = builder.build()
        body = (
            CreateAppTableRequestBody.builder()
            .table(table_req)
            .build()
        )
        req = (
            CreateAppTableRequest.builder()
            .app_token(self.app_token)
            .request_body(body)
            .build()
        )
        resp = self._client.bitable.v1.app_table.create(req)
        if not resp.success():
            raise FeishuApiError(
                f"创建数据表失败: code={resp.code}, msg={resp.msg}"
            )
        return resp.data.table_id or ""

    # ── 字段操作 ──

    def add_field(
        self,
        table_id: str,
        field_name: str,
        field_type: int,
        options: list[dict] | None = None,
    ) -> dict:
        """为数据表添加字段（幂等：字段已存在则跳过）。

        Args:
            table_id: 数据表ID
            field_name: 字段名称
            field_type: 飞书字段类型代码 (1=Text, 2=Number, 3=SingleSelect, ...)
            options: 仅 SingleSelect/MultiSelect 需要，[{"name": "选项名", "color": 1}, ...]

        Returns:
            {"field_id": "...", "field_name": "...", "created": True/False}
        """
        self.ensure_token()
        import requests as http_requests

        headers = {
            "Authorization": f"Bearer {self._token}",
            "Content-Type": "application/json",
        }
        url = (
            f"https://open.feishu.cn/open-apis/bitable/v1/apps"
            f"/{self.app_token}/tables/{table_id}/fields"
        )

        # 检查字段是否已存在
        existing = self._list_fields(table_id)
        for f in existing:
            if f["field_name"] == field_name:
                return {
                    "field_id": f["field_id"],
                    "field_name": field_name,
                    "created": False,
                }

        body: dict[str, Any] = {
            "field_name": field_name,
            "type": field_type,
        }
        if options:
            body["property"] = {"options": options}

        resp = http_requests.post(url, headers=headers, json=body)
        data = resp.json()
        if data.get("code") != 0:
            raise FeishuApiError(
                f"添加字段失败 [{field_name}]: code={data.get('code')}, msg={data.get('msg')}"
            )

        field_data = data.get("data", {}).get("field", {})
        return {
            "field_id": field_data.get("field_id", ""),
            "field_name": field_data.get("field_name", field_name),
            "created": True,
        }

    def _list_fields(self, table_id: str) -> list[dict]:
        """列出数据表的所有字段。"""
        import requests as http_requests

        headers = {
            "Authorization": f"Bearer {self._token}",
        }
        url = (
            f"https://open.feishu.cn/open-apis/bitable/v1/apps"
            f"/{self.app_token}/tables/{table_id}/fields"
        )
        fields: list[dict] = []
        page_token: str | None = None
        while True:
            params = {"page_size": 100}
            if page_token:
                params["page_token"] = page_token
            resp = http_requests.get(url, headers=headers, params=params)
            data = resp.json()
            if data.get("code") != 0:
                raise FeishuApiError(
                    f"列出字段失败: code={data.get('code')}, msg={data.get('msg')}"
                )
            items = data.get("data", {}).get("items", [])
            for item in items:
                fields.append({
                    "field_id": item.get("field_id", ""),
                    "field_name": item.get("field_name", ""),
                    "type": item.get("type", 0),
                })
            if not data.get("data", {}).get("has_more"):
                break
            page_token = data.get("data", {}).get("page_token")
        return fields

    # ── 记录操作 ──

    def list_records(
        self,
        table_id: str,
        page_size: int = 500,
        page_token: Optional[str] = None,
        filter_expr: Optional[str] = None,
    ) -> dict:
        """列出记录（分页）。"""
        self.ensure_token()
        builder = (
            ListAppTableRecordRequest.builder()
            .app_token(self.app_token)
            .table_id(table_id)
            .page_size(page_size)
        )
        if page_token:
            builder.page_token(page_token)
        req = builder.build()
        resp = self._client.bitable.v1.app_table_record.list(req)
        if not resp.success():
            raise FeishuApiError(
                f"列出记录失败: code={resp.code}, msg={resp.msg}"
            )
        records = []
        if resp.data and resp.data.items:
            for item in resp.data.items:
                record = {
                    "record_id": item.record_id,
                    "fields": item.fields or {},
                }
                records.append(record)
        return {
            "records": records,
            "has_more": resp.data.has_more if resp.data else False,
            "page_token": resp.data.page_token if resp.data else None,
        }

    @retry(
        retry=retry_if_exception_type(FeishuRateLimitError),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=30),
    )
    def batch_create_records(
        self, table_id: str, records: list[dict[str, Any]]
    ) -> list[dict]:
        """批量创建记录（最多 500 条/次）。

        Args:
            table_id: 数据表ID
            records: [{"fields": {"字段名": 值, ...}}, ...]

        Returns:
            [{"record_id": "xxx", "fields": {...}}, ...]
        """
        if not records:
            return []

        self.ensure_token()

        app_table_records = []
        for r in records:
            app_table_records.append(
                AppTableRecord.builder().fields(r.get("fields", r)).build()
            )

        body = BatchCreateAppTableRecordRequestBody.builder() \
            .records(app_table_records) \
            .build()
        req = BatchCreateAppTableRecordRequest.builder() \
            .app_token(self.app_token) \
            .table_id(table_id) \
            .request_body(body) \
            .build()

        resp = self._client.bitable.v1.app_table_record.batch_create(req)

        if not resp.success():
            if resp.code == 99991400:
                raise FeishuRateLimitError(f"飞书 API 频率限制: {resp.msg}")
            raise FeishuApiError(
                f"批量创建记录失败: code={resp.code}, msg={resp.msg}"
            )

        result = []
        if resp.data and resp.data.records:
            for item in resp.data.records:
                result.append({
                    "record_id": item.record_id,
                    "fields": item.fields or {},
                })
        return result

    @retry(
        retry=retry_if_exception_type(FeishuRateLimitError),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=30),
    )
    def batch_update_records(
        self, table_id: str, records: list[dict[str, Any]]
    ) -> list[dict]:
        """批量更新记录（最多 500 条/次）。

        Args:
            table_id: 数据表ID
            records: [{"record_id": "rec_xxx", "fields": {"字段名": 值, ...}}, ...]

        Returns:
            [{"record_id": "xxx", "fields": {...}}, ...]
        """
        if not records:
            return []

        self.ensure_token()

        app_table_records = []
        for r in records:
            app_table_records.append(
                AppTableRecord.builder()
                .record_id(r["record_id"])
                .fields(r.get("fields", {}))
                .build()
            )

        body = BatchUpdateAppTableRecordRequestBody.builder() \
            .records(app_table_records) \
            .build()
        req = BatchUpdateAppTableRecordRequest.builder() \
            .app_token(self.app_token) \
            .table_id(table_id) \
            .request_body(body) \
            .build()

        resp = self._client.bitable.v1.app_table_record.batch_update(req)

        if not resp.success():
            if resp.code == 99991400:
                raise FeishuRateLimitError(f"飞书 API 频率限制: {resp.msg}")
            raise FeishuApiError(
                f"批量更新记录失败: code={resp.code}, msg={resp.msg}"
            )

        result = []
        if resp.data and resp.data.records:
            for item in resp.data.records:
                result.append({
                    "record_id": item.record_id,
                    "fields": item.fields or {},
                })
        return result

    def upsert_records(
        self,
        table_id: str,
        records: list[dict[str, Any]],
        match_field: str = "笔记ID",
    ) -> dict:
        """按匹配字段 upsert（有则更新，无则创建）。

        先拉取全表，按 match_field 匹配现有记录决定更新或新增。
        适用于数据量不大的场景（< 2000 行）。

        Returns:
            {"created": N, "updated": N}
        """
        # 拉取已有记录，建立 match_field -> record_id 的映射
        existing_map: dict[str, str] = {}
        page_token = None
        while True:
            result = self.list_records(table_id, page_token=page_token)
            for rec in result["records"]:
                match_value = str(rec["fields"].get(match_field, ""))
                if match_value:
                    existing_map[match_value] = rec["record_id"]
            if not result["has_more"]:
                break
            page_token = result["page_token"]

        created = []
        updated = []

        for batch_start in range(0, len(records), 500):
            batch = records[batch_start : batch_start + 500]
            create_batch = []
            update_batch = []

            for rec in batch:
                match_value = str(rec.get("fields", {}).get(match_field, ""))
                if match_value and match_value in existing_map:
                    update_batch.append({
                        "record_id": existing_map[match_value],
                        "fields": rec.get("fields", rec),
                    })
                else:
                    create_batch.append(rec)

            if create_batch:
                created.extend(self.batch_create_records(table_id, create_batch))
                # 模拟延时避免限流
                if len(create_batch) >= 400:
                    time.sleep(1)

            if update_batch:
                updated.extend(self.batch_update_records(table_id, update_batch))
                if len(update_batch) >= 400:
                    time.sleep(1)

        return {"created": len(created), "updated": len(updated)}


# ── 全局单例 ──

_client: Optional[BitableClient] = None


def get_bitable_client() -> BitableClient:
    """获取全局 BitableClient 实例。"""
    global _client
    if _client is None:
        _client = BitableClient()
    return _client
