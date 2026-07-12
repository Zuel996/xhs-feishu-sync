#!/usr/bin/env python
"""手动单次运行 — 无需 CLI，直接执行采集→同步流程。

适用于 Windows Task Scheduler 等外部调度器触发。
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main():
    from src.core.config import load_config
    from src.core.logging import setup_logging

    config = load_config()
    setup_logging(config.logging)

    print("手动运行数据同步...")
    # TODO: Phase 4 - 调用完整 Pipeline
    print("Pipeline 将在 Phase 4 实现。当前基础框架已就绪。")
    print("✓ 完成")


if __name__ == "__main__":
    main()
