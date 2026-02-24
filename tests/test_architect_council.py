"""Tests for Council integration in ArchitectEngine."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from core.architect import ArchitectEngine
from core.council import CouncilMemberReview, CouncilReview
from core.llm_client import MockLLMClient


# ──────────────────────────────────────
#  Helpers
# ──────────────────────────────────────

def _make_engine(
    workspace: Path,
    llm_responses: dict | None = None,
    telegram_channel=None,
) -> ArchitectEngine:
    llm = MockLLMClient(responses=llm_responses or {})
    return ArchitectEngine(
        workspace_path=workspace,
        llm_client=llm,
        telegram_channel=telegram_channel,
    )


def _make_proposal(
    proposal_id: str = "prop_test_001",
    blast_radius: str = "medium",
    files_count: int = 4,
    status: str = "new",
) -> dict:
    """生成一个提案字典。"""
    return {
        "proposal_id": proposal_id,
        "files_affected": [f"rules/experience/{i}.md" for i in range(files_count)],
        "blast_radius": blast_radius,
        "problem": "测试问题描述",
        "solution": "测试方案描述",
        "new_content": "# 测试规则\n",
        "status": status,
    }


def _make_council_review(conclusion: str, proposal_id: str = "prop_test_001") -> CouncilReview:
    """生成一个 CouncilReview 对象。"""
    reviews = [
        CouncilMemberReview(
            role="safety",
            name="安全委员",
            concern="无特别担忧",
            recommendation="建议通过",
        ),
    ]
    return CouncilReview(
        proposal_id=proposal_id,
        reviews=reviews,
        conclusion=conclusion,
        summary=f"综合结论：{conclusion}",
    )


# ──────────────────────────────────────
#  Tests
# ──────────────────────────────────────

class TestCouncilTriggerByLevel:
    async def test_level_2_triggers_council(self, workspace: Path):
        """Level 2 提案应触发 council review。"""
        proposal = _make_proposal(blast_radius="medium", files_count=4)
        engine = _make_engine(workspace)
        engine._save_proposal(proposal)

        mock_review = _make_council_review("通过")

        with patch(
            "core.architect.run_council_review",
            new=AsyncMock(return_value=mock_review),
        ) as mock_council:
            await engine.execute_proposal(proposal)

        mock_council.assert_awaited_once()

    async def test_level_0_skips_council(self, workspace: Path):
        """Level 0 提案不触发 council review。"""
        proposal = _make_proposal(blast_radius="trivial", files_count=1)
        engine = _make_engine(workspace)
        engine._save_proposal(proposal)
        (workspace / "rules" / "experience").mkdir(parents=True, exist_ok=True)

        with patch(
            "core.architect.run_council_review",
            new=AsyncMock(),
        ) as mock_council:
            result = await engine.execute_proposal(proposal)

        mock_council.assert_not_awaited()
        assert result["status"] == "executed"

    async def test_level_1_skips_council(self, workspace: Path):
        """Level 1 提案不触发 council review。"""
        proposal = _make_proposal(blast_radius="small", files_count=2)
        engine = _make_engine(workspace)
        engine._save_proposal(proposal)
        (workspace / "rules" / "experience").mkdir(parents=True, exist_ok=True)

        with patch(
            "core.architect.run_council_review",
            new=AsyncMock(),
        ) as mock_council:
            result = await engine.execute_proposal(proposal)

        mock_council.assert_not_awaited()
        assert result["status"] == "executed"


class TestCouncilConclusion:
    async def test_council_rejection_sets_rejected(self, workspace: Path):
        """审议结论为否决时，提案状态为 rejected。"""
        proposal = _make_proposal(blast_radius="medium", files_count=4)
        engine = _make_engine(workspace)
        engine._save_proposal(proposal)

        mock_review = _make_council_review("否决")

        with patch("core.architect.run_council_review", new=AsyncMock(return_value=mock_review)):
            result = await engine.execute_proposal(proposal)

        assert result["status"] == "rejected"
        assert result["backup_id"] is None

        # 磁盘上的提案状态应为 rejected
        saved = engine._load_proposal("prop_test_001")
        assert saved["status"] == "rejected"

    async def test_council_approved_continues(self, workspace: Path):
        """审议结论为通过时，Level 2 提案继续走 pending_approval 流程。"""
        proposal = _make_proposal(blast_radius="medium", files_count=4)
        engine = _make_engine(workspace)
        engine._save_proposal(proposal)

        mock_review = _make_council_review("通过")

        with patch("core.architect.run_council_review", new=AsyncMock(return_value=mock_review)):
            result = await engine.execute_proposal(proposal)

        # Level 2 通过审议后仍需人工审批
        assert result["status"] == "pending_approval"

    async def test_council_needs_revision(self, workspace: Path):
        """审议结论为修改后通过时，提案标记为 needs_revision。"""
        proposal = _make_proposal(blast_radius="medium", files_count=4)
        engine = _make_engine(workspace)
        engine._save_proposal(proposal)

        mock_review = _make_council_review("修改后通过")

        with patch("core.architect.run_council_review", new=AsyncMock(return_value=mock_review)):
            result = await engine.execute_proposal(proposal)

        assert result["status"] == "needs_revision"

        saved = engine._load_proposal("prop_test_001")
        assert saved["status"] == "needs_revision"


class TestCouncilReviewStorage:
    async def test_council_review_stored_in_proposal(self, workspace: Path):
        """审议结果应保存在提案的 council_review 字段中。"""
        proposal = _make_proposal(blast_radius="medium", files_count=4)
        engine = _make_engine(workspace)
        engine._save_proposal(proposal)

        mock_review = _make_council_review("通过")

        with patch("core.architect.run_council_review", new=AsyncMock(return_value=mock_review)):
            await engine.execute_proposal(proposal)

        saved = engine._load_proposal("prop_test_001")
        assert "council_review" in saved
        cr = saved["council_review"]
        assert cr["conclusion"] == "通过"
        assert cr["summary"] == "综合结论：通过"
        assert len(cr["reviews"]) == 1
        assert cr["reviews"][0]["role"] == "safety"


class TestCouncilFailureResilience:
    async def test_council_failure_doesnt_block(self, workspace: Path):
        """council review 抛异常时不阻塞提案流程，降级为无审议处理。"""
        proposal = _make_proposal(blast_radius="medium", files_count=4)
        engine = _make_engine(workspace)
        engine._save_proposal(proposal)

        with patch(
            "core.architect.run_council_review",
            new=AsyncMock(side_effect=RuntimeError("LLM timeout")),
        ):
            result = await engine.execute_proposal(proposal)

        # council 失败后，Level 2 仍正常进入 pending_approval
        assert result["status"] == "pending_approval"


class TestCouncilTelegramNotification:
    async def test_council_notification_sent_on_conclusion(self, workspace: Path):
        """有 telegram_channel 时，审议结论应发送通知。"""
        sent_messages = []

        class MockTelegram:
            async def send_message(self, text, message_type="general", **kwargs):
                sent_messages.append({"text": text, "type": message_type})
                return {"sent": True}

            async def send_proposal(self, proposal):
                sent_messages.append({"type": "proposal"})
                return {"sent": True}

        proposal = _make_proposal(blast_radius="medium", files_count=4)
        engine = _make_engine(workspace, telegram_channel=MockTelegram())
        engine._save_proposal(proposal)

        mock_review = _make_council_review("通过")

        with patch("core.architect.run_council_review", new=AsyncMock(return_value=mock_review)):
            await engine.execute_proposal(proposal)

        # 应有 council 类型消息和 pending_approval 类型消息
        types = [m["type"] for m in sent_messages]
        assert "council" in types

    async def test_no_notification_without_telegram(self, workspace: Path):
        """没有 telegram_channel 时，审议通知静默跳过（不报错）。"""
        proposal = _make_proposal(blast_radius="medium", files_count=4)
        engine = _make_engine(workspace, telegram_channel=None)
        engine._save_proposal(proposal)

        mock_review = _make_council_review("否决")

        with patch("core.architect.run_council_review", new=AsyncMock(return_value=mock_review)):
            result = await engine.execute_proposal(proposal)

        assert result["status"] == "rejected"
