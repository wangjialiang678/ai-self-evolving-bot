"""Telegram 通道适配测试。"""

from datetime import datetime, time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from core.telegram import (
    TelegramChannel,
    format_proposal,
    format_daily_briefing,
    format_emergency,
    format_effect_report,
    make_approval_keyboard,
    parse_callback_data,
)


# ──────────────────────────────────────
#  消息模板测试
# ──────────────────────────────────────

class TestFormatProposal:
    def test_basic(self):
        proposal = {
            "proposal_id": "prop_024",
            "problem": "分析类任务过长",
            "solution": "新增长度控制规则",
            "level": 1,
            "blast_radius": "small",
            "files_affected": ["workspace/rules/experience/task_strategies.md"],
            "expected_effect": "分析类任务纠正率下降",
            "verification_method": "下 5 次分析类任务的首次成功率",
        }
        text = format_proposal(proposal)
        assert "prop_024" in text
        assert "分析类任务过长" in text
        assert "Level 1" in text
        assert "task_strategies.md" in text

    def test_empty_files(self):
        text = format_proposal({"proposal_id": "p1"})
        assert "p1" in text
        assert "无" in text


class TestFormatDailyBriefing:
    def test_basic(self):
        summary = {
            "date": "2026-02-23",
            "total_tasks": 12,
            "success": 10,
            "partial": 1,
            "failure": 1,
            "success_rate": 83,
            "tokens_used": 45000,
            "observer_findings": ["发现分析任务偏长模式", "用户偏好简短回复"],
            "architect_status": ["提案 #23 验证中"],
        }
        text = format_daily_briefing(summary)
        assert "2026-02-23" in text
        assert "12" in text
        assert "83%" in text
        assert "45,000" in text
        assert "分析任务偏长" in text

    def test_string_findings(self):
        summary = {
            "observer_findings": "无新发现",
            "architect_status": "无活动",
        }
        text = format_daily_briefing(summary)
        assert "无新发现" in text


class TestFormatEmergency:
    def test_basic(self):
        alert = {
            "problem": "连续 3 次 critical 错误",
            "severity": "CRITICAL",
            "action_taken": "已暂停 Architect",
            "suggestion": "检查最近的规则修改",
        }
        text = format_emergency(alert)
        assert "紧急通知" in text
        assert "CRITICAL" in text
        assert "暂停 Architect" in text


class TestFormatEffectReport:
    def test_basic(self):
        report = {
            "proposal_id": "prop_024",
            "solution": "新增长度控制",
            "verification_period": "5 天",
            "result": "成功率提升 15%",
            "metrics_change": "纠正率 30% → 15%",
            "conclusion": "方案有效，保留修改",
        }
        text = format_effect_report(report)
        assert "prop_024" in text
        assert "成功率提升" in text


# ──────────────────────────────────────
#  审批数据测试
# ──────────────────────────────────────

class TestApprovalKeyboard:
    def test_make_keyboard(self):
        kb = make_approval_keyboard("prop_024")
        assert len(kb) == 1  # 一行
        assert len(kb[0]) == 3  # 三个按钮
        assert kb[0][0]["text"] == "✅ 同意"
        assert kb[0][0]["callback_data"] == "approve:prop_024"
        assert kb[0][1]["callback_data"] == "reject:prop_024"
        assert kb[0][2]["callback_data"] == "discuss:prop_024"


class TestParseCallbackData:
    def test_approve(self):
        result = parse_callback_data("approve:prop_024")
        assert result == {"action": "approve", "proposal_id": "prop_024"}

    def test_reject(self):
        result = parse_callback_data("reject:prop_001")
        assert result == {"action": "reject", "proposal_id": "prop_001"}

    def test_discuss(self):
        result = parse_callback_data("discuss:prop_999")
        assert result == {"action": "discuss", "proposal_id": "prop_999"}

    def test_invalid_no_colon(self):
        assert parse_callback_data("invalid") is None

    def test_invalid_action(self):
        assert parse_callback_data("unknown:prop_001") is None


# ──────────────────────────────────────
#  TelegramChannel 测试
# ──────────────────────────────────────

@pytest.fixture
def channel(tmp_path):
    """创建测试用 channel（不初始化真实 Bot）。"""
    return TelegramChannel(
        token="test:token",
        chat_id="12345",
        queue_dir=tmp_path / "queue",
    )


class TestDND:
    def test_dnd_during_night(self, channel):
        """22:00-08:00 是勿扰时段。"""
        night = datetime(2026, 2, 23, 23, 30)
        assert channel.is_dnd(night) is True

    def test_dnd_early_morning(self, channel):
        """凌晨 3 点在勿扰时段。"""
        early = datetime(2026, 2, 23, 3, 0)
        assert channel.is_dnd(early) is True

    def test_not_dnd_daytime(self, channel):
        """白天 14:00 不在勿扰时段。"""
        day = datetime(2026, 2, 23, 14, 0)
        assert channel.is_dnd(day) is False

    def test_dnd_boundary_start(self, channel):
        """22:00 恰好进入勿扰。"""
        boundary = datetime(2026, 2, 23, 22, 0)
        assert channel.is_dnd(boundary) is True

    def test_dnd_boundary_end(self, channel):
        """08:00 恰好结束勿扰。"""
        boundary = datetime(2026, 2, 23, 8, 0)
        assert channel.is_dnd(boundary) is False

    def test_custom_dnd(self):
        """自定义勿扰时段。"""
        ch = TelegramChannel(
            token="t", chat_id="1",
            dnd_start=time(0, 0), dnd_end=time(6, 0),
        )
        assert ch.is_dnd(datetime(2026, 1, 1, 3, 0)) is True
        assert ch.is_dnd(datetime(2026, 1, 1, 10, 0)) is False


class TestRateLimiting:
    def test_proposal_limit(self, channel):
        """每天最多 2 个提案。"""
        assert channel.can_send_proposal() is True
        channel._daily_counts["proposal"] = 2
        channel._count_date = datetime.now().strftime("%Y-%m-%d")
        assert channel.can_send_proposal() is False

    def test_architect_limit(self, channel):
        """每天最多 3 条 Architect 消息。"""
        assert channel.can_send_architect_message() is True
        channel._daily_counts["architect"] = 3
        channel._count_date = datetime.now().strftime("%Y-%m-%d")
        assert channel.can_send_architect_message() is False

    def test_daily_reset(self, channel):
        """日期变了计数重置。"""
        channel._daily_counts = {"proposal": 5}
        channel._count_date = "2020-01-01"  # 过去的日期
        assert channel.can_send_proposal() is True


class TestSendMessage:
    @pytest.mark.asyncio
    async def test_dnd_queues_message(self, channel):
        """勿扰时段消息进入队列。"""
        with patch.object(channel, "is_dnd", return_value=True):
            result = await channel.send_message("测试消息")
            assert result["sent"] is False
            assert result["queued"] is True
            assert channel.get_queue_size() == 1

    @pytest.mark.asyncio
    async def test_emergency_bypasses_dnd(self, channel):
        """紧急消息无视勿扰。"""
        mock_bot = MagicMock()
        mock_msg = MagicMock()
        mock_msg.message_id = 42
        mock_bot.send_message = AsyncMock(return_value=mock_msg)
        channel._bot = mock_bot

        with patch.object(channel, "is_dnd", return_value=True):
            result = await channel.send_message(
                "紧急！", message_type="emergency"
            )
            assert result["sent"] is True
            assert result["message_id"] == 42

    @pytest.mark.asyncio
    async def test_proposal_rate_limit(self, channel):
        """提案超过每日上限进入队列。"""
        channel._daily_counts = {"proposal": 2}
        channel._count_date = datetime.now().strftime("%Y-%m-%d")

        with patch.object(channel, "is_dnd", return_value=False):
            result = await channel.send_message("提案", message_type="proposal")
            assert result["sent"] is False
            assert result["queued"] is True

    @pytest.mark.asyncio
    async def test_successful_send(self, channel):
        """正常发送消息。"""
        mock_bot = MagicMock()
        mock_msg = MagicMock()
        mock_msg.message_id = 100
        mock_bot.send_message = AsyncMock(return_value=mock_msg)
        channel._bot = mock_bot

        with patch.object(channel, "is_dnd", return_value=False):
            result = await channel.send_message("你好")
            assert result["sent"] is True
            assert result["message_id"] == 100

    @pytest.mark.asyncio
    async def test_send_failure_queues(self, channel):
        """发送失败时消息进入队列。"""
        mock_bot = MagicMock()
        mock_bot.send_message = AsyncMock(side_effect=Exception("Network error"))
        channel._bot = mock_bot

        with patch.object(channel, "is_dnd", return_value=False):
            result = await channel.send_message("测试")
            assert result["sent"] is False
            assert result["queued"] is True
            assert "error" in result

    @pytest.mark.asyncio
    async def test_proposal_count_increments(self, channel):
        """发送提案后计数增加。"""
        mock_bot = MagicMock()
        mock_msg = MagicMock()
        mock_msg.message_id = 1
        mock_bot.send_message = AsyncMock(return_value=mock_msg)
        channel._bot = mock_bot

        with patch.object(channel, "is_dnd", return_value=False):
            await channel.send_message("提案1", message_type="proposal")
            assert channel._daily_counts.get("proposal") == 1
            await channel.send_message("提案2", message_type="proposal")
            assert channel._daily_counts.get("proposal") == 2


class TestSendProposal:
    @pytest.mark.asyncio
    async def test_sends_with_keyboard(self, channel):
        """发送提案带 inline keyboard。"""
        mock_bot = MagicMock()
        mock_msg = MagicMock()
        mock_msg.message_id = 1
        mock_bot.send_message = AsyncMock(return_value=mock_msg)
        channel._bot = mock_bot

        proposal = {
            "proposal_id": "prop_001",
            "problem": "测试问题",
            "solution": "测试方案",
            "level": 1,
        }

        with patch.object(channel, "is_dnd", return_value=False):
            result = await channel.send_proposal(proposal)
            assert result["sent"] is True

            # 检查调用参数中有 reply_markup
            call_kwargs = mock_bot.send_message.call_args
            assert call_kwargs.kwargs.get("reply_markup") is not None


class TestCallbackHandling:
    @pytest.mark.asyncio
    async def test_handle_approve(self, channel):
        result = await channel.handle_callback("approve:prop_024")
        assert result == {"action": "approve", "proposal_id": "prop_024"}

    @pytest.mark.asyncio
    async def test_handle_invalid(self, channel):
        result = await channel.handle_callback("invalid")
        assert result is None

    @pytest.mark.asyncio
    async def test_handler_called(self, channel):
        """注册的 handler 被调用。"""
        handler_calls = []
        channel.register_approval_handler(
            lambda action, pid: handler_calls.append((action, pid))
        )

        await channel.handle_callback("approve:prop_001")
        assert handler_calls == [("approve", "prop_001")]


class TestFlushQueue:
    @pytest.mark.asyncio
    async def test_flush_sends_queued(self, channel):
        """flush 发送队列中的消息。"""
        # 先队列两条消息
        channel._message_queue = [
            {"text": "msg1", "parse_mode": "Markdown", "reply_markup": None, "message_type": "general"},
            {"text": "msg2", "parse_mode": "Markdown", "reply_markup": None, "message_type": "general"},
        ]

        mock_bot = MagicMock()
        mock_msg = MagicMock()
        mock_msg.message_id = 1
        mock_bot.send_message = AsyncMock(return_value=mock_msg)
        channel._bot = mock_bot

        with patch.object(channel, "is_dnd", return_value=False):
            results = await channel.flush_queue()
            assert len(results) == 2
            assert channel.get_queue_size() == 0

    @pytest.mark.asyncio
    async def test_flush_during_dnd(self, channel):
        """勿扰时段 flush 不发送。"""
        channel._message_queue = [
            {"text": "msg1", "parse_mode": "Markdown", "reply_markup": None, "message_type": "general"},
        ]
        with patch.object(channel, "is_dnd", return_value=True):
            results = await channel.flush_queue()
            assert len(results) == 0
            assert channel.get_queue_size() == 1


class TestQueuePersistence:
    @pytest.mark.asyncio
    async def test_queue_writes_to_disk(self, channel):
        """消息入队时写入磁盘。"""
        with patch.object(channel, "is_dnd", return_value=True):
            await channel.send_message("持久化测试")

        queue_file = channel._queue_dir / "pending.jsonl"
        assert queue_file.exists()
        content = queue_file.read_text(encoding="utf-8")
        assert "持久化测试" in content
