"""飞书 Bot 通知推送。

通过飞书 Webhook 发送:
- 成功: 交互式卡片日报（关键指标变化 + TOP3 笔记 + 竞品排名变化）
- 失败: 错误详情通知
"""

import json
import logging
from datetime import date
from typing import Any, Optional

import httpx

from src.core.config import load_config
from src.core.exceptions import NotifierError

logger = logging.getLogger(__name__)


class FeishuBotNotifier:
    """飞书 Bot 通知器。

    用法:
        notifier = FeishuBotNotifier()
        notifier.send_daily_summary(summary_data)
        notifier.send_error_alert("采集失败", "Connection timeout")
    """

    def __init__(self, webhook_url: Optional[str] = None):
        if webhook_url:
            self.webhook_url = webhook_url
        else:
            config = load_config()
            self.webhook_url = config.feishu.bot_webhook_url

        if not self.webhook_url:
            logger.warning(
                "飞书 Bot Webhook 未配置，通知功能禁用。"
                "请在 .env 中设置 FEISHU_BOT_WEBHOOK_URL。"
            )

        self._client = httpx.Client(timeout=15.0)

    @property
    def enabled(self) -> bool:
        return bool(self.webhook_url)

    def _send(self, payload: dict) -> bool:
        """发送消息到飞书 Webhook。"""
        if not self.enabled:
            logger.debug("Bot 未配置，跳过通知")
            return False

        try:
            resp = self._client.post(
                self.webhook_url,
                json=payload,
                headers={"Content-Type": "application/json"},
            )
            data = resp.json()
            if data.get("code") == 0:
                logger.info("飞书 Bot 通知发送成功")
                return True
            else:
                logger.error(
                    "飞书 Bot 通知发送失败: code=%s, msg=%s",
                    data.get("code"), data.get("msg"),
                )
                return False
        except Exception as e:
            logger.error("飞书 Bot 通知发送异常: %s", e)
            return False

    def send_text(self, title: str, content: str) -> bool:
        """发送纯文本消息。"""
        payload = {
            "msg_type": "interactive",
            "card": {
                "header": {
                    "title": {"tag": "plain_text", "content": title},
                    "template": "red" if "失败" in title or "错误" in title else "blue",
                },
                "elements": [
                    {
                        "tag": "markdown",
                        "content": content,
                    }
                ],
            },
        }
        return self._send(payload)

    def send_daily_summary(
        self,
        run_date: Optional[date] = None,
        total_accounts: int = 0,
        success_count: int = 0,
        failed_count: int = 0,
        highlights: Optional[list[dict]] = None,
        errors: Optional[list[str]] = None,
    ) -> bool:
        """发送每日数据同步日报卡片。

        Args:
            run_date: 运行日期
            total_accounts: 总处理账号数
            success_count: 成功数
            failed_count: 失败数
            highlights: 高亮数据 [{"label": "涨粉最多", "value": "账号A +1200"}]
            errors: 错误列表
        """
        if not self.enabled:
            return False

        rd = run_date or date.today()
        status_emoji = "✅" if failed_count == 0 else "⚠️"

        elements: list[dict] = [
            {
                "tag": "markdown",
                "content": f"**执行日期**: {rd.strftime('%Y年%m月%d日')}\n"
                           f"**处理账号**: {total_accounts} 个\n"
                           f"**成功**: {success_count} | **失败**: {failed_count}",
            },
            {"tag": "hr"},
        ]

        if highlights:
            elements.append({
                "tag": "markdown",
                "content": "**📊 关键指标变化**",
            })
            for h in highlights[:5]:
                elements.append({
                    "tag": "markdown",
                    "content": f"- {h.get('label', '')}: {h.get('value', '')}",
                })
            elements.append({"tag": "hr"})

        if errors:
            elements.append({
                "tag": "markdown",
                "content": "**⚠️ 异常提醒**",
            })
            for err in errors[:3]:
                elements.append({
                    "tag": "markdown",
                    "content": f"- {err}",
                })

        elements.append({
            "tag": "note",
            "elements": [
                {
                    "tag": "plain_text",
                    "content": f"小红书数据自动同步 | {rd.strftime('%Y-%m-%d %H:%M')}",
                }
            ],
        })

        payload = {
            "msg_type": "interactive",
            "card": {
                "header": {
                    "title": {
                        "tag": "plain_text",
                        "content": f"{status_emoji} 小红书数据日报 - {rd.strftime('%m/%d')}",
                    },
                    "template": "green" if failed_count == 0 else "orange",
                },
                "elements": elements,
            },
        }

        return self._send(payload)

    def send_error_alert(
        self,
        step: str,
        error_message: str,
        account_id: Optional[str] = None,
    ) -> bool:
        """发送错误告警。"""
        if not self.enabled:
            return False

        account_info = f"\n**受影响账号**: {account_id}" if account_id else ""

        content = (
            f"**失败步骤**: {step}{account_info}\n"
            f"**错误信息**: {error_message[:300]}\n"
            f"\n请检查系统状态并及时处理。"
        )

        return self.send_text("⚠️ 数据同步告警", content)
