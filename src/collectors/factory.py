"""采集器工厂：根据配置选择并创建合适的采集器实例。

策略决策:
    "browser"  -> XHSBrowserCollector (CDP 模式)
    "api"      -> XHSApiCollector (官方 API)
    "hybrid"   -> HybridCollector (API → 浏览器 → CSV 降级)
    "csv"      -> CSVImportCollector (手动 CSV 导入)
"""

import logging
from typing import Optional

from src.collectors.base import BaseCollector
from src.collectors.csv_import import CSVImportCollector
from src.core.config import CollectionConfig, load_config
from src.core.exceptions import CollectorError

logger = logging.getLogger(__name__)


def create_collector(strategy: Optional[str] = None) -> BaseCollector:
    """根据配置创建采集器实例。

    Args:
        strategy: 采集策略，None 则从配置文件读取

    Returns:
        BaseCollector 实例

    Raises:
        CollectorError: 不支持的策略
    """
    config = load_config()

    if strategy is None:
        strategy = config.collection.strategy

    strategy = strategy.lower()

    if strategy == "browser":
        from src.collectors.xhs_browser import XHSBrowserCollector

        browser_cfg = config.collection.browser
        return XHSBrowserCollector(
            cdp_endpoint=browser_cfg.cdp_endpoint,
            headless=browser_cfg.headless,
            min_delay=browser_cfg.min_delay_seconds,
            max_delay=browser_cfg.max_delay_seconds,
            timeout=browser_cfg.request_timeout_seconds,
            max_notes=browser_cfg.max_notes_per_account,
            storage_state_path=browser_cfg.storage_state_path,
        )

    elif strategy == "api":
        from src.collectors.xhs_api import XHSApiCollector

        api_cfg = config.xhs_api
        if not api_cfg.app_key or not api_cfg.app_secret:
            raise CollectorError(
                "选择 API 采集模式但未配置小红书 API 凭证。"
                "请在 .env 中设置 XHS_APP_KEY 和 XHS_APP_SECRET。"
            )
        return XHSApiCollector(
            app_key=api_cfg.app_key,
            app_secret=api_cfg.app_secret,
            base_url=api_cfg.base_url,
        )

    elif strategy == "csv":
        return CSVImportCollector()

    elif strategy == "hybrid":
        # 尝试 API 优先，失败则降级到浏览器，再失败则 CSV
        logger.info("混合采集模式: 将依次尝试 API → Browser → CSV")
        from src.collectors.xhs_api import XHSApiCollector
        from src.collectors.xhs_browser import XHSBrowserCollector

        api_cfg = config.xhs_api
        browser_cfg = config.collection.browser

        api_collector = None
        if api_cfg.app_key and api_cfg.app_secret:
            api_collector = XHSApiCollector(
                app_key=api_cfg.app_key,
                app_secret=api_cfg.app_secret,
                base_url=api_cfg.base_url,
            )

        browser_collector = XHSBrowserCollector(
            cdp_endpoint=browser_cfg.cdp_endpoint,
            headless=browser_cfg.headless,
            min_delay=browser_cfg.min_delay_seconds,
            max_delay=browser_cfg.max_delay_seconds,
            timeout=browser_cfg.request_timeout_seconds,
            max_notes=browser_cfg.max_notes_per_account,
            storage_state_path=browser_cfg.storage_state_path,
        )

        csv_collector = CSVImportCollector()

        from src.collectors.xhs_browser import HybridCollector
        return HybridCollector(
            api_collector=api_collector,
            browser_collector=browser_collector,
            csv_collector=csv_collector,
        )

    else:
        raise CollectorError(
            f"不支持的采集策略: '{strategy}'。"
            f"可选: browser, api, hybrid, csv"
        )
