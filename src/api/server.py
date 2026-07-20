"""HTTP API 服务 — FastAPI 应用。

为 Chrome 插件提供 REST API：
  POST /config   — 配置飞书凭证（验证连接）
  POST /collect  — 提交采集数据，触发 Pipeline
  GET  /status   — 查看最近采集状态
  GET  /health   — 后端健康检查

启动:
  python -m src.api.server
  xhs-feishu-server
"""

import asyncio
import json
import logging
import os
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from src.core.config import FeishuConfig
from src.core.pipeline import run_pipeline_from_dict
from src.loaders.bitable_client import BitableClient

logger = logging.getLogger(__name__)

# ── 持久化配置路径 ──
def _get_config_file_path() -> Path:
    """获取飞书配置持久化文件路径。

    优先使用 exe 所在目录（PyInstaller），回退到项目根目录（开发模式）。
    """
    if getattr(sys, 'frozen', False):
        # PyInstaller 打包模式：配置保存在 exe 旁边
        exe_dir = Path(sys.executable).parent
    else:
        # 开发模式：配置保存在项目根目录
        exe_dir = Path(__file__).resolve().parents[2]
    return exe_dir / "feishu_config.json"


def _save_config_to_file(config: FeishuConfig) -> None:
    """将飞书配置持久化到本地文件。"""
    try:
        path = _get_config_file_path()
        data = {
            "app_id": config.app_id,
            "app_secret": config.app_secret,
            "bitable_app_token": config.bitable_app_token,
            "bot_webhook_url": config.bot_webhook_url,
        }
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        logger.info("飞书配置已持久化到 %s", path)
    except Exception as e:
        logger.warning("持久化飞书配置失败（不影响运行）: %s", e)


def _load_config_from_file() -> Optional[FeishuConfig]:
    """从本地文件加载飞书配置。返回 None 如果文件不存在或损坏。"""
    try:
        path = _get_config_file_path()
        if not path.exists():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        cfg = FeishuConfig(
            app_id=data.get("app_id", ""),
            app_secret=data.get("app_secret", ""),
            bitable_app_token=data.get("bitable_app_token", ""),
            bot_webhook_url=data.get("bot_webhook_url", ""),
        )
        logger.info("从 %s 加载了飞书配置", path)
        return cfg
    except Exception as e:
        logger.warning("加载飞书配置失败: %s", e)
        return None


# ── 全局状态 ──
_feishu_config: Optional[FeishuConfig] = _load_config_from_file()
_last_status: dict = {
    "last_run": None,
    "status": "idle",
    "accounts_processed": 0,
    "notes_synced": 0,
    "errors": [],
}

# ── FastAPI 应用 ──
app = FastAPI(
    title="xhs-feishu-sync",
    version="0.1.0",
    description="小红书 → 飞书多维表格 数据同步后端",
)

# CORS：允许 Chrome 插件从任何 origin 调用 localhost
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ═══════════════════════════════════════════════════
# 请求模型
# ═══════════════════════════════════════════════════

class FeishuConfigRequest(BaseModel):
    """飞书凭证配置请求。"""
    app_id: str = Field(description="飞书应用 App ID")
    app_secret: str = Field(description="飞书应用 App Secret")
    bitable_app_token: str = Field(description="飞书多维表格 App Token")
    bot_webhook_url: str = Field(default="", description="Bot Webhook（可选）")


class ProfileData(BaseModel):
    """账号 Profile 数据。"""
    account_id: str
    xhs_user_id: str
    username: str
    display_name: str = ""
    follower_count: int = Field(default=0, ge=0)
    following_count: int = Field(default=0, ge=0)
    total_likes: int = Field(default=0, ge=0)
    total_collections: int = Field(default=0, ge=0)
    competitor: bool = False


class NoteData(BaseModel):
    """单篇笔记数据。"""
    note_id: str = Field(description="小红书笔记 ID")
    account_id: str = Field(description="所属账号 ID")
    title: str = ""
    note_type: str = "image"
    publish_date: Optional[str] = Field(default=None, description="发布日期 (ISO 格式)")
    url: str = ""
    views: int = Field(default=0, ge=0)
    likes: int = Field(default=0, ge=0)
    favorites: int = Field(default=0, ge=0)
    comments: int = Field(default=0, ge=0)
    shares: int = Field(default=0, ge=0)
    impressions: int = Field(default=0, ge=0)
    ctr: float = Field(default=0.0, ge=0)
    new_followers: int = Field(default=0, ge=0)
    avg_watch_time: float = Field(default=0.0, ge=0)
    danmaku: int = Field(default=0, ge=0)
    sort_order: int = Field(default=0, ge=0)


class CollectRequest(BaseModel):
    """采集数据提交请求。"""
    account_id: str = Field(description="账号 ID")
    profile: Optional[ProfileData] = Field(default=None, description="账号 Profile 数据")
    notes: list[NoteData] = Field(default_factory=list, description="笔记列表")


# ═══════════════════════════════════════════════════
# API 端点
# ═══════════════════════════════════════════════════

@app.post("/config")
async def set_config(config: FeishuConfigRequest):
    """配置飞书凭证并验证连接。"""
    global _feishu_config

    cfg = FeishuConfig(
        app_id=config.app_id,
        app_secret=config.app_secret,
        bitable_app_token=config.bitable_app_token,
        bot_webhook_url=config.bot_webhook_url,
    )

    # 立即验证：尝试获取 tenant_access_token
    try:
        client = BitableClient(cfg)
        token = client.ensure_token()
        _feishu_config = cfg
        _save_config_to_file(cfg)  # 持久化，重启不丢失

        # 检查多维表格中已存在的表（不自动创建，仅报告状态）
        expected_tables = {
            "account_summary": "账号概览",
            "note_metrics": "笔记数据明细",
            "daily_snapshot": "每日快照",
            "competitor_comparison": "竞品对比",
            "account_manager": "账号管理",
        }
        tables_found = []
        tables_missing = []
        try:
            existing_tables = client.list_tables()
            existing_names = {t["name"] for t in existing_tables}
            for key, name in expected_tables.items():
                if name in existing_names:
                    tables_found.append(name)
                else:
                    tables_missing.append(name)
            if tables_missing:
                logger.warning(
                    "多维表格缺少以下表: %s。请在飞书后台手动创建。",
                    tables_missing,
                )
            logger.info("多维表格已有表: %s", tables_found)
        except Exception as e:
            logger.warning("检查多维表格结构失败（不影响连接验证）: %s", e)
            tables_missing = list(expected_tables.values())

        return {
            "status": "ok",
            "token_prefix": token[:10] + "...",
            "message": "飞书连接成功",
            "tables_found": tables_found,
            "tables_missing": tables_missing,
        }
    except Exception as e:
        _feishu_config = None
        raise HTTPException(
            status_code=400,
            detail=f"飞书连接失败: {e}",
        )


@app.post("/collect")
async def collect(request: CollectRequest):
    """提交采集数据，触发 Pipeline 处理。"""
    global _feishu_config, _last_status

    if _feishu_config is None:
        raise HTTPException(
            status_code=400,
            detail="请先配置飞书凭证: POST /config",
        )

    try:
        result = await run_pipeline_from_dict(
            account_id=request.account_id,
            profile_data=request.profile.model_dump() if request.profile else None,
            notes_data=[n.model_dump() for n in request.notes],
            feishu_config=_feishu_config,
        )

        sync_errors = result.get("errors", [])
        _last_status = {
            "last_run": date.today().isoformat(),
            "status": "success" if not sync_errors else "partial",
            "accounts_processed": 1,
            "notes_synced": result.get("notes_synced", 0),
            "profile_synced": result.get("profile_synced", False),
            "errors": sync_errors,
        }
        return _last_status

    except Exception as e:
        _last_status = {
            "last_run": date.today().isoformat(),
            "status": "failed",
            "errors": [str(e)],
        }
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/status")
async def get_status():
    """获取最近一次采集状态。"""
    global _last_status
    config_ok = _feishu_config is not None
    return {
        **_last_status,
        "feishu_configured": config_ok,
    }


@app.get("/health")
async def health():
    """健康检查。"""
    global _feishu_config
    return {
        "status": "ok",
        "feishu_configured": _feishu_config is not None,
    }


def start():
    """启动 API 服务器（uvicorn）。"""
    import uvicorn

    uvicorn.run(
        "src.api.server:app",
        host="127.0.0.1",
        port=9527,
        log_level="info",
    )


if __name__ == "__main__":
    start()
