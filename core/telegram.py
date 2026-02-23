"""Telegram 通道适配 — 消息模板、审批流程、勿扰时段。

功能：
- 发送文本消息和结构化通知
- 提案审批（inline keyboard: 同意/拒绝/讨论）
- 每日简报、效果报告、紧急通知
- 勿扰时段 (22:00-08:00) + 消息排队
- 频率控制（提案 ≤2/天，Architect ≤3/天）
"""

import json
import logging
from datetime import datetime, time
from pathlib import Path
from typing import Callable

logger = logging.getLogger(__name__)

# ──────────────────────────────────────
#  消息模板
# ──────────────────────────────────────

PROPOSAL_TEMPLATE = """🔧 *进化提案 \\#{proposal_id}*

*问题*: {problem}
*方案*: {solution}
*审批级别*: Level {level}
*影响范围*: {blast_radius}
*涉及文件*: {files}
*预期效果*: {expected_effect}
*验证方式*: {verification_method}"""

DAILY_BRIEFING_TEMPLATE = """📊 *每日简报 — {date}*

*任务统计*
• 总数: {total_tasks}   成功: {success}   部分: {partial}   失败: {failure}
• 成功率: {success_rate}%
• Token 消耗: {tokens_used:,}

*Observer 发现*
{observer_findings}

*Architect 状态*
{architect_status}"""

EFFECT_REPORT_TEMPLATE = """📈 *效果报告 — 提案 \\#{proposal_id}*

*方案*: {solution}
*验证期*: {verification_period}
*结果*: {result}
*指标变化*: {metrics_change}
*结论*: {conclusion}"""

EMERGENCY_TEMPLATE = """⚠️ *紧急通知*

*问题*: {problem}
*严重程度*: {severity}
*已采取行动*: {action_taken}
*建议*: {suggestion}"""

HUMAN_TASK_TEMPLATE = """📋 *需要你的帮助*

*任务*: {task}
*原因*: {reason}
*期望结果*: {expected_result}
*截止时间*: {deadline}
*如果不方便*: {fallback}"""


def format_proposal(proposal: dict) -> str:
    """格式化提案通知消息。"""
    files = "\n".join(f"  • `{f}`" for f in proposal.get("files_affected", []))
    return PROPOSAL_TEMPLATE.format(
        proposal_id=proposal.get("proposal_id", "???"),
        problem=proposal.get("problem", "未知"),
        solution=proposal.get("solution", "未知"),
        level=proposal.get("level", 0),
        blast_radius=proposal.get("blast_radius", "未知"),
        files=files or "无",
        expected_effect=proposal.get("expected_effect", ""),
        verification_method=proposal.get("verification_method", ""),
    )


def format_daily_briefing(summary: dict) -> str:
    """格式化每日简报。"""
    findings = summary.get("observer_findings", "无新发现")
    if isinstance(findings, list):
        findings = "\n".join(f"• {f}" for f in findings)

    arch_status = summary.get("architect_status", "无活动")
    if isinstance(arch_status, list):
        arch_status = "\n".join(f"• {s}" for s in arch_status)

    return DAILY_BRIEFING_TEMPLATE.format(
        date=summary.get("date", datetime.now().strftime("%Y-%m-%d")),
        total_tasks=summary.get("total_tasks", 0),
        success=summary.get("success", 0),
        partial=summary.get("partial", 0),
        failure=summary.get("failure", 0),
        success_rate=summary.get("success_rate", 0),
        tokens_used=summary.get("tokens_used", 0),
        observer_findings=findings,
        architect_status=arch_status,
    )


def format_emergency(alert: dict) -> str:
    """格式化紧急通知。"""
    return EMERGENCY_TEMPLATE.format(
        problem=alert.get("problem", "未知"),
        severity=alert.get("severity", "HIGH"),
        action_taken=alert.get("action_taken", "暂无"),
        suggestion=alert.get("suggestion", "请检查系统状态"),
    )


def format_effect_report(report: dict) -> str:
    """格式化效果报告。"""
    return EFFECT_REPORT_TEMPLATE.format(
        proposal_id=report.get("proposal_id", "???"),
        solution=report.get("solution", ""),
        verification_period=report.get("verification_period", ""),
        result=report.get("result", ""),
        metrics_change=report.get("metrics_change", ""),
        conclusion=report.get("conclusion", ""),
    )


# ──────────────────────────────────────
#  审批回调数据
# ──────────────────────────────────────

APPROVAL_ACTIONS = {
    "approve": "✅ 同意",
    "reject": "❌ 拒绝",
    "discuss": "💬 讨论",
}


def make_approval_keyboard(proposal_id: str) -> list[list[dict]]:
    """生成审批 inline keyboard 数据。

    Returns:
        适用于 telegram.InlineKeyboardMarkup 的按钮行数据。
        每个 dict: {"text": "✅ 同意", "callback_data": "approve:prop_024"}
    """
    buttons = []
    for action, label in APPROVAL_ACTIONS.items():
        buttons.append({
            "text": label,
            "callback_data": f"{action}:{proposal_id}",
        })
    return [buttons]  # 一行三个按钮


def parse_callback_data(data: str) -> dict | None:
    """解析审批回调数据。

    Args:
        data: "approve:prop_024" 格式

    Returns:
        {"action": "approve", "proposal_id": "prop_024"} 或 None
    """
    if ":" not in data:
        return None
    parts = data.split(":", 1)
    if parts[0] not in APPROVAL_ACTIONS:
        return None
    return {"action": parts[0], "proposal_id": parts[1]}


# ──────────────────────────────────────
#  Telegram 通道
# ──────────────────────────────────────

class TelegramChannel:
    """Telegram 通道适配器。

    封装消息发送、审批交互、勿扰时段、频率控制。
    """

    def __init__(
        self,
        token: str,
        chat_id: str | int,
        dnd_start: time = time(22, 0),
        dnd_end: time = time(8, 0),
        max_proposals_per_day: int = 2,
        max_architect_messages_per_day: int = 3,
        queue_dir: str | Path | None = None,
    ):
        """
        Args:
            token: Telegram Bot token
            chat_id: 目标聊天 ID（与用户的对话）
            dnd_start: 勿扰开始时间（默认 22:00）
            dnd_end: 勿扰结束时间（默认 08:00）
            max_proposals_per_day: 每日最大提案通知数
            max_architect_messages_per_day: 每日最大 Architect 消息数
            queue_dir: 消息队列持久化目录（None 则内存队列）
        """
        self.token = token
        self.chat_id = chat_id
        self.dnd_start = dnd_start
        self.dnd_end = dnd_end
        self.max_proposals_per_day = max_proposals_per_day
        self.max_architect_messages_per_day = max_architect_messages_per_day

        self._queue_dir = Path(queue_dir) if queue_dir else None
        if self._queue_dir:
            self._queue_dir.mkdir(parents=True, exist_ok=True)

        # 内存队列（勿扰时段暂存）
        self._message_queue: list[dict] = []

        # 每日计数器
        self._daily_counts: dict[str, int] = {}
        self._count_date: str = ""

        # 审批回调处理器
        self._approval_handlers: dict[str, Callable] = {}

        # Bot 实例（延迟初始化）
        self._bot = None

    def _get_bot(self):
        """延迟初始化 Bot。"""
        if self._bot is None:
            from telegram import Bot
            self._bot = Bot(token=self.token)
        return self._bot

    def _reset_daily_counts(self):
        """如果日期变了，重置计数。"""
        today = datetime.now().strftime("%Y-%m-%d")
        if today != self._count_date:
            self._daily_counts = {"proposal": 0, "architect": 0}
            self._count_date = today

    def is_dnd(self, now: datetime | None = None) -> bool:
        """检查当前是否在勿扰时段。"""
        now = now or datetime.now()
        current = now.time()

        if self.dnd_start > self.dnd_end:
            # 跨午夜（如 22:00 - 08:00）
            return current >= self.dnd_start or current < self.dnd_end
        else:
            return self.dnd_start <= current < self.dnd_end

    def can_send_proposal(self) -> bool:
        """检查今天是否还能发提案通知。"""
        self._reset_daily_counts()
        return self._daily_counts.get("proposal", 0) < self.max_proposals_per_day

    def can_send_architect_message(self) -> bool:
        """检查今天是否还能发 Architect 消息。"""
        self._reset_daily_counts()
        return self._daily_counts.get("architect", 0) < self.max_architect_messages_per_day

    async def send_message(
        self,
        text: str,
        parse_mode: str = "Markdown",
        reply_markup: dict | None = None,
        force: bool = False,
        message_type: str = "general",
    ) -> dict:
        """发送消息（遵守勿扰时段，除非 force=True 或紧急）。

        Args:
            text: 消息内容
            parse_mode: "Markdown" 或 "HTML"
            reply_markup: inline keyboard 等
            force: 是否无视勿扰时段
            message_type: "general" | "proposal" | "architect" | "emergency"

        Returns:
            {"sent": True/False, "queued": True/False, "message_id": id/None}
        """
        # 紧急消息无视勿扰
        if message_type == "emergency":
            force = True

        # 勿扰检查
        if not force and self.is_dnd():
            self._enqueue(text, parse_mode, reply_markup, message_type)
            return {"sent": False, "queued": True, "message_id": None}

        # 频率检查
        self._reset_daily_counts()
        if message_type == "proposal" and not self.can_send_proposal():
            self._enqueue(text, parse_mode, reply_markup, message_type)
            logger.warning("Daily proposal limit reached, queued")
            return {"sent": False, "queued": True, "message_id": None}
        if message_type == "architect" and not self.can_send_architect_message():
            self._enqueue(text, parse_mode, reply_markup, message_type)
            logger.warning("Daily architect message limit reached, queued")
            return {"sent": False, "queued": True, "message_id": None}

        # 发送
        try:
            bot = self._get_bot()
            kwargs = {
                "chat_id": self.chat_id,
                "text": text,
                "parse_mode": parse_mode,
            }
            if reply_markup:
                from telegram import InlineKeyboardButton, InlineKeyboardMarkup
                buttons = []
                for row in reply_markup.get("inline_keyboard", []):
                    btn_row = []
                    for btn in row:
                        btn_row.append(InlineKeyboardButton(
                            text=btn["text"],
                            callback_data=btn.get("callback_data"),
                        ))
                    buttons.append(btn_row)
                kwargs["reply_markup"] = InlineKeyboardMarkup(buttons)

            msg = await bot.send_message(**kwargs)

            # 更新计数
            if message_type in ("proposal", "architect"):
                self._daily_counts[message_type] = self._daily_counts.get(message_type, 0) + 1

            logger.info(f"Telegram message sent (type={message_type}, id={msg.message_id})")
            return {"sent": True, "queued": False, "message_id": msg.message_id}

        except Exception as e:
            logger.error(f"Failed to send Telegram message: {e}")
            self._enqueue(text, parse_mode, reply_markup, message_type)
            return {"sent": False, "queued": True, "message_id": None, "error": str(e)}

    async def send_proposal(self, proposal: dict) -> dict:
        """发送提案通知（带审批按钮）。"""
        text = format_proposal(proposal)
        proposal_id = proposal.get("proposal_id", "unknown")
        keyboard = {"inline_keyboard": make_approval_keyboard(proposal_id)}

        return await self.send_message(
            text=text,
            reply_markup=keyboard,
            message_type="proposal",
        )

    async def send_daily_briefing(self, summary: dict) -> dict:
        """发送每日简报。"""
        text = format_daily_briefing(summary)
        return await self.send_message(text=text, message_type="architect")

    async def send_emergency(self, alert: dict) -> dict:
        """发送紧急通知（无视勿扰）。"""
        text = format_emergency(alert)
        return await self.send_message(text=text, message_type="emergency", force=True)

    async def send_effect_report(self, report: dict) -> dict:
        """发送效果报告。"""
        text = format_effect_report(report)
        return await self.send_message(text=text, message_type="architect")

    def register_approval_handler(self, handler: Callable):
        """注册审批回调处理器。

        handler(action: str, proposal_id: str) -> None
        """
        self._approval_handlers["default"] = handler

    async def handle_callback(self, callback_data: str) -> dict | None:
        """处理审批回调。

        Args:
            callback_data: 来自 inline keyboard 的 callback_data

        Returns:
            {"action": "approve", "proposal_id": "prop_024"} 或 None
        """
        parsed = parse_callback_data(callback_data)
        if not parsed:
            return None

        handler = self._approval_handlers.get("default")
        if handler:
            try:
                handler(parsed["action"], parsed["proposal_id"])
            except Exception as e:
                logger.error(f"Approval handler error: {e}")

        return parsed

    async def flush_queue(self) -> list[dict]:
        """发送队列中的消息（勿扰时段结束后调用）。

        Returns:
            发送结果列表
        """
        if self.is_dnd():
            return []

        results = []
        remaining = []

        for item in self._message_queue:
            result = await self.send_message(
                text=item["text"],
                parse_mode=item.get("parse_mode", "Markdown"),
                reply_markup=item.get("reply_markup"),
                force=True,  # 已确认不在勿扰
                message_type=item.get("message_type", "general"),
            )
            if result.get("sent"):
                results.append(result)
            else:
                remaining.append(item)

        self._message_queue = remaining
        if results:
            logger.info(f"Flushed {len(results)} queued messages")
        return results

    def get_queue_size(self) -> int:
        """获取队列中的消息数量。"""
        return len(self._message_queue)

    def _enqueue(self, text: str, parse_mode: str, reply_markup: dict | None, message_type: str):
        """将消息加入队列。"""
        item = {
            "text": text,
            "parse_mode": parse_mode,
            "reply_markup": reply_markup,
            "message_type": message_type,
            "queued_at": datetime.now().isoformat(),
        }
        self._message_queue.append(item)

        # 持久化（如果配置了队列目录）
        if self._queue_dir:
            queue_file = self._queue_dir / "pending.jsonl"
            with open(queue_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(item, ensure_ascii=False) + "\n")

        logger.info(f"Message queued (type={message_type}, queue_size={len(self._message_queue)})")
