"""自定义异常层次结构。

所有项目异常继承自 XHSFeishuSyncError，便于统一捕获和处理。
"""


class XHSFeishuSyncError(Exception):
    """项目基础异常。"""


# ── 配置异常 ──


class ConfigError(XHSFeishuSyncError):
    """配置相关错误：缺少必填字段、格式错误等。"""


class MissingCredentialError(ConfigError):
    """缺少必需的环境变量或凭证。"""


# ── 采集异常 ──


class CollectorError(XHSFeishuSyncError):
    """数据采集层通用异常。"""


class BrowserConnectionError(CollectorError):
    """无法连接到 Chrome CDP 调试端口。"""


class LoginSessionExpiredError(CollectorError):
    """小红书登录态已过期，需要重新登录。"""


class CaptchaDetectedError(CollectorError):
    """检测到验证码，需要人工介入。"""


class RateLimitError(CollectorError):
    """请求频率受限，需要等待。"""


class AccountNotFoundError(CollectorError):
    """找不到指定的账号。"""


class AntiCrawlBlockedError(CollectorError):
    """被反爬机制拦截。"""


# ── API 异常 ──


class XHSApiError(CollectorError):
    """小红书开放平台 API 异常。"""


class XHSAuthError(XHSApiError):
    """小红书 API 鉴权失败。"""


# ── 转换异常 ──


class TransformerError(XHSFeishuSyncError):
    """数据转换层通用异常。"""


class DataValidationError(TransformerError):
    """数据校验失败：格式不正确、数值异常等。"""


# ── 存储异常 ──


class StorageError(XHSFeishuSyncError):
    """本地存储层通用异常。"""


class DatabaseError(StorageError):
    """SQLite 数据库操作异常。"""


# ── 加载异常 ──


class LoaderError(XHSFeishuSyncError):
    """数据加载层通用异常（飞书同步）。"""


class FeishuAuthError(LoaderError):
    """飞书 API 鉴权失败：token 无效或获取失败。"""


class FeishuApiError(LoaderError):
    """飞书 API 调用异常。"""


class FeishuRateLimitError(FeishuApiError):
    """飞书 API 频率限制（429）。"""


class BitableSchemaError(LoaderError):
    """多维表格 Schema 操作异常。"""


class SyncEngineError(LoaderError):
    """数据同步引擎异常。"""


# ── 通知异常 ──


class NotifierError(XHSFeishuSyncError):
    """通知推送异常。"""


# ── 调度异常 ──


class SchedulerError(XHSFeishuSyncError):
    """任务调度异常。"""
