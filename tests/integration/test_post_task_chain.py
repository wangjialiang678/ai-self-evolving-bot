"""联调测试：任务后处理链（反思 → 信号 → Observer → 指标）。"""

from __future__ import annotations

import json

import pytest

try:
    from core.llm_client import MockLLMClient
    from extensions.memory.reflection import ReflectionEngine
    from extensions.signals.store import SignalStore
    from extensions.signals.detector import SignalDetector
    from extensions.observer.engine import ObserverEngine
    from extensions.evolution.metrics import MetricsTracker
    _IMPORTS_OK = True
except Exception as _import_err:
    _IMPORTS_OK = False
    _import_err_msg = str(_import_err)

pytestmark = pytest.mark.skipif(
    not _IMPORTS_OK,
    reason=f"Import failed: {_import_err_msg if not _IMPORTS_OK else ''}",  # type: ignore[possibly-undefined]
)


# ---------------------------------------------------------------------------
# 联调 1: 反思 + 信号
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_reflection_generates_signal(workspace):
    """ERROR 反思 → 生成信号。"""
    llm = MockLLMClient(responses={
        "gemini-flash": json.dumps({
            "type": "ERROR", "outcome": "FAILURE",
            "lesson": "错误假设", "root_cause": "wrong_assumption",
            "reusable_experience": None,
        })
    })

    reflection = ReflectionEngine(llm, str(workspace / "memory"))
    store = SignalStore(str(workspace / "signals"))
    detector = SignalDetector(store)

    trace = {
        "task_id": "task_001",
        "user_message": "设计功能",
        "system_response": "方案...",
        "user_feedback": "不对",
        "tools_used": [],
        "tokens_used": 3000,
        "model": "opus",
        "duration_ms": 10000,
    }

    ref_output = await reflection.lightweight_reflect(trace)
    assert ref_output["type"] == "ERROR"

    task_context = {
        "task_id": "task_001",
        "user_corrections": 1,
        "tokens_used": 3000,
        "output_type": ref_output["type"],
        "outcome": ref_output["outcome"],
        "root_cause": ref_output.get("root_cause"),
        "rules_used": [],
    }
    signals = detector.detect(ref_output, task_context)
    assert len(signals) >= 1
    assert any(s["priority"] in ("HIGH", "MEDIUM") for s in signals)


@pytest.mark.asyncio
async def test_preference_low_priority_signal(workspace):
    """PREFERENCE 反思 → 低优先级信号或无信号。"""
    llm = MockLLMClient(responses={
        "gemini-flash": json.dumps({
            "type": "PREFERENCE", "outcome": "PARTIAL",
            "lesson": "用户偏好简短", "root_cause": None,
            "reusable_experience": "先给结论",
        })
    })

    reflection = ReflectionEngine(llm, str(workspace / "memory"))
    store = SignalStore(str(workspace / "signals"))
    detector = SignalDetector(store)

    trace = {
        "task_id": "task_002",
        "user_message": "分析竞品",
        "system_response": "很长的分析..." * 50,
        "user_feedback": "太长了",
        "tools_used": [],
        "tokens_used": 2000,
        "model": "qwen",
        "duration_ms": 5000,
    }

    ref_output = await reflection.lightweight_reflect(trace)
    assert ref_output["type"] == "PREFERENCE"

    task_context = {
        "task_id": "task_002",
        "user_corrections": 1,
        "tokens_used": 2000,
        "output_type": ref_output["type"],
        "outcome": ref_output["outcome"],
        "root_cause": ref_output.get("root_cause"),
        "rules_used": [],
    }
    signals = detector.detect(ref_output, task_context)
    # PREFERENCE 不应触发 CRITICAL 或 HIGH task_failure
    critical_signals = [s for s in signals if s["priority"] == "CRITICAL"]
    assert len(critical_signals) == 0


# ---------------------------------------------------------------------------
# 联调 2: 反思 + 信号 + 指标
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_full_post_task_records_metrics(workspace):
    """完整后处理链记录指标。"""
    llm = MockLLMClient(responses={
        "gemini-flash": json.dumps({
            "type": "ERROR", "outcome": "FAILURE",
            "lesson": "遗漏关键考虑", "root_cause": "missed_consideration",
            "reusable_experience": None,
        })
    })

    reflection = ReflectionEngine(llm, str(workspace / "memory"))
    store = SignalStore(str(workspace / "signals"))
    detector = SignalDetector(store)
    metrics = MetricsTracker(str(workspace / "metrics"))

    trace = {
        "task_id": "task_003",
        "user_message": "优化性能",
        "system_response": "优化方案...",
        "user_feedback": "漏了一个场景",
        "tools_used": [],
        "tokens_used": 4000,
        "model": "opus",
        "duration_ms": 12000,
    }

    # 执行反思
    ref_output = await reflection.lightweight_reflect(trace)
    assert ref_output["type"] == "ERROR"

    # 生成信号
    task_context = {
        "task_id": "task_003",
        "user_corrections": 1,
        "tokens_used": trace["tokens_used"],
        "output_type": ref_output["type"],
        "outcome": ref_output["outcome"],
        "root_cause": ref_output.get("root_cause"),
        "rules_used": [],
    }
    signals = detector.detect(ref_output, task_context)

    # 记录指标
    metrics.record_task(
        task_id=trace["task_id"],
        outcome=ref_output["outcome"],
        tokens=trace["tokens_used"],
        model=trace["model"],
        duration_ms=trace["duration_ms"],
        user_corrections=task_context["user_corrections"],
        error_type=ref_output.get("root_cause"),
    )
    for sig in signals:
        metrics.record_signal(
            signal_type=sig["signal_type"],
            priority=sig["priority"],
            source=sig.get("source", "detector"),
        )

    # 验证 events.jsonl 有记录
    events_file = workspace / "metrics" / "events.jsonl"
    assert events_file.exists()
    lines = [l for l in events_file.read_text(encoding="utf-8").splitlines() if l.strip()]
    assert len(lines) >= 1

    task_events = [json.loads(l) for l in lines if json.loads(l).get("event_type") == "task"]
    assert len(task_events) == 1
    assert task_events[0]["task_id"] == "task_003"
    assert task_events[0]["outcome"] == "FAILURE"


# ---------------------------------------------------------------------------
# 联调 3: 反思 + 信号 + Observer 轻量 + 指标
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_complete_post_task_pipeline(workspace):
    """完整任务后处理链。"""
    llm = MockLLMClient(responses={
        "gemini-flash": json.dumps({
            "type": "ERROR", "outcome": "FAILURE",
            "lesson": "工具误用", "root_cause": "tool_misuse",
            "reusable_experience": None,
        })
    })

    reflection = ReflectionEngine(llm, str(workspace / "memory"))
    store = SignalStore(str(workspace / "signals"))
    detector = SignalDetector(store)
    # Observer 使用同一个 mock llm（qwen 和 opus 都支持）
    observer = ObserverEngine(
        llm_client=llm,
        workspace_path=str(workspace),
    )
    metrics = MetricsTracker(str(workspace / "metrics"))

    trace = {
        "task_id": "task_004",
        "user_message": "调用 API",
        "system_response": "结果...",
        "user_feedback": "参数传错了",
        "tools_used": ["api_call"],
        "tokens_used": 2500,
        "model": "opus",
        "duration_ms": 8000,
    }

    # 步骤 1: 反思
    ref_output = await reflection.lightweight_reflect(trace)
    assert ref_output["type"] == "ERROR"

    # 步骤 2: 信号检测
    task_context = {
        "task_id": "task_004",
        "user_corrections": 1,
        "tokens_used": trace["tokens_used"],
        "output_type": ref_output["type"],
        "outcome": ref_output["outcome"],
        "root_cause": ref_output.get("root_cause"),
        "rules_used": [],
    }
    signals = detector.detect(ref_output, task_context)
    assert len(signals) >= 1

    # 步骤 3: Observer 轻量观察
    obs_output = await observer.lightweight_observe(trace, ref_output)
    assert "patterns_noticed" in obs_output
    assert "urgency" in obs_output
    assert obs_output["urgency"] in ("none", "low", "high")

    # 步骤 4: 指标记录
    metrics.record_task(
        task_id=trace["task_id"],
        outcome=ref_output["outcome"],
        tokens=trace["tokens_used"],
        model=trace["model"],
        duration_ms=trace["duration_ms"],
        user_corrections=1,
        error_type=ref_output.get("root_cause"),
    )

    # 验证各输出文件存在且非空
    # reflections.jsonl
    reflections_log = workspace / "memory" / "user" / "reflections.jsonl"
    assert reflections_log.exists()
    assert reflections_log.stat().st_size > 0

    # events.jsonl
    events_file = workspace / "metrics" / "events.jsonl"
    assert events_file.exists()
    lines = [l for l in events_file.read_text(encoding="utf-8").splitlines() if l.strip()]
    assert len(lines) >= 1

    # light_logs (当日)
    from datetime import date
    light_log_file = workspace / "observations" / "light_logs" / f"{date.today().isoformat()}.jsonl"
    assert light_log_file.exists()
    assert light_log_file.stat().st_size > 0
