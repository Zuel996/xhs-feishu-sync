#!/usr/bin/env python
"""初始化本地 SQLite 数据库。

创建所有 ORM 表，可在部署时或首次使用前运行。
"""

import sys
from pathlib import Path

# 确保项目根目录在 sys.path 中
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.storage.sqlite import Database


def main():
    print("正在初始化本地 SQLite 数据库...")
    db = Database()
    db.init()
    print(f"✓ 数据库已就绪: {db.db_path}")
    print("已创建以下表:")
    from src.storage.models import Base
    for table_name in Base.metadata.tables.keys():
        print(f"  - {table_name}")


if __name__ == "__main__":
    main()
