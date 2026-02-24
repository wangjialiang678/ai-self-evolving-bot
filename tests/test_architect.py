"""Tests for B5 ArchitectEngine."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from core.architect import ArchitectEngine
from core.council import CouncilReview
from core.llm_client import MockLLMClient


# ──────────────────────────────────────
#  Helpers
# ──────────────────────────────────────

def _make_engine(
    workspace: Path,
    llm_responses: dict | None = None,
    rollback_manager=None,
    telegram_channel=None,
) -> ArchitectEngine:
    llm = MockLLMClient(responses=llm_responses or {})
    return ArchitectEngine(
        workspace_path=workspace,
        llm_client=llm,
        rollback_manager=rollback_manager,
        telegram_channel=telegram_channel,
    )


def _write_observer_report(workspace: Path, date_str: str, content: str = "") -> Path:
    reports_dir = workspace / "observations" / "deep_reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    path = reports_dir / f"{date_str}.md"
    path.write_text(content or f"# Observer 深度报告 — {date_str}\n\n## 关键发现\n\n发现了若干问题。\n", encoding="utf-8")
    return path


def _sample_proposals_json(n: int = 1) -> str:
    proposals = []
    for i in range(n):
        proposals.append({
            "proposal_id": f"prop_{i+1:03d}",
            "level": 1,
            "trigger_source": "observer_report:2026-02-25",
            "problem": f"问题{i+1}",
            "solution": f"方案{i+1}",
            "files_affected": ["rules/experience/task_strategies.md"],
            "blast_radius": "small",
            "expected_effect": "提升成功率",
            "verification_method": "下5次任务成功率",
            "verification_days": 5,
            "rollback_plan": "恢复原文件",
            "new_content": "# 新规则\n\n控制长度。\n",
        })
    return json.dumps(proposals, ensure_ascii=False)


# ──────────────────────────────────────
#  Test: analyze_and_propose
# ──────────────────────────────────────

class TestAnalyzeAndPropose:
    async def test_basic_flow_returns_proposals(self, workspace: Path):
        """基本流程：有报告时返回提案列表。"""
        _write_observer_report(workspace, "2026-02-25")
        engine = _make_engine(workspace, llm_responses={"opus": _sample_proposals_json(2)})

        proposals = await engine.analyze_and_propose()

        assert len(proposals) == 2
        assert proposals[0]["proposal_id"] == "prop_001"
        assert proposals[1]["proposal_id"] == "prop_002"

    async def test_no_report_returns_empty(self, workspace: Path):
        """没有 Observer 报告时返回空列表。"""
        engine = _make_engine(workspace, llm_responses={"opus": _sample_proposals_json()})
        proposals = await engine.analyze_and_propose()
        assert proposals == []

    async def test_proposals_saved_to_disk(self, workspace: Path):
        """提案应保存为 JSON 文件。"""
        _write_observer_report(workspace, "2026-02-25")
        engine = _make_engine(workspace, llm_responses={"opus": _sample_proposals_json()})

        proposals = await engine.analyze_and_propose()

        prop_id = proposals[0]["proposal_id"]
        saved_path = workspace / "architect" / "proposals" / f"{prop_id}.json"
        assert saved_path.exists()
        data = json.loads(saved_path.read_text(encoding="utf-8"))
        assert data["proposal_id"] == prop_id

    async def test_llm_failure_returns_empty(self, workspace: Path):
        """LLM 返回空字符串时优雅降级，返回空列表。"""
        _write_observer_report(workspace, "2026-02-25")
        engine = _make_engine(workspace, llm_responses={"opus": ""})

        proposals = await engine.analyze_and_propose()
        assert proposals == []

    async def test_llm_invalid_json_returns_empty(self, workspace: Path):
        """LLM 返回非 JSON 时优雅降级。"""
        _write_observer_report(workspace, "2026-02-25")
        engine = _make_engine(workspace, llm_responses={"opus": "这不是JSON内容"})

        proposals = await engine.analyze_and_propose()
        assert proposals == []


# ──────────────────────────────────────
#  Test: determine_approval_level
# ──────────────────────────────────────

class TestDetermineApprovalLevel:
    def test_level_0_trivial_single_file(self, workspace: Path):
        """Level 0: trivial + 1 个文件。"""
        engine = _make_engine(workspace)
        proposal = {"files_affected": ["rules/experience/a.md"], "blast_radius": "trivial"}
        assert engine.determine_approval_level(proposal) == 0

    def test_level_1_small_two_files(self, workspace: Path):
        """Level 1: small + 2 个文件。"""
        engine = _make_engine(workspace)
        proposal = {
            "files_affected": ["rules/experience/a.md", "rules/experience/b.md"],
            "blast_radius": "small",
        }
        assert engine.determine_approval_level(proposal) == 1

    def test_level_2_medium_four_files(self, workspace: Path):
        """Level 2: medium + 4 个文件。"""
        engine = _make_engine(workspace)
        proposal = {
            "files_affected": [f"rules/experience/{i}.md" for i in range(4)],
            "blast_radius": "medium",
        }
        assert engine.determine_approval_level(proposal) == 2

    def test_level_3_large_blast_radius(self, workspace: Path):
        """Level 3: blast_radius=large。"""
        engine = _make_engine(workspace)
        proposal = {
            "files_affected": ["rules/experience/a.md"],
            "blast_radius": "large",
        }
        assert engine.determine_approval_level(proposal) == 3

    def test_level_3_too_many_files(self, workspace: Path):
        """Level 3: 超过 5 个文件。"""
        engine = _make_engine(workspace)
        proposal = {
            "files_affected": [f"rules/experience/{i}.md" for i in range(6)],
            "blast_radius": "small",
        }
        assert engine.determine_approval_level(proposal) == 3


# ──────────────────────────────────────
#  Test: execute_proposal
# ──────────────────────────────────────

class TestExecuteProposal:
    async def test_level_0_auto_executes(self, workspace: Path):
        """Level 0: 自动执行，不通知。"""
        # 确保目标文件的父目录存在
        (workspace / "rules" / "experience").mkdir(parents=True, exist_ok=True)
        engine = _make_engine(workspace, llm_responses={"opus": "# 新规则内容\n"})

        proposal = {
            "proposal_id": "prop_level0",
            "files_affected": ["rules/experience/task_strategies.md"],
            "blast_radius": "trivial",
            "problem": "测试问题",
            "solution": "测试方案",
            "new_content": "# 新规则\n",
            "status": "new",
        }
        result = await engine.execute_proposal(proposal)

        assert result["status"] == "executed"

    async def test_level_1_executes_then_notifies(self, workspace: Path):
        """Level 1: 执行后通知。"""
        (workspace / "rules" / "experience").mkdir(parents=True, exist_ok=True)

        sent_messages = []

        class MockTelegram:
            async def send_message(self, text, message_type="general", **kwargs):
                sent_messages.append({"text": text, "type": message_type})
                return {"sent": True}

            async def send_proposal(self, proposal):
                sent_messages.append({"type": "proposal"})
                return {"sent": True}

        engine = _make_engine(workspace, telegram_channel=MockTelegram())

        proposal = {
            "proposal_id": "prop_level1",
            "files_affected": ["rules/experience/a.md", "rules/experience/b.md"],
            "blast_radius": "small",
            "problem": "问题",
            "solution": "方案",
            "new_content": "# 内容\n",
            "status": "new",
        }
        result = await engine.execute_proposal(proposal)

        assert result["status"] == "executed"
        assert len(sent_messages) >= 1

    async def test_level_2_pending_approval(self, workspace: Path):
        """Level 2: 等待审批，发送提案通知（council 审议通过后）。"""
        sent = []

        class MockTelegram:
            async def send_proposal(self, proposal):
                sent.append(proposal)
                return {"sent": True}

            async def send_message(self, text, message_type="general", **kwargs):
                sent.append({"text": text, "type": message_type})
                return {"sent": True}

        engine = _make_engine(workspace, telegram_channel=MockTelegram())

        # 先保存提案到磁盘，以便 _update_proposal_status 能找到
        proposal = {
            "proposal_id": "prop_level2",
            "files_affected": [f"rules/experience/{i}.md" for i in range(4)],
            "blast_radius": "medium",
            "problem": "问题",
            "solution": "方案",
            "new_content": "# 内容\n",
            "status": "new",
        }
        engine._save_proposal(proposal)

        approved_review = CouncilReview(
            proposal_id="prop_level2", conclusion="通过", summary="测试通过"
        )
        with patch(
            "core.architect.run_council_review",
            new=AsyncMock(return_value=approved_review),
        ):
            result = await engine.execute_proposal(proposal)

        assert result["status"] == "pending_approval"
        assert result["backup_id"] is None
        # council 通知 + send_proposal 各发送一条
        assert len(sent) >= 1

    async def test_level_0_file_written(self, workspace: Path):
        """Level 0 执行后，文件内容应被写入。"""
        target = workspace / "rules" / "experience" / "task_strategies.md"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("# 旧内容\n", encoding="utf-8")

        engine = _make_engine(workspace)
        proposal = {
            "proposal_id": "prop_write_test",
            "files_affected": ["rules/experience/task_strategies.md"],
            "blast_radius": "trivial",
            "problem": "问题",
            "solution": "方案",
            "new_content": "# 新内容\n经过改进的规则。\n",
            "status": "new",
        }
        await engine.execute_proposal(proposal)

        assert "新内容" in target.read_text(encoding="utf-8")


# ──────────────────────────────────────
#  Test: check_verification
# ──────────────────────────────────────

class TestCheckVerification:
    async def test_verifying_within_period(self, workspace: Path):
        """验证期内返回 verifying。"""
        engine = _make_engine(workspace)

        # 刚执行（2 天前）
        executed_at = (datetime.now() - timedelta(days=2)).replace(microsecond=0).isoformat()
        proposal = {
            "proposal_id": "prop_verify_001",
            "files_affected": ["rules/experience/a.md"],
            "blast_radius": "trivial",
            "verification_days": 5,
            "executed_at": executed_at,
            "status": "executed",
        }
        engine._save_proposal(proposal)

        result = await engine.check_verification("prop_verify_001")
        assert result["status"] == "verifying"
        assert result["remaining_days"] > 0

    async def test_validated_after_period_no_signals(self, workspace: Path):
        """验证期结束且无高优先信号 → validated。"""
        engine = _make_engine(workspace)

        # 6 天前执行，验证期 5 天
        executed_at = (datetime.now() - timedelta(days=6)).replace(microsecond=0).isoformat()
        proposal = {
            "proposal_id": "prop_validate_002",
            "files_affected": ["rules/experience/a.md"],
            "blast_radius": "trivial",
            "verification_days": 5,
            "executed_at": executed_at,
            "status": "executed",
        }
        engine._save_proposal(proposal)
        # 确保 active.jsonl 为空（无高优先信号）
        (workspace / "signals" / "active.jsonl").write_text("", encoding="utf-8")

        result = await engine.check_verification("prop_validate_002")
        assert result["status"] == "validated"

    async def test_rolled_back_after_period_with_signals(self, workspace: Path):
        """验证期结束但有 HIGH 信号 → rolled_back（需要 rollback_manager）。"""
        class MockRollback:
            def __init__(self):
                self.rolled_back = []

            def backup(self, files, proposal_id):
                return f"backup_{proposal_id}"

            def rollback(self, backup_id):
                self.rolled_back.append(backup_id)
                return {"status": "success"}

        mock_rb = MockRollback()
        engine = _make_engine(workspace, rollback_manager=mock_rb)

        executed_at = (datetime.now() - timedelta(days=6)).replace(microsecond=0).isoformat()
        proposal = {
            "proposal_id": "prop_rollback_003",
            "files_affected": ["rules/experience/a.md"],
            "blast_radius": "trivial",
            "verification_days": 5,
            "executed_at": executed_at,
            "backup_id": "backup_prop_rollback_003",
            "status": "executed",
        }
        engine._save_proposal(proposal)

        # 写入 HIGH 信号
        signal = {"signal_id": "sig_001", "priority": "HIGH", "description": "仍有问题"}
        (workspace / "signals" / "active.jsonl").write_text(
            json.dumps(signal, ensure_ascii=False) + "\n", encoding="utf-8"
        )

        result = await engine.check_verification("prop_rollback_003")
        assert result["status"] == "rolled_back"
        assert "backup_prop_rollback_003" in mock_rb.rolled_back

    async def test_not_found_proposal(self, workspace: Path):
        """不存在的提案返回 not_found。"""
        engine = _make_engine(workspace)
        result = await engine.check_verification("prop_nonexistent_999")
        assert result["status"] == "not_found"


# ──────────────────────────────────────
#  Test: get_pending_proposals
# ──────────────────────────────────────

class TestGetPendingProposals:
    def test_returns_pending_proposals(self, workspace: Path):
        """get_pending_proposals 只返回 pending_approval 状态的提案。"""
        engine = _make_engine(workspace)

        engine._save_proposal({"proposal_id": "prop_p1", "status": "pending_approval"})
        engine._save_proposal({"proposal_id": "prop_p2", "status": "executed"})
        engine._save_proposal({"proposal_id": "prop_p3", "status": "pending_discussion"})
        engine._save_proposal({"proposal_id": "prop_p4", "status": "new"})

        pending = engine.get_pending_proposals()
        ids = [p["proposal_id"] for p in pending]

        assert "prop_p1" in ids
        assert "prop_p3" in ids
        assert "prop_p4" in ids
        assert "prop_p2" not in ids

    def test_empty_when_no_proposals(self, workspace: Path):
        """没有提案时返回空列表。"""
        engine = _make_engine(workspace)
        assert engine.get_pending_proposals() == []
