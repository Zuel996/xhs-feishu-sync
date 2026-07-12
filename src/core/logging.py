"""日志配置模块。

支持 JSON 结构化日志（生产）和控制台彩色日志（开发）两种输出格式。
"""

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from src.core.config import LoggingConfig, PROJECT_ROOT


def setup_logging(config: LoggingConfig) -> None:
    """根据配置初始化全局日志系统。

    JSON 格式写入文件，控制台格式输出到 stdout。
    """
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, config.level.upper(), logging.INFO))

    # 清除已有 handler（避免重复）
    root_logger.handlers.clear()

    # 控制台 handler — 可读格式
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_fmt = logging.Formatter(
        fmt="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    console_handler.setFormatter(console_fmt)
    root_logger.addHandler(console_handler)

    # 文件 handler — 带轮转
    log_path = PROJECT_ROOT / config.file
    log_path.parent.mkdir(parents=True, exist_ok=True)

    file_handler = RotatingFileHandler(
        str(log_path),
        maxBytes=config.max_bytes,
        backupCount=config.backup_count,
        encoding="utf-8",
    )
    file_handler.setLevel(logging.DEBUG)

    if config.format == "json":
        try:
            import structlog
            # structlog 配置留作后续增强
            file_fmt = logging.Formatter(
                fmt='{"time":"%(asctime)s","level":"%(levelname)s",'
                '"logger":"%(name)s","message":"%(message)s"}',
                datefmt="%Y-%m-%dT%H:%M:%S",
            )
        except ImportError:
            file_fmt = logging.Formatter(
                fmt="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            )
    else:
        file_fmt = logging.Formatter(
            fmt="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )

    file_handler.setFormatter(file_fmt)
    root_logger.addHandler(file_handler)

    # 降低第三方库日志噪音
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("lark_oapi").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)

    root_logger.info("日志系统已初始化: level=%s, file=%s", config.level, log_path)


def get_logger(name: str) -> logging.Logger:
    """获取模块级 logger。"""
    return logging.getLogger(name)
