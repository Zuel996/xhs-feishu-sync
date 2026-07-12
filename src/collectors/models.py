"""采集器数据模型 — 标准化的内部数据结构。

所有采集器（浏览器/API/CSV）输出统一使用这些模型，
方便后续转换层和存储层使用。
"""

from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel, Field, field_validator


class AccountProfile(BaseModel):
    """小红书账号概览数据（一次性采集）。"""

    account_id: str = Field(description="内部账号标识")
    xhs_user_id: str = Field(description="小红书用户ID")
    username: str = Field(description="小红书用户名")
    display_name: str = Field(default="", description="显示名称")
    follower_count: int = Field(default=0, ge=0, description="粉丝数")
    following_count: int = Field(default=0, ge=0, description="关注数")
    total_likes: int = Field(default=0, ge=0, description="获赞数")
    total_collections: int = Field(default=0, ge=0, description="收藏数")
    collected_at: datetime = Field(default_factory=datetime.now)
    competitor: bool = Field(default=False, description="是否为竞品账号")

    @property
    def total_likes_and_collections(self) -> int:
        """获赞与收藏总数。"""
        return self.total_likes + self.total_collections


class NoteMetrics(BaseModel):
    """单篇笔记的互动数据。"""

    note_id: str = Field(description="小红书笔记ID")
    account_id: str = Field(description="所属账号内部标识")
    title: str = Field(default="", description="笔记标题")
    note_type: str = Field(default="image", description="笔记类型: image | video")
    publish_date: Optional[date] = Field(default=None, description="发布日期")
    url: str = Field(default="", description="笔记链接")
    views: int = Field(default=0, ge=0, description="浏览量")
    likes: int = Field(default=0, ge=0, description="点赞数")
    favorites: int = Field(default=0, ge=0, description="收藏数")
    comments: int = Field(default=0, ge=0, description="评论数")
    shares: int = Field(default=0, ge=0, description="分享数")
    collected_at: datetime = Field(default_factory=datetime.now)

    @property
    def total_interactions(self) -> int:
        """总互动量 = 点赞+收藏+评论+分享。"""
        return self.likes + self.favorites + self.comments + self.shares

    @property
    def engagement_rate(self) -> float:
        """互动率 = 总互动 / 浏览量。"""
        if self.views == 0:
            return 0.0
        return round(self.total_interactions / self.views * 100, 2)


class CollectResult(BaseModel):
    """一次采集的结果汇总。"""

    account_id: str
    profile: Optional[AccountProfile] = None
    notes: list[NoteMetrics] = Field(default_factory=list)
    new_notes_count: int = Field(default=0, description="本次新发现的笔记数")
    errors: list[str] = Field(default_factory=list)
    success: bool = Field(default=True)

    @property
    def total_views_today(self) -> int:
        return sum(n.views for n in self.notes)

    @property
    def total_interactions_today(self) -> int:
        return sum(n.total_interactions for n in self.notes)
