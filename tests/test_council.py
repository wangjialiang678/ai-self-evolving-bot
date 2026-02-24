"""Tests for core/council.py — Council 委员定义。"""

import pytest
from core.council import COUNCIL_ROLES, CouncilMemberReview, CouncilReview


class TestCouncilRoles:
    def test_has_four_roles(self):
        assert len(COUNCIL_ROLES) == 4

    def test_role_keys(self):
        expected = {"safety", "efficiency", "user_experience", "long_term"}
        assert set(COUNCIL_ROLES.keys()) == expected

    @pytest.mark.parametrize("role_key", ["safety", "efficiency", "user_experience", "long_term"])
    def test_each_role_has_name(self, role_key):
        assert "name" in COUNCIL_ROLES[role_key]
        assert COUNCIL_ROLES[role_key]["name"]

    @pytest.mark.parametrize("role_key", ["safety", "efficiency", "user_experience", "long_term"])
    def test_each_role_has_emoji(self, role_key):
        assert "emoji" in COUNCIL_ROLES[role_key]
        assert COUNCIL_ROLES[role_key]["emoji"]

    @pytest.mark.parametrize("role_key", ["safety", "efficiency", "user_experience", "long_term"])
    def test_each_role_has_system_prompt(self, role_key):
        assert "system_prompt" in COUNCIL_ROLES[role_key]
        assert len(COUNCIL_ROLES[role_key]["system_prompt"]) > 10


class TestCouncilMemberReview:
    def test_create(self):
        review = CouncilMemberReview(
            role="safety",
            name="安全委员",
            concern="可能影响核心功能",
            recommendation="添加回滚机制",
        )
        assert review.role == "safety"
        assert review.name == "安全委员"
        assert review.concern == "可能影响核心功能"
        assert review.recommendation == "添加回滚机制"


class TestCouncilReview:
    def test_create_minimal(self):
        cr = CouncilReview(proposal_id="prop-001")
        assert cr.proposal_id == "prop-001"
        assert cr.reviews == []
        assert cr.conclusion == ""
        assert cr.summary == ""

    def test_default_reviews_is_independent_list(self):
        cr1 = CouncilReview(proposal_id="p1")
        cr2 = CouncilReview(proposal_id="p2")
        cr1.reviews.append(
            CouncilMemberReview(role="safety", name="安全委员", concern="x", recommendation="y")
        )
        assert cr2.reviews == []

    def test_is_approved(self):
        cr = CouncilReview(proposal_id="p", conclusion="通过")
        assert cr.is_approved() is True
        assert cr.needs_revision() is False
        assert cr.is_rejected() is False

    def test_needs_revision(self):
        cr = CouncilReview(proposal_id="p", conclusion="修改后通过")
        assert cr.is_approved() is False
        assert cr.needs_revision() is True
        assert cr.is_rejected() is False

    def test_is_rejected(self):
        cr = CouncilReview(proposal_id="p", conclusion="否决")
        assert cr.is_approved() is False
        assert cr.needs_revision() is False
        assert cr.is_rejected() is True

    def test_empty_conclusion(self):
        cr = CouncilReview(proposal_id="p")
        assert cr.is_approved() is False
        assert cr.needs_revision() is False
        assert cr.is_rejected() is False
