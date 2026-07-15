"""PyInstaller 入口 — 启动 API 服务器（系统托盘模式）。

用法:
    python run_server.py
    xhs-feishu-server.exe  (PyInstaller 打包后)

特性:
    - uvicorn 服务器在后台线程运行（localhost:9527）
    - 系统托盘图标，右键可查看状态/退出
    - 无控制台窗口（noconsole 模式）
"""

import logging
import threading
import webbrowser
from datetime import date

import uvicorn

# ── PyInstaller 隐藏导入 ──
import src.api.server  # noqa: F401

from src.api.server import app, _last_status

logger = logging.getLogger(__name__)


def create_icon_image():
    """用 Pillow 创建一个红色圆角方形图标。"""
    from PIL import Image, ImageDraw

    size = 64
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # 红色圆角矩形
    draw.rounded_rectangle([2, 2, size - 2, size - 2], radius=12, fill="#ff2e4c")

    # 白色文字
    try:
        from PIL import ImageFont
        font = ImageFont.truetype("arial.ttf", 36)
    except Exception:
        font = ImageFont.load_default()

    draw.text((size // 2, size // 2), "S", fill="white", anchor="mm", font=font)
    return img


def start_tray():
    """启动系统托盘图标。

    托盘在 Windows 消息泵线程中运行（主线程），
    uvicorn 服务器在 daemon 线程中运行。
    用户通过托盘菜单退出时，服务器也会停止。
    """
    import pystray

    server_thread = None
    server_started = threading.Event()

    def run_server():
        """在 daemon 线程中启动 uvicorn。"""
        config = uvicorn.Config(
            app,
            host="127.0.0.1",
            port=9527,
            log_level="warning",
        )
        srv = uvicorn.Server(config)
        server_started.set()
        srv.run()

    # 启动服务器线程
    server_thread = threading.Thread(target=run_server, daemon=True)
    server_thread.start()
    server_started.wait(timeout=5)

    # 构建托盘菜单
    def on_status(icon, item):
        """打开浏览器状态页。"""
        webbrowser.open("http://localhost:9527/health")

    def on_exit(icon, item):
        """退出应用。"""
        icon.stop()

    menu = pystray.Menu(
        pystray.MenuItem(
            "📊 查看状态",
            on_status,
            default=True,
        ),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("❌ 退出", on_exit),
    )

    icon = pystray.Icon(
        "xhs-feishu-sync",
        create_icon_image(),
        "xhs-feishu-sync",
        menu,
    )

    icon.run()


def main():
    """启动系统托盘 + 后台服务器。"""
    start_tray()


if __name__ == "__main__":
    main()
