"""PyInstaller 入口 — 启动 API 服务器。

用法:
    python run_server.py
    xhs-feishu-server.exe  (PyInstaller 打包后)

特性:
    - uvicorn 服务器在 localhost:9527
    - 无控制台窗口（noconsole 模式）
"""

import uvicorn

# ── PyInstaller 隐藏导入 ──
import src.api.server  # noqa: F401

from src.api.server import app


def main():
    """启动 API 服务器。"""
    uvicorn.run(
        app,
        host="127.0.0.1",
        port=9527,
        log_level="info",
    )


if __name__ == "__main__":
    main()
