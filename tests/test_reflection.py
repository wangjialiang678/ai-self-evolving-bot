"""Tests for A5 reflection engine."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from core.llm_client import MockLLMClient
from extensions.memory.reflection import ReflectionEngine


class TestReflectionEngine:
    @pytest.mark.asyncio
    async def test_classify_error(self, tmp_path):
        """正确分类为 ERROR。"""
        memory_dir = _setup_memory(tmp_path)
        llm = MockLLMClient(
            responses={
                "gemini-flash": json.dumps(
                    {
                        "type": "ERROR",
                        "outcome": "FAILURE",
                        "lesson": "错误假设",
                        "root_cause": "wrong_assumption",
                        "reusable_experience": None,
                    }
                )
            }
        )
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
        llm = MockLLMClient(
            responses={
                "gemini-flash": json.dumps(
                    {
                        "type": "PREFERENCE",
                        "outcome": "PARTIAL",
                        "lesson": "用户偏好简短",
                        "root_cause": None,
                        "reusable_experience": "分析类任务先给结论",
                    }
                )
            }
        )
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
        llm = MockLLMClient(
            responses={
                "gemini-flash": json.dumps(
                    {
                        "type": "ERROR",
                        "outcome": "FAILURE",
                        "lesson": "test",
                        "root_cause": "wrong_assumption",
                        "reusable_experience": None,
                    }
                )
            }
        )
        engine = ReflectionEngine(llm, str(memory_dir))

        trace = _make_trace()
        await engine.lightweight_reflect(trace)

        error_log = memory_dir / "user/error_log.jsonl"
        assert error_log.exists()
        lines = error_log.read_text(encoding="utf-8").strip().split("\n")
        assert len(lines) >= 1

        patterns = memory_dir.parent / "rules/experience/error_patterns.md"
        assert patterns.exists()
        assert "test" in patterns.read_text(encoding="utf-8")

    @pytest.mark.asyncio
    async def test_write_preference_to_prefs(self, tmp_path):
        """PREFERENCE 写入 preferences.md。"""
        memory_dir = _setup_memory(tmp_path)
        llm = MockLLMClient(
            responses={
                "gemini-flash": json.dumps(
                    {
                        "type": "PREFERENCE",
                        "outcome": "PARTIAL",
                        "lesson": "用户偏好简短",
                        "root_cause": None,
                        "reusable_experience": None,
                    }
                )
            }
        )
        engine = ReflectionEngine(llm, str(memory_dir))

        trace = _make_trace()
        await engine.lightweight_reflect(trace)

        prefs = memory_dir / "user/preferences.md"
        assert prefs.exists()
        assert "用户偏好简短" in prefs.read_text(encoding="utf-8")

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
        assert result["lesson"] == "reflection_failed"

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
        # system_response 应截断到前 500 字
        assert "x" * 550 not in llm.calls[0]["user_message"]


def _setup_memory(tmp_path: Path) -> Path:
    memory_dir = tmp_path / "memory"
    (memory_dir / "user").mkdir(parents=True)
    (memory_dir / "projects").mkdir(parents=True)
    return memory_dir


def _make_trace(task_id: str = "task_042", user_message: str = "帮我分析 Cursor", user_feedback: str | None = "太长了"):
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
