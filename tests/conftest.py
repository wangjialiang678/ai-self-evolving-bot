"""共用 test fixtures — 所有模块测试共享。"""

import json
import pytest
from pathlib import Path


@pytest.fixture
def workspace(tmp_path):
    """创建标准的 workspace 目录结构。"""
    dirs = [
        "rules/constitution", "rules/experience",
        "memory/user", "memory/projects", "memory/conversations",
        "memory/daily_summaries",
        "skills/learned", "skills/seed",
        "observations/light_logs", "observations/deep_reports",
        "signals", "architect/proposals", "architect/modifications",
        "backups", "metrics/daily", "logs",
    ]
    for d in dirs:
        (tmp_path / d).mkdir(parents=True)

    # 初始化空文件
    (tmp_path / "signals/active.jsonl").touch()
    (tmp_path / "signals/archive.jsonl").touch()
    (tmp_path / "metrics/events.jsonl").touch()
    (tmp_path / "architect/big_picture.md").write_text("# Big Picture\n")

    return tmp_path


@pytest.fixture
def mock_llm():
    """Mock LLM 客户端工厂。"""
    from core.llm_client import MockLLMClient
    return MockLLMClient


@pytest.fixture
def sample_task_trace():
    """标准的任务轨迹样本。"""
    return {
        "task_id": "task_042",
        "timestamp": "2026-02-25T10:15:30",
        "user_message": "帮我分析 Cursor 做对了什么",
        "system_response": "Cursor 做对了以下几点：1. xxx 2. xxx 3. xxx...",
        "user_feedback": "太长了，只要结论",
        "tools_used": ["web_search"],
        "tokens_used": 3200,
        "model": "opus",
        "duration_ms": 15000,
    }


@pytest.fixture
def sample_reflection_output():
    """标准的反思输出样本。"""
    return {
        "task_id": "task_042",
        "type": "PREFERENCE",
        "outcome": "PARTIAL",
        "lesson": "用户偏好简短结论，不要展开论述",
        "root_cause": None,
        "reusable_experience": "分析类任务先给结论再展开",
    }


@pytest.fixture
def sample_signal():
    """标准的信号样本。"""
    return {
        "signal_id": "sig_001",
        "signal_type": "user_correction",
        "priority": "MEDIUM",
        "source": "reflection:task_042",
        "description": "用户纠正了分析长度偏好",
        "related_tasks": ["task_042"],
        "timestamp": "2026-02-25T10:16:00",
        "status": "active",
    }
