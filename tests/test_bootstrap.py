"""测试 Bootstrap 引导流程。"""

import json
import pytest
from pathlib import Path
from core.bootstrap import BootstrapFlow


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def ws(tmp_path):
    """创建带有标准子目录的 workspace。"""
    dirs = [
        "rules/constitution", "rules/experience",
        "memory/user", "memory/projects",
        "memory/conversations", "memory/daily_summaries",
        "skills/learned", "skills/seed",
        "observations/light_logs", "observations/deep_reports",
        "signals", "architect/proposals", "architect/modifications",
        "backups", "metrics/daily", "logs",
    ]
    for d in dirs:
        (tmp_path / d).mkdir(parents=True)
    return tmp_path


@pytest.fixture
def flow(ws):
    return BootstrapFlow(ws)


BACKGROUND_INPUT = {
    "name": "Alice",
    "role": "开发者",
    "experience": "高级",
    "languages": "Python, TypeScript",
    "focus": "AI 工程",
}

PROJECTS_INPUT = {
    "project_name": "my-agent",
    "description": "自进化 AI 代理",
    "tech_stack": "Python, Claude API",
    "current_phase": "开发",
}

PREFERENCES_INPUT = {
    "response_style": "简洁",
    "language": "中文",
    "notification_level": "normal",
}


# ---------------------------------------------------------------------------
# is_bootstrapped
# ---------------------------------------------------------------------------


class TestIsBootstrapped:
    def test_false_when_no_user_md(self, flow):
        """USER.md 不存在时返回 False。"""
        assert flow.is_bootstrapped() is False

    def test_false_when_user_md_empty(self, flow, ws):
        """USER.md 存在但为空时返回 False。"""
        (ws / "USER.md").write_text("")
        assert flow.is_bootstrapped() is False

    def test_true_when_user_md_present(self, flow, ws):
        """USER.md 存在且非空时返回 True。"""
        (ws / "USER.md").write_text("# 用户档案\n\n- **称呼**: Alice\n")
        assert flow.is_bootstrapped() is True


# ---------------------------------------------------------------------------
# get_current_stage
# ---------------------------------------------------------------------------


class TestGetCurrentStage:
    def test_not_started_initially(self, flow):
        """初始状态为 not_started。"""
        assert flow.get_current_stage() == "not_started"

    def test_stage_from_state_file(self, flow, ws):
        """从 state 文件读取阶段。"""
        state = {
            "current_stage": "projects",
            "completed_stages": ["background"],
            "started_at": "2026-02-23T10:00:00",
            "completed_at": None,
        }
        (ws / ".bootstrap_state.json").write_text(
            json.dumps(state), encoding="utf-8"
        )
        assert flow.get_current_stage() == "projects"

    def test_completed_when_user_md_exists(self, flow, ws):
        """USER.md 非空时 get_current_stage 返回 completed。"""
        (ws / "USER.md").write_text("# 用户档案\n\n- **称呼**: Alice\n")
        assert flow.get_current_stage() == "completed"


# ---------------------------------------------------------------------------
# process_stage: background
# ---------------------------------------------------------------------------


class TestProcessStageBackground:
    async def test_background_creates_user_md(self, flow, ws):
        result = await flow.process_stage("background", BACKGROUND_INPUT)
        assert (ws / "USER.md").exists()
        assert (ws / "USER.md").stat().st_size > 0

    async def test_background_returns_correct_next_stage(self, flow):
        result = await flow.process_stage("background", BACKGROUND_INPUT)
        assert result["stage"] == "background"
        assert result["next_stage"] == "projects"
        assert result["completed"] is False

    async def test_background_prompt_is_for_projects(self, flow):
        result = await flow.process_stage("background", BACKGROUND_INPUT)
        assert "项目" in result["prompt"]

    async def test_background_updates_state(self, flow, ws):
        await flow.process_stage("background", BACKGROUND_INPUT)
        state = json.loads((ws / ".bootstrap_state.json").read_text())
        assert "background" in state["completed_stages"]
        assert state["current_stage"] == "projects"


# ---------------------------------------------------------------------------
# process_stage: projects
# ---------------------------------------------------------------------------


class TestProcessStageProjects:
    async def test_projects_creates_context_md(self, flow, ws):
        await flow.process_stage("background", BACKGROUND_INPUT)
        await flow.process_stage("projects", PROJECTS_INPUT)
        ctx = ws / "memory" / "projects" / "my-agent" / "context.md"
        assert ctx.exists()
        assert ctx.stat().st_size > 0

    async def test_projects_returns_correct_next_stage(self, flow):
        await flow.process_stage("background", BACKGROUND_INPUT)
        result = await flow.process_stage("projects", PROJECTS_INPUT)
        assert result["stage"] == "projects"
        assert result["next_stage"] == "preferences"
        assert result["completed"] is False

    async def test_projects_updates_state(self, flow, ws):
        await flow.process_stage("background", BACKGROUND_INPUT)
        await flow.process_stage("projects", PROJECTS_INPUT)
        state = json.loads((ws / ".bootstrap_state.json").read_text())
        assert "projects" in state["completed_stages"]
        assert state["current_stage"] == "preferences"


# ---------------------------------------------------------------------------
# process_stage: preferences
# ---------------------------------------------------------------------------


class TestProcessStagePreferences:
    async def test_preferences_creates_preferences_md(self, flow, ws):
        await flow.process_stage("background", BACKGROUND_INPUT)
        await flow.process_stage("projects", PROJECTS_INPUT)
        await flow.process_stage("preferences", PREFERENCES_INPUT)
        pref = ws / "memory" / "user" / "preferences.md"
        assert pref.exists()
        assert pref.stat().st_size > 0

    async def test_preferences_completed_true(self, flow):
        await flow.process_stage("background", BACKGROUND_INPUT)
        await flow.process_stage("projects", PROJECTS_INPUT)
        result = await flow.process_stage("preferences", PREFERENCES_INPUT)
        assert result["stage"] == "preferences"
        assert result["next_stage"] is None
        assert result["completed"] is True

    async def test_preferences_updates_state_to_completed(self, flow, ws):
        await flow.process_stage("background", BACKGROUND_INPUT)
        await flow.process_stage("projects", PROJECTS_INPUT)
        await flow.process_stage("preferences", PREFERENCES_INPUT)
        state = json.loads((ws / ".bootstrap_state.json").read_text())
        assert state["current_stage"] == "completed"
        assert state["completed_at"] is not None


# ---------------------------------------------------------------------------
# save_* 方法
# ---------------------------------------------------------------------------


class TestSaveUserProfile:
    def test_saves_all_fields(self, flow, ws):
        flow.save_user_profile(BACKGROUND_INPUT)
        text = (ws / "USER.md").read_text(encoding="utf-8")
        assert "Alice" in text
        assert "开发者" in text
        assert "高级" in text
        assert "Python, TypeScript" in text
        assert "AI 工程" in text

    def test_returns_path(self, flow, ws):
        p = flow.save_user_profile(BACKGROUND_INPUT)
        assert p == ws / "USER.md"
        assert p.exists()


class TestSaveProjectConfig:
    def test_saves_to_correct_path(self, flow, ws):
        p = flow.save_project_config("my-agent", PROJECTS_INPUT)
        assert p == ws / "memory" / "projects" / "my-agent" / "context.md"
        assert p.exists()

    def test_saves_fields(self, flow, ws):
        flow.save_project_config("my-agent", PROJECTS_INPUT)
        text = (ws / "memory" / "projects" / "my-agent" / "context.md").read_text()
        assert "自进化 AI 代理" in text
        assert "Python, Claude API" in text
        assert "开发" in text

    def test_creates_missing_directory(self, flow, ws):
        """项目目录不存在时自动创建。"""
        flow.save_project_config("brand-new-project", PROJECTS_INPUT)
        assert (ws / "memory" / "projects" / "brand-new-project" / "context.md").exists()


class TestSavePreferences:
    def test_saves_to_correct_path(self, flow, ws):
        p = flow.save_preferences(["response_style: 简洁", "language: 中文"])
        assert p == ws / "memory" / "user" / "preferences.md"

    def test_saves_all_preferences(self, flow, ws):
        prefs = ["response_style: 简洁", "language: 中文", "notification_level: normal"]
        flow.save_preferences(prefs)
        text = (ws / "memory" / "user" / "preferences.md").read_text()
        for pref in prefs:
            assert pref in text


# ---------------------------------------------------------------------------
# 完整三阶段流程
# ---------------------------------------------------------------------------


class TestFullFlow:
    async def test_full_three_stage_flow(self, flow, ws):
        """完整走完三阶段，最终 is_bootstrapped 返回 True。"""
        assert flow.is_bootstrapped() is False
        assert flow.get_current_stage() == "not_started"

        r1 = await flow.process_stage("background", BACKGROUND_INPUT)
        assert r1["completed"] is False
        assert r1["next_stage"] == "projects"

        r2 = await flow.process_stage("projects", PROJECTS_INPUT)
        assert r2["completed"] is False
        assert r2["next_stage"] == "preferences"

        r3 = await flow.process_stage("preferences", PREFERENCES_INPUT)
        assert r3["completed"] is True
        assert r3["next_stage"] is None

        assert flow.is_bootstrapped() is True
        assert flow.get_current_stage() == "completed"

    async def test_no_overwrite_on_re_run(self, flow, ws):
        """已完成引导后，再次调用 save_user_profile 不应清空 USER.md。"""
        # 完成一次引导
        await flow.process_stage("background", BACKGROUND_INPUT)

        original = (ws / "USER.md").read_text()
        assert original  # 非空

        # 再次保存相同内容
        flow.save_user_profile(BACKGROUND_INPUT)
        again = (ws / "USER.md").read_text()
        assert again  # 仍然非空
        assert "Alice" in again
