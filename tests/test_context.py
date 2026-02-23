"""上下文引擎测试。"""

import pytest
from core.rules import RulesInterpreter
from core.context import (
    ContextEngine, TokenBudget, estimate_tokens, truncate_to_tokens
)


def _setup_rules(tmp_path):
    """创建测试用规则目录。"""
    rules_dir = tmp_path / "rules"
    (rules_dir / "constitution").mkdir(parents=True)
    (rules_dir / "experience").mkdir(parents=True)

    (rules_dir / "constitution" / "identity.md").write_text(
        "---\nname: identity\n---\n\n# 系统身份\n\n你是 AI 助手。\n"
    )
    (rules_dir / "experience" / "task_strategies.md").write_text(
        "---\nname: task_strategies\nkeywords: [任务, 策略]\n---\n\n"
        "# 任务策略\n\n分析类任务简短回答。\n"
    )

    return str(rules_dir)


class TestEstimateTokens:
    def test_empty(self):
        assert estimate_tokens("") == 0

    def test_english(self):
        assert estimate_tokens("Hello World") > 0

    def test_chinese(self):
        assert estimate_tokens("你好世界") > 0


class TestTruncateToTokens:
    def test_no_truncation_needed(self):
        text = "短文本"
        assert truncate_to_tokens(text, 1000) == text

    def test_truncation(self):
        text = "很长的文本" * 100
        result = truncate_to_tokens(text, 10)
        assert len(result) < len(text)
        assert "截断" in result


class TestTokenBudget:
    def test_available(self):
        budget = TokenBudget(total=100000, output_reserve=8000)
        assert budget.available == 92000

    def test_get_budget(self):
        budget = TokenBudget(total=100000, output_reserve=0)
        identity_budget = budget.get_budget("system_identity")
        assert identity_budget == int(100000 * 0.12)

    def test_unknown_section(self):
        budget = TokenBudget()
        assert budget.get_budget("unknown") == 0


class TestContextEngine:
    def test_assemble_basic(self, tmp_path):
        """基本组装：有规则、有历史。"""
        rules_dir = _setup_rules(tmp_path)
        interpreter = RulesInterpreter(rules_dir)
        engine = ContextEngine(interpreter)

        history = [
            {"role": "user", "content": "你好"},
            {"role": "assistant", "content": "你好！有什么可以帮你？"},
        ]

        ctx = engine.assemble(
            user_message="帮我分析竞品",
            conversation_history=history,
        )

        assert ctx.system_prompt != ""
        assert "核心规则" in ctx.system_prompt
        assert len(ctx.conversation_history) == 2
        assert ctx.total_tokens > 0
        assert "constitution" in ctx.sections_used

    def test_assemble_with_all_sections(self, tmp_path):
        """组装所有区段。"""
        rules_dir = _setup_rules(tmp_path)
        interpreter = RulesInterpreter(rules_dir)
        engine = ContextEngine(interpreter)
        engine.set_task_anchor("- 目标: 分析竞品\n- 进度: 1/3")

        ctx = engine.assemble(
            user_message="分析竞品",
            conversation_history=[
                {"role": "user", "content": "开始分析"},
                {"role": "assistant", "content": "好的"},
            ],
            memories=["上次分析发现竞品 A 的优势在于速度"],
            user_preferences="喜欢简短回答",
            error_trace="上次犯了假设错误",
        )

        assert "核心规则" in ctx.system_prompt
        assert "经验指导" in ctx.system_prompt
        assert "当前任务" in ctx.system_prompt
        assert "相关记忆" in ctx.system_prompt
        assert "用户偏好" in ctx.system_prompt
        assert "需避免的错误" in ctx.system_prompt
        assert len(ctx.sections_used) >= 5

    def test_assemble_empty_context(self, tmp_path):
        """空输入不崩溃。"""
        rules_dir = _setup_rules(tmp_path)
        interpreter = RulesInterpreter(rules_dir)
        engine = ContextEngine(interpreter)

        ctx = engine.assemble(user_message="你好")

        assert ctx.system_prompt != ""
        assert ctx.conversation_history == []
        assert ctx.total_tokens > 0

    def test_history_trimming(self, tmp_path):
        """对话历史超出预算时从最老开始裁剪。"""
        rules_dir = _setup_rules(tmp_path)
        interpreter = RulesInterpreter(rules_dir)
        # 给一个很小的预算
        budget = TokenBudget(total=2000, output_reserve=500)
        engine = ContextEngine(interpreter, budget=budget)

        # 生成很长的对话历史
        long_history = []
        for i in range(50):
            long_history.append({"role": "user", "content": f"消息 {i} " + "长内容" * 50})
            long_history.append({"role": "assistant", "content": f"回复 {i} " + "详细内容" * 50})

        ctx = engine.assemble(
            user_message="继续",
            conversation_history=long_history,
        )

        # 应该被裁剪到远少于 100 条
        assert len(ctx.conversation_history) < len(long_history)
        # 保留的是最近的消息
        if ctx.conversation_history:
            last_kept = ctx.conversation_history[-1]
            assert last_kept == long_history[-1]

    def test_constitution_before_experience(self, tmp_path):
        """宪法规则在经验规则之前（cache 友好）。"""
        rules_dir = _setup_rules(tmp_path)
        interpreter = RulesInterpreter(rules_dir)
        engine = ContextEngine(interpreter)

        ctx = engine.assemble(user_message="分析任务")

        # 在 system_prompt 中，宪法规则应出现在经验规则之前
        constitution_pos = ctx.system_prompt.find("核心规则")
        experience_pos = ctx.system_prompt.find("经验指导")

        if constitution_pos >= 0 and experience_pos >= 0:
            assert constitution_pos < experience_pos

    def test_task_anchor(self, tmp_path):
        """任务锚点被正确注入。"""
        rules_dir = _setup_rules(tmp_path)
        interpreter = RulesInterpreter(rules_dir)
        engine = ContextEngine(interpreter)

        engine.set_task_anchor("- 目标: 写单元测试\n- 进度: 2/5")
        ctx = engine.assemble(user_message="继续")

        assert "当前任务" in ctx.system_prompt
        assert "写单元测试" in ctx.system_prompt

    def test_get_current_usage(self, tmp_path):
        """Token 使用情况报告。"""
        rules_dir = _setup_rules(tmp_path)
        interpreter = RulesInterpreter(rules_dir)
        engine = ContextEngine(interpreter)

        ctx = engine.assemble(user_message="你好")
        usage = engine.get_current_usage(ctx)

        assert "total_tokens" in usage
        assert "budget_available" in usage
        assert "usage_ratio" in usage
        assert isinstance(usage["needs_compaction"], bool)

    def test_needs_compaction_detection(self, tmp_path):
        """检测需要 compaction 的情况。"""
        rules_dir = _setup_rules(tmp_path)
        interpreter = RulesInterpreter(rules_dir)
        # 小预算但足够装下一些内容
        budget = TokenBudget(total=500, output_reserve=50)
        engine = ContextEngine(interpreter, budget=budget)

        ctx = engine.assemble(
            user_message="继续讨论",
            conversation_history=[
                {"role": "user", "content": "消息内容" * 50},
                {"role": "assistant", "content": "回复内容" * 50},
            ],
        )
        usage = engine.get_current_usage(ctx)

        # 规则内容会占用一些 token
        assert usage["total_tokens"] > 0
        assert usage["usage_ratio"] > 0

    def test_custom_budget(self, tmp_path):
        """自定义预算生效。"""
        rules_dir = _setup_rules(tmp_path)
        interpreter = RulesInterpreter(rules_dir)
        budget = TokenBudget(
            total=50000,
            output_reserve=5000,
            system_identity_ratio=0.20,
        )
        engine = ContextEngine(interpreter, budget=budget)

        assert engine.budget.get_budget("system_identity") == int(45000 * 0.20)
