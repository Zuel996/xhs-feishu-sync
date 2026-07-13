"""配置系统：加载 YAML 配置文件并通过 pydantic 验证。

支持环境变量插值（${VAR_NAME} 语法），敏感信息不写入配置文件。
"""

import os
import re
from pathlib import Path
from typing import Any, Optional

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, Field, ValidationError, field_validator

from src.core.exceptions import ConfigError, MissingCredentialError

# 加载 .env 文件
load_dotenv()

# 项目根目录
PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = PROJECT_ROOT / "config"


def _interpolate_env(value: Any) -> Any:
    """递归替换字符串中的 ${VAR_NAME} 为环境变量值。"""
    if isinstance(value, str):
        pattern = re.compile(r"\$\{(\w+)\}")
        matches = pattern.findall(value)
        if not matches:
            return value
        result = value
        for var_name in matches:
            env_value = os.getenv(var_name, "")
            result = result.replace(f"${{{var_name}}}", env_value)
        return result
    elif isinstance(value, dict):
        return {k: _interpolate_env(v) for k, v in value.items()}
    elif isinstance(value, list):
        return [_interpolate_env(item) for item in value]
    return value


def _load_yaml(filename: str) -> dict:
    """加载 YAML 文件并返回插值后的字典。"""
    path = CONFIG_DIR / filename
    if not path.exists():
        raise ConfigError(f"配置文件不存在: {path}")
    with open(path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    return _interpolate_env(raw)


# ── Pydantic Models ──


class BrowserConfig(BaseModel):
    """浏览器自动化配置。"""

    cdp_endpoint: str = "http://localhost:9222"
    headless: bool = False
    min_delay_seconds: float = Field(default=1.5, ge=0.0)
    max_delay_seconds: float = Field(default=5.0, ge=0.0)
    request_timeout_seconds: int = 30
    max_notes_per_account: int = Field(default=100, ge=1, le=500)
    storage_state_path: str = ".browser_state/storage.json"


class CollectionConfig(BaseModel):
    """数据采集配置。"""

    strategy: str = "browser"
    fallback_strategy: str = "csv"
    browser: BrowserConfig = BrowserConfig()


class ScheduleConfig(BaseModel):
    """调度配置。"""

    cron: str = "0 8 * * *"
    timezone: str = "Asia/Shanghai"
    retry_count: int = Field(default=3, ge=0, le=10)
    retry_delay_seconds: int = Field(default=300, ge=30)
    coalesce: bool = True
    misfire_grace_time: int = Field(default=3600, ge=0)


class StorageConfig(BaseModel):
    """本地存储配置。"""

    sqlite_path: str = "data/local.db"
    retention_days: int = Field(default=90, ge=7)


class LoggingConfig(BaseModel):
    """日志配置。"""

    level: str = "INFO"
    file: str = "logs/sync.log"
    max_bytes: int = 10_485_760
    backup_count: int = 30
    format: str = "json"


class FeishuConfig(BaseModel):
    """飞书配置。"""

    app_id: str
    app_secret: str
    bitable_app_token: str
    bot_webhook_url: str = ""

    @field_validator("app_id", "app_secret", "bitable_app_token")
    @classmethod
    def not_empty(cls, v: str, info: Any) -> str:
        # 允许离线模式（空值不阻止配置加载，BitableClient/SyncEngine 层面处理）
        if not v or v.startswith("${"):
            return ""
        return v


class XHSApiConfig(BaseModel):
    """小红书开放平台 API 配置（可选）。"""

    app_key: str = ""
    app_secret: str = ""
    base_url: str = "https://open-api.xiaohongshu.com"


class AppConfig(BaseModel):
    """应用总配置。"""

    collection: CollectionConfig = CollectionConfig()
    schedule: ScheduleConfig = ScheduleConfig()
    storage: StorageConfig = StorageConfig()
    logging: LoggingConfig = LoggingConfig()
    feishu: FeishuConfig
    xhs_api: XHSApiConfig = XHSApiConfig()


class AccountInfo(BaseModel):
    """单个监控账号的配置。"""

    account_id: str
    xhs_user_id: str
    xhs_username: str
    display_name: str
    competitor: bool = False


class AccountsConfig(BaseModel):
    """所有监控账号配置。"""

    own_accounts: list[AccountInfo] = Field(default_factory=list)
    competitor_accounts: list[AccountInfo] = Field(default_factory=list)

    @field_validator("own_accounts", "competitor_accounts", mode="before")
    @classmethod
    def default_to_empty(cls, v):
        """YAML 空列表可能被解析为 None，转为 []"""
        return v if v is not None else []

    @property
    def all_accounts(self) -> list[AccountInfo]:
        return self.own_accounts + self.competitor_accounts


# ── 单例加载 ──

_config: Optional[AppConfig] = None
_accounts: Optional[AccountsConfig] = None


def load_config() -> AppConfig:
    """加载并缓存应用配置。"""
    global _config
    if _config is None:
        try:
            data = _load_yaml("settings.yaml")
            _config = AppConfig(**data)
        except ValidationError as e:
            raise ConfigError(f"配置验证失败:\n{e}") from e
    return _config


def load_accounts() -> AccountsConfig:
    """加载并缓存账号配置。"""
    global _accounts
    if _accounts is None:
        try:
            data = _load_yaml("accounts.yaml")
            _accounts = AccountsConfig(**data)
        except ValidationError as e:
            raise ConfigError(f"账号配置验证失败:\n{e}") from e
    return _accounts


def reload_config() -> tuple[AppConfig, AccountsConfig]:
    """重新加载所有配置（用于运行时刷新）。"""
    global _config, _accounts
    _config = None
    _accounts = None
    return load_config(), load_accounts()
