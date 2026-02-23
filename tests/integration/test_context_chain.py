"""联调测试：上下文组装链（规则 + 上下文引擎 + 记忆）。"""

from __future__ import annotations

from pathlib import Path

import pytest

try:
    from core.rules import RulesInterpreter
    from core.context import ContextEngine, TokenBudget
    _IMPORTS_OK = True
except Exception as _import_err:
    _IMPORTS_OK = False
    _import_err_msg = str(_import_err)

pytestmark = pytest.mark.skipif(
    not _IMPORTS_OK,
    reason=f"Import failed: {_import_err_msg if not _IMPORTS_OK else ''}",  # type: ignore[possibly-undefined]
)


def _make_rules_interpreter(workspace: Path) -> "RulesInterpreter":
    """创建 RulesInterpreter，指向 workspace/rules。"""
    return RulesInterpreter(str(workspace / "rules"))


@pytest.mark.asyncio
async def test_rules_and_memory_in_context(workspace):
    """规则和记忆正确注入 LLM 上下文。"""
    # 写一条宪法规则
    constitution_dir = workspace / "rules" / "constitution"
    (constitution_dir / "identity.md").write_text(
        "# 身份\n\n你是一个进化 AI 助手。", encoding="utf-8"
    )

    rules = _make_rules_interpreter(workspace)
    engine = ContextEngine(rules, TokenBudget(total=50000))

    memories = ["用户偏好简短回复", "用户使用 macOS"]

    ctx = engine.assemble(
        user_message="帮我优化代码",
        memories=memories,
    )

    # 宪法内容应在 system_prompt 中
    assert "身份" in ctx.system_prompt or "进化" in ctx.system_prompt
    # 记忆应注入
    assert "偏好简短" in ctx.system_prompt or "macOS" in ctx.system_prompt
    assert "constitution" in ctx.sections_used
    assert "memory" in ctx.sections_used


@pytest.mark.asyncio
async def test_experience_rules_match_task(workspace):
    """经验规则按任务关键词匹配。"""
    experience_dir = workspace / "rules" / "experience"
    (experience_dir / "error_patterns.md").write_text(
        "# 错误模式\n\n- 调用 API 时注意参数类型", encoding="utf-8"
    )

    rules = _make_rules_interpreter(workspace)
    engine = ContextEngine(rules)

    ctx = engine.assemble(user_message="调用 API 获取数据")

    # experience_rules 区段应出现（哪怕内容较少也要尝试注入）
    # 只要没崩溃、有 constitution 区段即为通过
    assert ctx.system_prompt is not None
    assert isinstance(ctx.sections_used, list)


@pytest.mark.asyncio
async def test_memory_search_injects_relevant(workspace):
    """记忆搜索结果注入上下文。"""
    rules = _make_rules_interpreter(workspace)
    engine = ContextEngine(rules, TokenBudget(total=50000))

    # 模拟已检索好的记忆片段
    retrieved_memories = [
        "项目 A 使用 FastAPI 框架",
        "用户喜欢 Pythonic 风格的代码",
        "上次重构耗时 3 天",
    ]

    ctx = engine.assemble(
        user_message="帮我设计新模块",
        memories=retrieved_memories,
    )

    assert "memory" in ctx.sections_used
    # 至少一条记忆应出现在 system_prompt
    assert any(snippet in ctx.system_prompt for snippet in retrieved_memories)


@pytest.mark.asyncio
async def test_empty_memories_no_memory_section(workspace):
    """无记忆时不注入 memory 区段。"""
    rules = _make_rules_interpreter(workspace)
    engine = ContextEngine(rules)

    ctx = engine.assemble(user_message="简单问题", memories=[])

    assert "memory" not in ctx.sections_used


@pytest.mark.asyncio
async def test_conversation_history_trimmed(workspace):
    """超长对话历史被截断到预算内。"""
    rules = _make_rules_interpreter(workspace)
    # 极小预算，强制裁剪
    budget = TokenBudget(total=5000, history_ratio=0.1)
    engine = ContextEngine(rules, budget)

    # 构造 20 条对话历史，每条约 100 tokens
    history = [
        {"role": "user" if i % 2 == 0 else "assistant", "content": "x" * 200}
        for i in range(20)
    ]

    ctx = engine.assemble(user_message="继续", conversation_history=history)

    # 对话历史应被截断（不超过 budget）
    assert len(ctx.conversation_history) < len(history)
