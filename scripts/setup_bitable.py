#!/usr/bin/env python
"""一键初始化飞书多维表格。

在飞书多维表格中创建所需的数据表（如不存在）。
运行前请确保已在 .env 中配置飞书凭证。
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.loaders.bitable_schema import BitableSchemaManager


def main():
    print("=" * 60)
    print("  小红书 → 飞书多维表格 — 初始化建表")
    print("=" * 60)

    try:
        manager = BitableSchemaManager()
        print(f"\n目标多维表格: {manager.app_token}\n")
        table_ids = manager.setup_all_tables()
        print(f"\n✓ 完成！共 {len(table_ids)} 张表已就绪。")
        print("\n表 ID 映射:")
        for key, tid in table_ids.items():
            print(f"  {key}: {tid}")
    except Exception as e:
        print(f"\n✗ 初始化失败: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
