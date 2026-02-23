"""Tests for A6 compaction engine."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from core.llm_client import MockLLMClient
from extensions.context.compaction import CompactionEngine


class TestCompactionEngine:
    def test_should_compact_threshold(self):
        """85% 阈值判断。"""
        engine = CompactionEngine(None, "/tmp")

        assert engine.should_compact(17000, 20000) is True  # 85%
        assert engine.should_compact(16000, 20000) is False  # 80%
        assert engine.should_compact(20000, 20000) is True  # 100%

    @pytest.mark.asyncio
    async def test_compact_preserves_recent(self, tmp_path):
        """保留最近 5 轮对话。"""
        memory_dir = _setup_memory(tmp_path)
        llm = MockLLMClient(
            responses={
                "gemini-flash": "这是压缩后的摘要。用户在讨论项目架构。",
            }
        )
        engine = CompactionEngine(llm, str(memory_dir))

        history = _make_long_history(20)  # 20 轮对话
        result = await engine.compact(history, keep_recent=5)

        # 最近 5 轮 = 10 条消息，加上摘要消息，不超过 11。
        assert len(result["compacted_history"]) <= 11
        assert result["compacted_history"][0].get("type") == "summary"

    @pytest.mark.asyncio
    async def test_compact_has_summary(self, tmp_path):
        """压缩结果包含摘要。"""
        memory_dir = _setup_memory(tmp_path)
        llm = MockLLMClient(
            responses={
                "gemini-flash": "项目讨论摘要",
            }
        )
        engine = CompactionEngine(llm, str(memory_dir))

        history = _make_long_history(20)
        result = await engine.compact(history, keep_recent=5)

        assert result["summary"] != ""
        assert result["compression_ratio"] < 1.0
        assert "compressed_history" in result
        assert "stats" in result
        assert result["stats"]["compression_ratio"] == result["compression_ratio"]

    @pytest.mark.asyncio
    async def test_compact_short_history_no_op(self, tmp_path):
        """短对话不需要压缩。"""
        memory_dir = _setup_memory(tmp_path)
        llm = MockLLMClient()
        engine = CompactionEngine(llm, str(memory_dir))

        history = _make_long_history(3)  # 只有 3 轮
        result = await engine.compact(history, keep_recent=5)

        assert result["compacted_history"] == history
        assert result["summary"] == ""

    @pytest.mark.asyncio
    async def test_flush_writes_to_memory(self, tmp_path):
        """Pre-Compaction Flush 写入记忆。"""
        memory_dir = _setup_memory(tmp_path)
        llm = MockLLMClient(
            responses={
                "gemini-flash": json.dumps(
                    [
                        {"type": "decision", "content": "使用 React"},
                        {"type": "preference", "content": "简短回答"},
                    ]
                ),
            }
        )
        engine = CompactionEngine(llm, str(memory_dir))

        history = _make_long_history(20)
        result = await engine.compact(history, keep_recent=5)

        assert len(result["flushed_to_memory"]) >= 1
        flush_file = memory_dir / "user/compaction_flush.jsonl"
        assert flush_file.exists()

    @pytest.mark.asyncio
    async def test_flush_parse_failure_returns_empty(self, tmp_path):
        """flush 提取失败时返回空列表而不崩溃。"""
        memory_dir = _setup_memory(tmp_path)
        llm = MockLLMClient(
            responses={
                "gemini-flash": "not json",
            }
        )
        engine = CompactionEngine(llm, str(memory_dir))

        history = _make_long_history(20)
        result = await engine.compact(history, keep_recent=5)
        assert result["flushed_to_memory"] == []


def _setup_memory(tmp_path: Path) -> Path:
    memory_dir = tmp_path / "memory"
    (memory_dir / "user").mkdir(parents=True)
    return memory_dir


def _make_long_history(rounds: int) -> list[dict]:
    """生成 N 轮对话历史。"""
    history = []
    for i in range(rounds):
        history.append(
            {
                "role": "user",
                "content": f"第{i + 1}轮用户消息：请帮我分析问题{i + 1}",
                "timestamp": f"2026-02-25T{10 + i // 6:02d}:{(i % 6) * 10:02d}:00",
            }
        )
        history.append(
            {
                "role": "assistant",
                "content": (
                    f"第{i + 1}轮助手回复：关于问题{i + 1}的分析结果是..."
                    + "详细内容" * 20
                ),
                "timestamp": f"2026-02-25T{10 + i // 6:02d}:{(i % 6) * 10 + 5:02d}:00",
            }
        )
    return history
