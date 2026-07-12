"""采集器抽象基类。

所有数据采集实现（浏览器/API/CSV）继承此基类，
确保接口一致，方便通过工厂模式切换。
"""

import logging
from abc import ABC, abstractmethod
from datetime import date
from typing import Optional

from src.collectors.models import AccountProfile, CollectResult, NoteMetrics
from src.core.config import AccountInfo

logger = logging.getLogger(__name__)


class BaseCollector(ABC):
    """数据采集器抽象基类。

    子类需实现:
        - collect_account_profile(): 采集账号概览数据
        - collect_notes_data(): 采集笔记互动数据
        - validate_connection(): 验证数据源连接
    """

    def __init__(self):
        self.name = self.__class__.__name__

    @abstractmethod
    async def collect_account_profile(
        self, account: AccountInfo
    ) -> AccountProfile:
        """采集账号概览数据（粉丝数、关注数、获赞收藏等）。

        Args:
            account: 账号配置信息

        Returns:
            AccountProfile: 标准化账号数据
        """
        ...

    @abstractmethod
    async def collect_notes_data(
        self, account: AccountInfo, target_date: Optional[date] = None
    ) -> list[NoteMetrics]:
        """采集账号下笔记的互动数据。

        Args:
            account: 账号配置信息
            target_date: 目标日期，None 表示采集最近的数据

        Returns:
            NoteMetrics 列表
        """
        ...

    @abstractmethod
    async def validate_connection(self) -> bool:
        """验证数据源连接是否正常。

        Returns:
            True 如果连接正常
        """
        ...

    async def collect_all(
        self, account: AccountInfo, target_date: Optional[date] = None
    ) -> CollectResult:
        """采集一个账号的完整数据（profile + notes）。

        这是推荐的调用入口，子类可以覆写以优化采集流程。
        """
        result = CollectResult(account_id=account.account_id)

        try:
            logger.info("开始采集账号: %s", account.display_name)

            # 1. 采集账号概览
            try:
                result.profile = await self.collect_account_profile(account)
                logger.info(
                    "  ✓ 账号概览: 粉丝=%d, 关注=%d",
                    result.profile.follower_count,
                    result.profile.following_count,
                )
            except Exception as e:
                result.errors.append(f"账号概览采集失败: {e}")
                logger.error("  ✗ 账号概览采集失败: %s", e)

            # 2. 采集笔记数据
            try:
                result.notes = await self.collect_notes_data(account, target_date)
                result.new_notes_count = len(result.notes)
                logger.info("  ✓ 笔记数据: %d 篇", len(result.notes))
            except Exception as e:
                result.errors.append(f"笔记数据采集失败: {e}")
                logger.error("  ✗ 笔记数据采集失败: %s", e)

            result.success = len(result.errors) == 0

        except Exception as e:
            result.success = False
            result.errors.append(f"采集流程异常: {e}")
            logger.exception("采集账号 %s 时发生未预期错误", account.display_name)

        return result
