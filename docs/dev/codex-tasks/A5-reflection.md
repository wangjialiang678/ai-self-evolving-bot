# 任务 A5：反思引擎

> **优先级**: P1（信号系统和 Observer 依赖反思输出）
> **预计工作量**: 2-3 天
> **类型**: Python 模块开发（含 LLM 调用）

---

## 项目背景

你在参与一个「自进化 AI 智能体系统」的开发。每次任务完成后，反思引擎自动运行，用 Gemini Flash 提取一行教训。反思引擎区分两类信号：

- **真正错误（ERROR）**：有正确答案但做错了 → 深度处理，推送信号系统
- **偏好偏差（PREFERENCE）**：没有标准答案，只是不符合用户习惯 → 简单记录

详细背景见 `docs/design/v3-2-system-design.md` 第 5.5 节

---

## 你要做什么

实现 `ReflectionEngine` 类，提供轻量反思和结果写入功能。

---

## 接口定义

```python
# extensions/memory/reflection.py

import json
import logging
from pathlib import Path
from core.llm_client import BaseLLMClient

logger = logging.getLogger(__name__)


class ReflectionEngine:
    """
    任务后反思引擎。每次任务后用 Gemini Flash 提取教训。
    """

    def __init__(self, llm_client: BaseLLMClient, memory_dir: str):
        """
        Args:
            llm_client: LLM 客户端（测试时传 MockLLMClient）
            memory_dir: workspace/memory/ 路径
        """

    async def lightweight_reflect(self, task_trace: dict) -> dict:
        """
        轻量反思：分析一次任务，提取一行教训。

        Args:
            task_trace:
                {"task_id": "task_042",
                 "user_message": "...",
                 "system_response": "...",
                 "user_feedback": "..." | None,
                 "tools_used": [...],
                 "tokens_used": 3200,
                 "model": "opus",
                 "duration_ms": 15000}

        Returns:
            {"task_id": "task_042",
             "type": "ERROR" | "PREFERENCE" | "NONE",
             "outcome": "SUCCESS" | "PARTIAL" | "FAILURE",
             "lesson": "做了错误假设——以为用户要技术方案，实际要产品策略",
             "root_cause": "wrong_assumption" | "missed_consideration" |
                          "tool_misuse" | "knowledge_gap" | None,
             "reusable_experience": "..." | None}

        行为：
        1. 组装 prompt（见下方 Prompt 模板）
        2. 调用 LLM（model="gemini-flash"）
        3. 解析 LLM 返回的 JSON
        4. 如果解析失败，返回 type=NONE 的默认值
        5. 自动调用 write_reflection() 写入结果
        """

    def write_reflection(self, reflection: dict):
        """
        将反思结果写入对应文件。

        规则：
        - ERROR → 追加到 workspace/rules/experience/error_patterns.md
        - PREFERENCE → 追加到 workspace/memory/user/preferences.md
        - 所有类型 → 追加到 workspace/memory/user/reflections.jsonl
        """
```

---

## Prompt 模板

反思引擎调用 LLM 时使用以下 prompt：

**System Prompt:**
```
你是一个反思引擎。分析以下任务执行轨迹，提取教训。

请严格按以下 JSON 格式输出（不要添加任何其他文字）：
{
  "type": "ERROR 或 PREFERENCE 或 NONE",
  "outcome": "SUCCESS 或 PARTIAL 或 FAILURE",
  "lesson": "一句话总结教训",
  "root_cause": "wrong_assumption 或 missed_consideration 或 tool_misuse 或 knowledge_gap 或 null",
  "reusable_experience": "可复用的经验，或 null"
}

分类规则：
- ERROR: 有正确答案但做错了（错误假设、遗漏关键考虑、工具误用、知识不足）
- PREFERENCE: 没有标准答案，只是不符合用户习惯（回复太长、格式不合口味、语气偏差）
- NONE: 无异常

如果是 ERROR，必须填写 root_cause。
如果是 PREFERENCE 或 NONE，root_cause 填 null。
```

**User Message:**
```
任务ID: {task_id}
用户消息: {user_message}
系统回复: {system_response}（截取前500字）
用户反馈: {user_feedback 或 "无"}
使用工具: {tools_used}
消耗 token: {tokens_used}
耗时: {duration_ms}ms
```

---

## 技术约束

- Python 3.11+
- 依赖：`core.llm_client.BaseLLMClient`（已提供）
- LLM 调用使用 `model="gemini-flash"`
- 输出需解析为 JSON。如果 LLM 返回非 JSON，尝试提取 `{...}` 部分
- LLM 调用超时或失败 → 返回 `{"type": "NONE", "outcome": "SUCCESS", "lesson": "reflection_failed"}`
- system_response 截取前 500 字传给 LLM（控制 token）
- 写入文件使用追加模式

---

## 测试要求

```python
# tests/test_reflection.py

import pytest
import json
from pathlib import Path

# from extensions.memory.reflection import ReflectionEngine
# from core.llm_client import MockLLMClient


class TestReflectionEngine:
    @pytest.mark.asyncio
    async def test_classify_error(self, tmp_path):
        """正确分类为 ERROR。"""
        memory_dir = _setup_memory(tmp_path)
        llm = MockLLMClient(responses={
            "gemini-flash": json.dumps({
                "type": "ERROR", "outcome": "FAILURE",
                "lesson": "错误假设", "root_cause": "wrong_assumption",
                "reusable_experience": None,
            })
        })
        engine = ReflectionEngine(llm, str(memory_dir))

        trace = _make_trace(user_feedback="不对，用户在微信不是邮件")
        result = await engine.lightweight_reflect(trace)

        assert result["type"] == "ERROR"
        assert result["outcome"] == "FAILURE"
        assert result["root_cause"] == "wrong_assumption"

    @pytest.mark.asyncio
    async def test_classify_preference(self, tmp_path):
        """正确分类为 PREFERENCE。"""
        memory_dir = _setup_memory(tmp_path)
        llm = MockLLMClient(responses={
            "gemini-flash": json.dumps({
                "type": "PREFERENCE", "outcome": "PARTIAL",
                "lesson": "用户偏好简短", "root_cause": None,
                "reusable_experience": "分析类任务先给结论",
            })
        })
        engine = ReflectionEngine(llm, str(memory_dir))

        trace = _make_trace(user_feedback="太长了，只要结论")
        result = await engine.lightweight_reflect(trace)

        assert result["type"] == "PREFERENCE"
        assert result["root_cause"] is None

    @pytest.mark.asyncio
    async def test_classify_none(self, tmp_path):
        """无异常时分类为 NONE。"""
        memory_dir = _setup_memory(tmp_path)
        llm = MockLLMClient()  # 默认返回 NONE
        engine = ReflectionEngine(llm, str(memory_dir))

        trace = _make_trace(user_feedback=None)
        result = await engine.lightweight_reflect(trace)

        assert result["type"] == "NONE"

    @pytest.mark.asyncio
    async def test_write_error_to_log(self, tmp_path):
        """ERROR 写入 error_log.jsonl。"""
        memory_dir = _setup_memory(tmp_path)
        llm = MockLLMClient(responses={
            "gemini-flash": json.dumps({
                "type": "ERROR", "outcome": "FAILURE",
                "lesson": "test", "root_cause": "wrong_assumption",
                "reusable_experience": None,
            })
        })
        engine = ReflectionEngine(llm, str(memory_dir))

        trace = _make_trace()
        await engine.lightweight_reflect(trace)

        error_log = memory_dir / "user/error_log.jsonl"
        assert error_log.exists()
        lines = error_log.read_text().strip().split("\n")
        assert len(lines) >= 1

    @pytest.mark.asyncio
    async def test_write_preference_to_prefs(self, tmp_path):
        """PREFERENCE 写入 preferences.md。"""
        memory_dir = _setup_memory(tmp_path)
        llm = MockLLMClient(responses={
            "gemini-flash": json.dumps({
                "type": "PREFERENCE", "outcome": "PARTIAL",
                "lesson": "用户偏好简短", "root_cause": None,
                "reusable_experience": None,
            })
        })
        engine = ReflectionEngine(llm, str(memory_dir))

        trace = _make_trace()
        await engine.lightweight_reflect(trace)

        prefs = memory_dir / "user/preferences.md"
        assert prefs.exists()
        assert "用户偏好简短" in prefs.read_text()

    @pytest.mark.asyncio
    async def test_all_types_to_reflections_log(self, tmp_path):
        """所有类型都写入 reflections.jsonl。"""
        memory_dir = _setup_memory(tmp_path)
        llm = MockLLMClient()
        engine = ReflectionEngine(llm, str(memory_dir))

        await engine.lightweight_reflect(_make_trace())

        reflections = memory_dir / "user/reflections.jsonl"
        assert reflections.exists()

    @pytest.mark.asyncio
    async def test_llm_failure_returns_default(self, tmp_path):
        """LLM 返回非 JSON 时不崩溃。"""
        memory_dir = _setup_memory(tmp_path)
        llm = MockLLMClient(responses={"gemini-flash": "这不是JSON"})
        engine = ReflectionEngine(llm, str(memory_dir))

        trace = _make_trace()
        result = await engine.lightweight_reflect(trace)

        assert result["type"] == "NONE"

    @pytest.mark.asyncio
    async def test_prompt_includes_trace(self, tmp_path):
        """LLM 调用包含任务轨迹信息。"""
        memory_dir = _setup_memory(tmp_path)
        llm = MockLLMClient()
        engine = ReflectionEngine(llm, str(memory_dir))

        trace = _make_trace(user_message="分析竞品")
        await engine.lightweight_reflect(trace)

        assert len(llm.calls) == 1
        assert "分析竞品" in llm.calls[0]["user_message"]
        assert llm.calls[0]["model"] == "gemini-flash"


def _setup_memory(tmp_path):
    memory_dir = tmp_path / "memory"
    (memory_dir / "user").mkdir(parents=True)
    (memory_dir / "projects").mkdir(parents=True)
    return memory_dir


def _make_trace(task_id="task_042", user_message="帮我分析 Cursor",
                user_feedback="太长了"):
    return {
        "task_id": task_id,
        "user_message": user_message,
        "system_response": "Cursor 做对了以下几点：" + "x" * 600,
        "user_feedback": user_feedback,
        "tools_used": ["web_search"],
        "tokens_used": 3200,
        "model": "opus",
        "duration_ms": 15000,
    }
```

---

## 交付物

```
extensions/memory/reflection.py
extensions/memory/__init__.py     # 空文件（如不存在）
tests/test_reflection.py
```

---

## 验收标准

- [ ] lightweight_reflect 能正确分类 ERROR / PREFERENCE / NONE
- [ ] ERROR 类型包含 root_cause（4 种之一）
- [ ] PREFERENCE 和 NONE 的 root_cause 为 None
- [ ] write_reflection 将不同类型写入不同文件
- [ ] 所有反思结果写入 reflections.jsonl
- [ ] LLM 返回非 JSON 时优雅降级
- [ ] system_response 截取前 500 字传给 LLM
- [ ] Prompt 包含任务轨迹关键信息
- [ ] 以上测试全部通过

---

## 参考文档

- 反思引擎：`docs/design/v3-2-system-design.md` 第 5.5 节
- 模块计划：`docs/dev/mvp-module-plan.md` A5 节
- 接口规范：`docs/dev/mvp-dev-guide.md` 第 2 节（接口 I1、I2）
