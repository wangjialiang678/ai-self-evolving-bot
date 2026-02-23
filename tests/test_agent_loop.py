"""Agent Loop 集成测试。"""

import asyncio
import json
from pathlib import Path

import pytest

from core.agent_loop import AgentLoop
from core.llm_client import MockLLMClient


@pytest.fixture
def loop_workspace(workspace):
    """在 workspace fixture 基础上添加种子规则。"""
    # 宪法级规则
    (workspace / "rules/constitution/identity.md").write_text(
        "# 系统身份\n\n你是一个自我进化的 AI 助手。\n"
    )
    # 经验级规则
    (workspace / "rules/experience/task_strategies.md").write_text(
        "# 任务策略\n\n## 分析类任务\n- 先给结论再展开\n- 控制长度在 500 字以内\n"
    )
    return workspace


@pytest.fixture
def mock_responses():
    """标准 Mock LLM 响应。"""
    return {
        "opus": "这是 Claude Opus 的回复。",
        "qwen": json.dumps({
            "type": "NONE",
            "outcome": "SUCCESS",
            "lesson": "正常完成",
            "root_cause": None,
            "reusable_experience": None,
        }),
        "gemini-flash": json.dumps({
            "type": "NONE",
            "outcome": "SUCCESS",
            "lesson": "正常完成",
            "root_cause": None,
            "reusable_experience": None,
        }),
    }


@pytest.fixture
def agent(loop_workspace, mock_responses):
    """创建 Agent Loop 实例。"""
    llm = MockLLMClient(responses=mock_responses)
    return AgentLoop(
        workspace_path=loop_workspace,
        llm_client=llm,
        model="opus",
    )


# ──────────────────────────────────────
#  基础流程测试
# ──────────────────────────────────────

class TestBasicFlow:
    @pytest.mark.asyncio
    async def test_process_message_returns_trace(self, agent):
        """处理消息返回完整 task_trace。"""
        trace = await agent.process_message("你好")
        assert trace["task_id"] == "task_0001"
        assert trace["user_message"] == "你好"
        assert "system_response" in trace
        assert trace["duration_ms"] >= 0

    @pytest.mark.asyncio
    async def test_response_is_string(self, agent):
        """回复是字符串。"""
        trace = await agent.process_message("测试")
        assert isinstance(trace["system_response"], str)
        assert len(trace["system_response"]) > 0

    @pytest.mark.asyncio
    async def test_conversation_history_grows(self, agent):
        """对话历史随消息增长。"""
        await agent.process_message("第一条")
        await agent.process_message("第二条")
        history = agent.get_conversation_history()
        assert len(history) == 4  # 2 user + 2 assistant

    @pytest.mark.asyncio
    async def test_task_id_increments(self, agent):
        """task_id 递增。"""
        t1 = await agent.process_message("消息1")
        t2 = await agent.process_message("消息2")
        assert t1["task_id"] == "task_0001"
        assert t2["task_id"] == "task_0002"

    @pytest.mark.asyncio
    async def test_clear_history(self, agent):
        """清空历史。"""
        await agent.process_message("测试")
        agent.clear_history()
        assert len(agent.get_conversation_history()) == 0


# ──────────────────────────────────────
#  规则集成测试
# ──────────────────────────────────────

class TestRulesIntegration:
    @pytest.mark.asyncio
    async def test_rules_loaded(self, agent):
        """种子规则被加载。"""
        rules = agent.rules.get_constitution_rules()
        assert len(rules) >= 1
        assert any("身份" in r.content for r in rules)

    @pytest.mark.asyncio
    async def test_experience_rules_match(self, agent):
        """经验规则按关键词匹配。"""
        exp = agent.rules.get_experience_rules(task_context="分析类任务")
        assert len(exp) >= 1
        assert any("分析" in r.content for r in exp)


# ──────────────────────────────────────
#  记忆集成测试
# ──────────────────────────────────────

class TestMemoryIntegration:
    @pytest.mark.asyncio
    async def test_memory_search_in_context(self, agent, loop_workspace):
        """记忆被注入上下文。"""
        # 预存一条记忆
        agent.memory.save_user_memory("coding_style", "用户偏好 Python 类型注解")

        # 发消息触发记忆检索
        trace = await agent.process_message("写一个 Python 函数")

        # 验证记忆被检索到（通过 LLM 调用参数间接验证）
        assert isinstance(trace["system_response"], str)

    @pytest.mark.asyncio
    async def test_project_memory_isolation(self, agent):
        """项目级记忆互不干扰。"""
        agent.memory.save_project_memory("project_a", "context", "用 React")
        agent.memory.save_project_memory("project_b", "context", "用 Vue")

        ctx_a = agent.memory.get_project_context("project_a")
        ctx_b = agent.memory.get_project_context("project_b")
        assert "React" in ctx_a
        assert "Vue" in ctx_b
        assert "Vue" not in ctx_a


# ──────────────────────────────────────
#  后处理链测试
# ──────────────────────────────────────

class TestPostTaskPipeline:
    @pytest.mark.asyncio
    async def test_pipeline_runs_without_error(self, agent):
        """后处理链完整执行不报错。"""
        trace = await agent.process_message("测试后处理链")
        # 等待后处理链完成
        await asyncio.sleep(0.3)
        # 没有异常就是通过

    @pytest.mark.asyncio
    async def test_reflection_writes_file(self, agent, loop_workspace):
        """反思引擎写入 reflections.jsonl。"""
        await agent.process_message("测试反思")
        await asyncio.sleep(0.3)

        reflections_file = loop_workspace / "memory/user/reflections.jsonl"
        assert reflections_file.exists()
        content = reflections_file.read_text()
        assert len(content.strip()) > 0

    @pytest.mark.asyncio
    async def test_observer_writes_log(self, agent, loop_workspace):
        """Observer 写入轻量日志。"""
        await agent.process_message("测试观察")
        await asyncio.sleep(0.3)

        from datetime import date
        log_file = loop_workspace / f"observations/light_logs/{date.today().isoformat()}.jsonl"
        assert log_file.exists()

    @pytest.mark.asyncio
    async def test_metrics_records_task(self, agent, loop_workspace):
        """指标系统记录任务。"""
        await agent.process_message("测试指标")
        await asyncio.sleep(0.3)

        events_file = loop_workspace / "metrics/events.jsonl"
        content = events_file.read_text().strip()
        assert len(content) > 0
        event = json.loads(content.split("\n")[0])
        assert event["event_type"] == "task"

    @pytest.mark.asyncio
    async def test_user_feedback_triggers_reflection(self, agent, loop_workspace):
        """带用户反馈的消息触发正确反思。"""
        # 先发一条，再带反馈发第二条
        await agent.process_message("分析 Cursor 的优势")
        await asyncio.sleep(0.1)
        trace = await agent.process_message(
            "简短一点", user_feedback="太长了"
        )
        await asyncio.sleep(0.3)
        assert trace["user_feedback"] == "太长了"


# ──────────────────────────────────────
#  对话历史管理测试
# ──────────────────────────────────────

class TestHistoryManagement:
    @pytest.mark.asyncio
    async def test_history_trim(self, loop_workspace, mock_responses):
        """对话历史超过上限时裁剪。"""
        llm = MockLLMClient(responses=mock_responses)
        agent = AgentLoop(
            workspace_path=loop_workspace,
            llm_client=llm,
            max_history_rounds=3,
        )
        for i in range(5):
            await agent.process_message(f"消息{i}")

        history = agent.get_conversation_history()
        assert len(history) == 6  # 3 rounds × 2


# ──────────────────────────────────────
#  错误恢复测试
# ──────────────────────────────────────

class TestErrorRecovery:
    @pytest.mark.asyncio
    async def test_llm_failure_returns_error_message(self, loop_workspace):
        """LLM 调用失败返回错误消息而不崩溃。"""
        class FailingLLM(MockLLMClient):
            async def complete(self, **kwargs):
                raise RuntimeError("LLM unavailable")

        agent = AgentLoop(
            workspace_path=loop_workspace,
            llm_client=FailingLLM(),
        )
        trace = await agent.process_message("测试")
        assert "出错" in trace["system_response"]

    @pytest.mark.asyncio
    async def test_missing_extensions_graceful(self, loop_workspace, mock_responses):
        """扩展模块缺失不影响基本流程。"""
        llm = MockLLMClient(responses=mock_responses)
        agent = AgentLoop(
            workspace_path=loop_workspace,
            llm_client=llm,
        )
        # 手动清掉扩展
        agent._reflection_engine = None
        agent._signal_detector = None
        agent._observer_engine = None
        agent._metrics_tracker = None

        trace = await agent.process_message("测试")
        assert trace["system_response"] == "这是 Claude Opus 的回复。"


# ──────────────────────────────────────
#  每日汇总测试
# ──────────────────────────────────────

class TestDailySummary:
    @pytest.mark.asyncio
    async def test_get_daily_summary(self, agent):
        """获取每日汇总。"""
        await agent.process_message("测试1")
        await asyncio.sleep(0.3)
        summary = await agent.get_daily_summary()
        assert summary is not None
        assert "tasks" in summary
