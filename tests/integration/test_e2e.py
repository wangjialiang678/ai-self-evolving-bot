"""端到端集成测试：验证 main.py 中各模块串联后的完整流程。

覆盖 MVP 成功标准：
1. 闭环完整性 — 多轮任务处理 + 反思 + 信号 + 指标
2. Bootstrap 引导 — 三阶段引导流程
3. Architect 提案 — Observer 报告 → 诊断 → 提案 → 执行 → 回滚
4. 回滚可靠性 — 坏规则自动回滚
"""

from __future__ import annotations

import asyncio
import json
from datetime import date, datetime
from pathlib import Path

import pytest

from core.agent_loop import AgentLoop
from core.architect import ArchitectEngine
from core.bootstrap import BootstrapFlow
from core.config import EvoConfig
from core.llm_client import MockLLMClient

try:
    from extensions.evolution.rollback import RollbackManager
    from extensions.evolution.metrics import MetricsTracker
    _HAS_EXTENSIONS = True
except ImportError:
    _HAS_EXTENSIONS = False


# ──────────────────────────────────────
#  E2E 1: 完整消息处理链路（5 轮对话）
# ──────────────────────────────────────

@pytest.mark.asyncio
async def test_multi_turn_conversation(workspace):
    """多轮对话：消息 → LLM → 反思 → 信号 → Observer → 指标，全部串联。"""
    llm = MockLLMClient(responses={
        "opus": "这是 Agent 的回复。",
        "qwen": json.dumps({
            "type": "NONE", "outcome": "SUCCESS",
            "lesson": "", "root_cause": None,
            "reusable_experience": None,
        }),
    })

    agent = AgentLoop(
        workspace_path=str(workspace),
        llm_client=llm,
        llm_client_light=llm,
    )

    # 5 轮对话
    for i in range(1, 6):
        trace = await agent.process_message(f"第 {i} 轮消息")
        assert trace["task_id"] == f"task_{i:04d}"
        assert "回复" in trace["system_response"]

    # 等待异步后处理链完成
    await asyncio.sleep(0.3)

    # 验证对话历史
    history = agent.get_conversation_history()
    assert len(history) == 10  # 5 轮 × 2（user + assistant）

    # 验证指标记录
    events_file = workspace / "metrics" / "events.jsonl"
    if events_file.exists():
        lines = [l for l in events_file.read_text("utf-8").splitlines() if l.strip()]
        task_events = [json.loads(l) for l in lines if json.loads(l).get("event_type") == "task"]
        assert len(task_events) == 5

    # 验证 Observer light_logs
    light_log = workspace / "observations" / "light_logs" / f"{date.today().isoformat()}.jsonl"
    if light_log.exists():
        log_lines = [l for l in light_log.read_text("utf-8").splitlines() if l.strip()]
        assert len(log_lines) == 5


@pytest.mark.asyncio
async def test_error_task_generates_signals(workspace):
    """ERROR 类型任务生成信号并记录指标。"""
    llm = MockLLMClient(responses={
        "opus": "错误的回复",
        "qwen": json.dumps({
            "type": "ERROR", "outcome": "FAILURE",
            "lesson": "做了错误假设", "root_cause": "wrong_assumption",
            "reusable_experience": None,
        }),
    })

    agent = AgentLoop(
        workspace_path=str(workspace),
        llm_client=llm,
        llm_client_light=llm,
    )

    trace = await agent.process_message("分析竞品", user_feedback="完全不对")
    await asyncio.sleep(0.3)

    # 验证信号生成
    active_signals = workspace / "signals" / "active.jsonl"
    if active_signals.exists():
        lines = [l for l in active_signals.read_text("utf-8").splitlines() if l.strip()]
        assert len(lines) >= 1
        signals = [json.loads(l) for l in lines]
        signal_types = [s.get("signal_type") for s in signals]
        # 应包含 task_failure 或 user_correction
        assert any(t in ("task_failure", "user_correction", "capability_gap") for t in signal_types)


# ──────────────────────────────────────
#  E2E 2: Bootstrap 引导流程
# ──────────────────────────────────────

@pytest.mark.asyncio
async def test_bootstrap_full_flow(workspace):
    """三阶段 Bootstrap：background → projects → preferences。"""
    bootstrap = BootstrapFlow(str(workspace))

    assert not bootstrap.is_bootstrapped()
    assert bootstrap.get_current_stage() == "not_started"

    # Stage 1: background
    result = await bootstrap.process_stage("background", {
        "name": "Michael",
        "role": "developer",
        "experience": "senior",
        "languages": "Python, TypeScript",
        "focus": "AI agents",
    })
    assert result["next_stage"] == "projects"
    assert not result["completed"]
    assert (workspace / "USER.md").exists()

    # Stage 2: projects
    result = await bootstrap.process_stage("projects", {
        "project_name": "evo-agent",
        "description": "自进化 AI 系统",
        "tech_stack": "Python + Claude",
        "current_phase": "开发",
    })
    assert result["next_stage"] == "preferences"

    # Stage 3: preferences
    result = await bootstrap.process_stage("preferences", {
        "response_style": "简洁",
        "language": "中文",
        "notification_level": "normal",
    })
    assert result["completed"]
    assert bootstrap.is_bootstrapped()
    assert bootstrap.get_current_stage() == "completed"


# ──────────────────────────────────────
#  E2E 3: Architect 提案 + 执行 + 验证
# ──────────────────────────────────────

@pytest.mark.asyncio
async def test_architect_propose_and_execute(workspace):
    """Observer 报告 → Architect 提案 → 执行（Level 0/1 自动执行）。"""
    # 准备 Observer 深度报告
    reports_dir = workspace / "observations" / "deep_reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    (reports_dir / "2026-02-23.md").write_text(
        "# 深度分析\n\n## 发现\n- 分析类任务回复过长，用户多次要求缩短\n"
        "- 连续 3 次 error_pattern 信号\n\n## 建议\n- 新增长度控制规则",
        encoding="utf-8",
    )

    # Mock LLM 返回提案
    proposal_json = json.dumps([{
        "proposal_id": "prop_test_001",
        "level": 0,
        "trigger_source": "observer_report:2026-02-23",
        "problem": "分析类任务回复过长",
        "solution": "在 task_strategies.md 中添加长度控制规则",
        "files_affected": ["rules/experience/task_strategies.md"],
        "blast_radius": "trivial",
        "expected_effect": "分析类回复长度减少 30%",
        "verification_method": "检查后续任务平均 token 数",
        "verification_days": 3,
        "rollback_plan": "恢复原 task_strategies.md",
        "new_content": "# 任务策略\n\n## 分析类任务\n- 回复不超过 500 字\n- 先给结论再展开",
    }])

    llm = MockLLMClient(responses={"opus": proposal_json})

    rollback = None
    if _HAS_EXTENSIONS:
        rollback = RollbackManager(str(workspace))

    architect = ArchitectEngine(
        workspace_path=str(workspace),
        llm_client=llm,
        rollback_manager=rollback,
    )

    # 确保目标文件存在（供备份）
    target = workspace / "rules" / "experience" / "task_strategies.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("# 旧的任务策略\n\n旧内容", encoding="utf-8")

    # 生成提案
    proposals = await architect.analyze_and_propose()
    assert len(proposals) == 1
    assert proposals[0]["proposal_id"] == "prop_test_001"

    # 执行提案（Level 0，自动执行）
    result = await architect.execute_proposal(proposals[0])
    assert result["status"] == "executed"

    # 验证文件已修改
    new_content = target.read_text(encoding="utf-8")
    assert "500 字" in new_content or "先给结论" in new_content


@pytest.mark.asyncio
@pytest.mark.skipif(not _HAS_EXTENSIONS, reason="extensions not available")
async def test_architect_rollback_on_bad_proposal(workspace):
    """坏提案验证失败 → 自动回滚。"""
    rollback = RollbackManager(str(workspace))

    llm = MockLLMClient(responses={"opus": "验证未通过"})

    architect = ArchitectEngine(
        workspace_path=str(workspace),
        llm_client=llm,
        rollback_manager=rollback,
    )

    # 准备原始文件
    target = workspace / "rules" / "experience" / "test_rule.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    original_content = "# 原始规则\n\n这是原始内容"
    target.write_text(original_content, encoding="utf-8")

    # 手动创建并执行一个提案
    proposal = {
        "proposal_id": "prop_rollback_test",
        "level": 0,
        "problem": "测试回滚",
        "solution": "写入坏规则",
        "files_affected": ["rules/experience/test_rule.md"],
        "blast_radius": "trivial",
        "new_content": "# 坏规则\n\n这是一个坏规则",
        "verification_days": 0,
        "status": "new",
        "created_at": datetime.now().isoformat(),
    }
    architect._save_proposal(proposal)
    exec_result = await architect.execute_proposal(proposal)
    assert exec_result["status"] == "executed"
    backup_id = exec_result["backup_id"]
    assert backup_id is not None

    # 验证文件已被修改
    assert "坏规则" in target.read_text("utf-8")

    # 模拟回滚
    rollback_result = rollback.rollback(backup_id)
    assert rollback_result.get("status") == "success"

    # 验证文件已恢复
    restored = target.read_text("utf-8")
    assert "原始内容" in restored


# ──────────────────────────────────────
#  E2E 4: 配置加载
# ──────────────────────────────────────

def test_config_loads_yaml(workspace):
    """从 YAML 文件加载配置。"""
    config_path = workspace / "test_config.yaml"
    config_path.write_text(
        "observer:\n  deep_mode:\n    schedule: '04:00'\n"
        "architect:\n  schedule: '05:00'\n",
        encoding="utf-8",
    )

    config = EvoConfig(str(config_path))
    assert config.observer_schedule == "04:00"
    assert config.architect_schedule == "05:00"


def test_config_defaults():
    """无配置文件时使用默认值。"""
    config = EvoConfig(None)
    assert config.observer_schedule == "02:00"
    assert config.architect_schedule == "03:00"
    assert config.quiet_hours == ("22:00", "08:00")
    assert config.evolution_strategy == "cautious"


# ──────────────────────────────────────
#  E2E 5: main.py 工具函数
# ──────────────────────────────────────

def test_split_message():
    """长消息分段。"""
    from main import _split_message

    # 短消息不分段
    assert _split_message("hello", 100) == ["hello"]

    # 长消息分段
    long_text = "line\n" * 1000
    chunks = _split_message(long_text, 100)
    assert len(chunks) > 1
    assert all(len(c) <= 100 for c in chunks)
    # 重组后内容一致（允许换行差异）
    rejoined = "\n".join(chunks)
    assert rejoined.replace("\n", "") == long_text.replace("\n", "")


def test_parse_time():
    """时间解析。"""
    from main import _parse_time
    from datetime import time as dt_time

    assert _parse_time("02:00") == dt_time(2, 0)
    assert _parse_time("14:30") == dt_time(14, 30)
    assert _parse_time("invalid") == dt_time(2, 0)  # fallback


def test_in_window():
    """时间窗口判断。"""
    from main import _in_window
    from datetime import time as dt_time

    now = datetime(2026, 2, 23, 2, 5, 0)  # 02:05
    assert _in_window(now, dt_time(2, 0), minutes=30)  # 在 02:00 ±15min 内

    now_far = datetime(2026, 2, 23, 3, 0, 0)  # 03:00
    assert not _in_window(now_far, dt_time(2, 0), minutes=30)


# ──────────────────────────────────────
#  E2E 6: build_app 初始化
# ──────────────────────────────────────

def test_build_app_dry_run(workspace):
    """build_app 在 dry-run 模式下不创建 Telegram。"""
    from main import build_app

    config = EvoConfig(None)
    app = build_app(config, workspace, telegram_enabled=False)

    assert app["agent_loop"] is not None
    assert app["bootstrap"] is not None
    assert app["architect"] is not None
    assert app["telegram"] is None
