"""Tests for run_council_review() in core/council.py."""

import json
import pytest
from unittest.mock import AsyncMock, patch

from core.council import (
    COUNCIL_ROLES,
    CouncilMemberReview,
    CouncilReview,
    run_council_review,
    _parse_member_response,
    _parse_conclusion_response,
    _build_proposal_text,
)


# ──────────────────────────────────────
#  Fixtures
# ──────────────────────────────────────

SAMPLE_PROPOSAL = {
    "proposal_id": "prop-001",
    "problem": "Observer 模块存在内存泄漏",
    "solution": "在 Observer.__del__ 中清理订阅列表",
    "files_affected": ["core/observer.py"],
    "priority": "high",
    "risk_level": "low",
}

STRUCTURED_MEMBER_RESPONSE = (
    "Concern: 该方案可能影响正在运行的订阅者。\n"
    "Recommendation: 建议添加单元测试覆盖清理路径。"
)

CONCLUSION_JSON = json.dumps({
    "conclusion": "通过",
    "summary": "4 位委员均认为方案可行，风险可控。",
})


def make_mock_llm(side_effects: list):
    """创建一个按 side_effects 列表顺序返回的 mock LLM。"""
    mock = AsyncMock()
    mock.complete = AsyncMock(side_effect=side_effects)
    return mock


# ──────────────────────────────────────
#  单元：解析函数
# ──────────────────────────────────────

class TestBuildProposalText:
    def test_includes_proposal_id(self):
        text = _build_proposal_text(SAMPLE_PROPOSAL)
        assert "prop-001" in text

    def test_includes_problem_and_solution(self):
        text = _build_proposal_text(SAMPLE_PROPOSAL)
        assert "Observer" in text
        assert "清理订阅列表" in text

    def test_files_list_joined(self):
        text = _build_proposal_text({"proposal_id": "x", "files_affected": ["a.py", "b.py"]})
        assert "a.py" in text
        assert "b.py" in text

    def test_minimal_proposal(self):
        text = _build_proposal_text({"proposal_id": "min"})
        assert "min" in text


class TestParseMemberResponse:
    def test_structured_english_keys(self):
        concern, rec = _parse_member_response(
            "Concern: 有风险\nRecommendation: 加测试"
        )
        assert "有风险" in concern
        assert "加测试" in rec

    def test_structured_chinese_keys(self):
        concern, rec = _parse_member_response(
            "担忧：存在泄漏\n建议：添加清理"
        )
        assert "存在泄漏" in concern
        assert "添加清理" in rec

    def test_unstructured_fallback(self):
        concern, rec = _parse_member_response("这是一段没有结构的分析文本。")
        assert "这是一段没有结构的分析文本。" in concern
        assert rec == "无特别建议"

    def test_empty_string_fallback(self):
        concern, rec = _parse_member_response("")
        assert rec == "无特别建议"


class TestParseConclusionResponse:
    def test_valid_approved(self):
        conclusion, summary = _parse_conclusion_response(
            json.dumps({"conclusion": "通过", "summary": "ok"})
        )
        assert conclusion == "通过"
        assert summary == "ok"

    def test_valid_rejected(self):
        conclusion, _ = _parse_conclusion_response(
            json.dumps({"conclusion": "否决", "summary": "风险太高"})
        )
        assert conclusion == "否决"

    def test_valid_needs_revision(self):
        conclusion, _ = _parse_conclusion_response(
            json.dumps({"conclusion": "修改后通过", "summary": "需要改进"})
        )
        assert conclusion == "修改后通过"

    def test_json_in_code_block(self):
        text = '```json\n{"conclusion": "通过", "summary": "good"}\n```'
        conclusion, summary = _parse_conclusion_response(text)
        assert conclusion == "通过"
        assert summary == "good"

    def test_invalid_json_defaults_to_needs_revision(self):
        conclusion, _ = _parse_conclusion_response("这根本不是 JSON")
        assert conclusion == "修改后通过"

    def test_invalid_conclusion_value_defaults(self):
        conclusion, _ = _parse_conclusion_response(
            json.dumps({"conclusion": "未知结论", "summary": ""})
        )
        assert conclusion == "修改后通过"


# ──────────────────────────────────────
#  集成：run_council_review
# ──────────────────────────────────────

class TestRunCouncilReviewBasic:
    @pytest.mark.asyncio
    async def test_returns_council_review_instance(self):
        # 5 次调用：4 个委员 + 1 个综合
        side_effects = [STRUCTURED_MEMBER_RESPONSE] * 4 + [CONCLUSION_JSON]
        mock_llm = make_mock_llm(side_effects)

        result = await run_council_review(SAMPLE_PROPOSAL, mock_llm, model="opus")

        assert isinstance(result, CouncilReview)

    @pytest.mark.asyncio
    async def test_has_four_reviews(self):
        side_effects = [STRUCTURED_MEMBER_RESPONSE] * 4 + [CONCLUSION_JSON]
        mock_llm = make_mock_llm(side_effects)

        result = await run_council_review(SAMPLE_PROPOSAL, mock_llm, model="opus")

        assert len(result.reviews) == 4

    @pytest.mark.asyncio
    async def test_review_roles_match_council_roles(self):
        side_effects = [STRUCTURED_MEMBER_RESPONSE] * 4 + [CONCLUSION_JSON]
        mock_llm = make_mock_llm(side_effects)

        result = await run_council_review(SAMPLE_PROPOSAL, mock_llm, model="opus")

        roles = {r.role for r in result.reviews}
        assert roles == set(COUNCIL_ROLES.keys())

    @pytest.mark.asyncio
    async def test_review_names_are_populated(self):
        side_effects = [STRUCTURED_MEMBER_RESPONSE] * 4 + [CONCLUSION_JSON]
        mock_llm = make_mock_llm(side_effects)

        result = await run_council_review(SAMPLE_PROPOSAL, mock_llm, model="opus")

        for review in result.reviews:
            assert review.name  # 非空

    @pytest.mark.asyncio
    async def test_concern_and_recommendation_parsed(self):
        side_effects = [STRUCTURED_MEMBER_RESPONSE] * 4 + [CONCLUSION_JSON]
        mock_llm = make_mock_llm(side_effects)

        result = await run_council_review(SAMPLE_PROPOSAL, mock_llm, model="opus")

        for review in result.reviews:
            assert review.concern
            assert review.recommendation

    @pytest.mark.asyncio
    async def test_llm_called_five_times(self):
        side_effects = [STRUCTURED_MEMBER_RESPONSE] * 4 + [CONCLUSION_JSON]
        mock_llm = make_mock_llm(side_effects)

        await run_council_review(SAMPLE_PROPOSAL, mock_llm, model="opus")

        assert mock_llm.complete.call_count == 5

    @pytest.mark.asyncio
    async def test_proposal_id_preserved(self):
        side_effects = [STRUCTURED_MEMBER_RESPONSE] * 4 + [CONCLUSION_JSON]
        mock_llm = make_mock_llm(side_effects)

        result = await run_council_review(SAMPLE_PROPOSAL, mock_llm, model="opus")

        assert result.proposal_id == "prop-001"


class TestReviewWithUnstructuredResponse:
    @pytest.mark.asyncio
    async def test_unstructured_concern_is_full_text(self):
        unstructured = "这个方案存在一些潜在问题，需要仔细考虑边界情况。"
        side_effects = [unstructured] * 4 + [CONCLUSION_JSON]
        mock_llm = make_mock_llm(side_effects)

        result = await run_council_review(SAMPLE_PROPOSAL, mock_llm, model="opus")

        for review in result.reviews:
            assert unstructured in review.concern
            assert review.recommendation == "无特别建议"


class TestConclusionApproved:
    @pytest.mark.asyncio
    async def test_conclusion_is_approved(self):
        approved_json = json.dumps({"conclusion": "通过", "summary": "一切正常"})
        side_effects = [STRUCTURED_MEMBER_RESPONSE] * 4 + [approved_json]
        mock_llm = make_mock_llm(side_effects)

        result = await run_council_review(SAMPLE_PROPOSAL, mock_llm)

        assert result.conclusion == "通过"
        assert result.is_approved() is True
        assert result.summary == "一切正常"


class TestConclusionRejected:
    @pytest.mark.asyncio
    async def test_conclusion_is_rejected(self):
        rejected_json = json.dumps({"conclusion": "否决", "summary": "风险太高"})
        side_effects = [STRUCTURED_MEMBER_RESPONSE] * 4 + [rejected_json]
        mock_llm = make_mock_llm(side_effects)

        result = await run_council_review(SAMPLE_PROPOSAL, mock_llm)

        assert result.conclusion == "否决"
        assert result.is_rejected() is True
        assert result.summary == "风险太高"


class TestConclusionNeedsRevision:
    @pytest.mark.asyncio
    async def test_conclusion_needs_revision(self):
        revision_json = json.dumps({"conclusion": "修改后通过", "summary": "需要补充测试"})
        side_effects = [STRUCTURED_MEMBER_RESPONSE] * 4 + [revision_json]
        mock_llm = make_mock_llm(side_effects)

        result = await run_council_review(SAMPLE_PROPOSAL, mock_llm)

        assert result.conclusion == "修改后通过"
        assert result.needs_revision() is True
        assert result.summary == "需要补充测试"


class TestConclusionParseFailure:
    @pytest.mark.asyncio
    async def test_non_json_defaults_to_needs_revision(self):
        side_effects = [STRUCTURED_MEMBER_RESPONSE] * 4 + ["这不是 JSON 格式的回复"]
        mock_llm = make_mock_llm(side_effects)

        result = await run_council_review(SAMPLE_PROPOSAL, mock_llm)

        assert result.conclusion == "修改后通过"

    @pytest.mark.asyncio
    async def test_invalid_conclusion_value_defaults(self):
        bad_json = json.dumps({"conclusion": "未知", "summary": ""})
        side_effects = [STRUCTURED_MEMBER_RESPONSE] * 4 + [bad_json]
        mock_llm = make_mock_llm(side_effects)

        result = await run_council_review(SAMPLE_PROPOSAL, mock_llm)

        assert result.conclusion == "修改后通过"


class TestSingleMemberFailure:
    @pytest.mark.asyncio
    async def test_one_failure_doesnt_stop_others(self):
        """某个委员的 LLM 调用抛异常，其他委员仍继续审议。"""
        side_effects = [
            STRUCTURED_MEMBER_RESPONSE,  # safety 成功
            RuntimeError("LLM timeout"),  # efficiency 失败
            STRUCTURED_MEMBER_RESPONSE,  # user_experience 成功
            STRUCTURED_MEMBER_RESPONSE,  # long_term 成功
            CONCLUSION_JSON,             # 综合结论
        ]
        mock_llm = make_mock_llm(side_effects)

        result = await run_council_review(SAMPLE_PROPOSAL, mock_llm)

        # 仍然有 4 个审议结果
        assert len(result.reviews) == 4

    @pytest.mark.asyncio
    async def test_failed_member_has_error_concern(self):
        """失败的委员审议中 concern 包含错误信息。"""
        side_effects = [
            RuntimeError("network error"),  # safety 失败
            STRUCTURED_MEMBER_RESPONSE,
            STRUCTURED_MEMBER_RESPONSE,
            STRUCTURED_MEMBER_RESPONSE,
            CONCLUSION_JSON,
        ]
        mock_llm = make_mock_llm(side_effects)

        result = await run_council_review(SAMPLE_PROPOSAL, mock_llm)

        # 第一个委员（safety）的 concern 应包含错误信息
        safety_review = next(r for r in result.reviews if r.role == "safety")
        assert "审议失败" in safety_review.concern or "network error" in safety_review.concern

    @pytest.mark.asyncio
    async def test_conclusion_still_generated_after_member_failure(self):
        """即使某个委员失败，综合结论仍然生成。"""
        side_effects = [
            RuntimeError("timeout"),
            STRUCTURED_MEMBER_RESPONSE,
            STRUCTURED_MEMBER_RESPONSE,
            STRUCTURED_MEMBER_RESPONSE,
            CONCLUSION_JSON,
        ]
        mock_llm = make_mock_llm(side_effects)

        result = await run_council_review(SAMPLE_PROPOSAL, mock_llm)

        assert result.conclusion == "通过"

    @pytest.mark.asyncio
    async def test_conclusion_failure_defaults_to_needs_revision(self):
        """综合结论 LLM 调用失败时，默认修改后通过。"""
        side_effects = [
            STRUCTURED_MEMBER_RESPONSE,
            STRUCTURED_MEMBER_RESPONSE,
            STRUCTURED_MEMBER_RESPONSE,
            STRUCTURED_MEMBER_RESPONSE,
            RuntimeError("conclusion failed"),
        ]
        mock_llm = make_mock_llm(side_effects)

        result = await run_council_review(SAMPLE_PROPOSAL, mock_llm)

        assert result.conclusion == "修改后通过"
