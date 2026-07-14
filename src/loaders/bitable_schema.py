"""飞书多维表格 Schema 管理器。

负责：
- 根据 bitable_schema.yaml 创建表/字段
- 幂等性：存在即跳过，只增不删
- Schema 版本追踪
"""

from typing import Any

import click
import yaml

from src.core.config import PROJECT_ROOT, load_config
from src.core.exceptions import BitableSchemaError
from src.loaders.bitable_client import BitableClient, get_bitable_client


# 飞书字段类型名称 -> 类型代码 映射
FIELD_TYPE_MAP: dict[str, int] = {
    "Text": 1,
    "Number": 2,
    "SingleSelect": 3,
    "MultiSelect": 4,
    "DateTime": 5,
    "Checkbox": 7,
    "User": 11,
    "Url": 15,
    "Attachment": 17,
    "Link": 18,  # 单向关联
    "Phone": 13,
    "Location": 22,
    "Currency": 26,
    "Progress": 14,
    "Rating": 27,
}


def load_schema_config() -> dict:
    """加载 bitable_schema.yaml 配置。"""
    path = PROJECT_ROOT / "config" / "bitable_schema.yaml"
    if not path.exists():
        raise BitableSchemaError(f"Schema 配置文件不存在: {path}")
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


class BitableSchemaManager:
    """多维表格 Schema 管理器。"""

    def __init__(self, client: BitableClient | None = None):
        self.client = client or get_bitable_client()
        self.app_token = self.client.config.bitable_app_token

    # ── 表管理 ──

    def get_existing_tables(self) -> dict[str, str]:
        """获取已存在的表: {表名: table_id}。"""
        tables = self.client.list_tables()
        return {t["name"]: t["table_id"] for t in tables}

    def ensure_table(self, name: str) -> str:
        """确保表存在，存在则返回 table_id，不存在则创建。"""
        existing = self.get_existing_tables()
        if name in existing:
            return existing[name]
        table_id = self.client.create_table(name)
        click.echo(f"  ✓ 创建表: {name} ({table_id})")
        return table_id

    def setup_all_tables(self) -> dict[str, str]:
        """根据 schema 配置创建所有表并添加字段。返回 {table_key: table_id}。"""
        schema = load_schema_config()
        table_ids: dict[str, str] = {}
        existing_tables = self.get_existing_tables()

        for table_key, table_def in schema.get("tables", {}).items():
            name = table_def["name"]
            if name in existing_tables:
                table_ids[table_key] = existing_tables[name]
                click.echo(f"  - 表已存在: {name} ({existing_tables[name]})")
            else:
                table_id = self.ensure_table(name)
                table_ids[table_key] = table_id
                existing_tables[name] = table_id  # 更新缓存

            # 为每张表添加字段
            tid = table_ids[table_key]
            for field_def in table_def.get("fields", []):
                field_name = field_def["name"]
                field_type = field_def["type"]
                options = field_def.get("options", None)
                try:
                    result = self.client.add_field(tid, field_name, field_type, options)
                    if result.get("created"):
                        click.echo(f"    ✓ 添加字段: {field_name}")
                except Exception as e:
                    click.echo(f"    ⚠ 字段 {field_name} 添加失败: {e}")

        return table_ids

    def print_schema_summary(self) -> None:
        """打印当前多维表格的 Schema 摘要。"""
        schema = load_schema_config()
        tables = self.get_existing_tables()

        click.echo(f"\n多维表格: {self.app_token}")
        click.echo("=" * 60)

        for table_key, table_def in schema.get("tables", {}).items():
            name = table_def["name"]
            status = "✓" if name in tables else "✗ (未创建)"
            fields_count = len(table_def.get("fields", []))
            click.echo(f"  [{status}] {name} ({table_key}) — {fields_count} 个字段定义了")

        click.echo("=" * 60)
        click.echo(f"共 {len(schema.get('tables', {}))} 张表")


if __name__ == "__main__":
    manager = BitableSchemaManager()
    manager.print_schema_summary()
