"""规则解释器测试。"""

import pytest
from core.rules import RulesInterpreter, Rule, parse_rule_file


class TestParseRuleFile:
    def test_parse_plain_markdown(self, tmp_path):
        """解析纯 Markdown 规则文件（无 YAML front matter）。"""
        rule_file = tmp_path / "constitution" / "identity.md"
        rule_file.parent.mkdir(parents=True)
        rule_file.write_text(
            "# 系统身份\n\n你是一个自进化 AI 助手。\n"
        )

        rule = parse_rule_file(rule_file)
        assert rule is not None
        assert rule.name == "identity"
        assert rule.level == "constitution"
        assert "自进化" in rule.content
        # 关键词从标题提取
        assert "系统身份" in " ".join(rule.keywords)

    def test_parse_experience_rule(self, tmp_path):
        """解析经验级规则文件。"""
        rule_file = tmp_path / "experience" / "task_strategies.md"
        rule_file.parent.mkdir(parents=True)
        rule_file.write_text("# 任务策略\n\n分析类任务简短回答。\n")

        rule = parse_rule_file(rule_file)
        assert rule is not None
        assert rule.name == "task_strategies"
        assert rule.level == "experience"
        assert rule.content.startswith("# 任务策略")

    def test_parse_empty_file(self, tmp_path):
        """空文件返回空内容规则。"""
        rule_file = tmp_path / "experience" / "empty.md"
        rule_file.parent.mkdir(parents=True)
        rule_file.write_text("")

        rule = parse_rule_file(rule_file)
        assert rule is None or rule.content == ""

    def test_parse_nonexistent_file(self, tmp_path):
        """不存在的文件返回 None。"""
        rule = parse_rule_file(tmp_path / "nonexistent.md")
        assert rule is None


class TestRulesInterpreter:
    def _setup_rules(self, tmp_path):
        """创建测试用规则目录（纯 Markdown，无 front matter）。"""
        rules_dir = tmp_path / "rules"
        (rules_dir / "constitution").mkdir(parents=True)
        (rules_dir / "experience").mkdir(parents=True)

        # 宪法规则
        (rules_dir / "constitution" / "identity.md").write_text(
            "# 系统身份\n\n你是一个自进化 AI 助手。\n"
        )
        (rules_dir / "constitution" / "safety_boundaries.md").write_text(
            "# 安全边界\n\n不得执行危险操作。\n"
        )

        # 经验规则
        (rules_dir / "experience" / "task_strategies.md").write_text(
            "# 任务策略\n\n## 分析类任务\n\n分析类任务控制在 500 字内。\n"
        )
        (rules_dir / "experience" / "interaction_patterns.md").write_text(
            "# 交互模式\n\n## 澄清确认\n\n执行前主动澄清不确定性。\n"
        )
        (rules_dir / "experience" / "error_patterns.md").write_text(
            "# 错误模式\n\n## 常见假设错误\n\n错误假设、遗漏考虑。\n"
        )

        return str(rules_dir)

    def test_load_rules(self, tmp_path):
        """加载所有规则。"""
        rules_dir = self._setup_rules(tmp_path)
        interpreter = RulesInterpreter(rules_dir)
        result = interpreter.load_rules()

        assert result["total_rules"] == 5
        assert len(result["constitution"]) == 2
        assert len(result["experience"]) == 3
        assert result["total_tokens"] > 0

    def test_get_constitution_rules(self, tmp_path):
        """获取宪法级规则。"""
        rules_dir = self._setup_rules(tmp_path)
        interpreter = RulesInterpreter(rules_dir)
        rules = interpreter.get_constitution_rules()

        assert len(rules) == 2
        names = {r.name for r in rules}
        assert "identity" in names
        assert "safety_boundaries" in names

    def test_get_experience_rules_no_context(self, tmp_path):
        """无上下文时返回所有经验规则。"""
        rules_dir = self._setup_rules(tmp_path)
        interpreter = RulesInterpreter(rules_dir)
        rules = interpreter.get_experience_rules()

        assert len(rules) == 3

    def test_get_experience_rules_with_context(self, tmp_path):
        """有上下文时按相关性排序——标题关键词匹配。"""
        rules_dir = self._setup_rules(tmp_path)
        interpreter = RulesInterpreter(rules_dir)
        rules = interpreter.get_experience_rules(task_context="帮我分析竞品策略")

        # task_strategies 应该排在前面（标题含"任务策略"、"分析"关键词）
        assert len(rules) == 3
        assert rules[0].name == "task_strategies"

    def test_get_experience_rules_token_budget(self, tmp_path):
        """Token 预算限制生效。"""
        rules_dir = self._setup_rules(tmp_path)
        interpreter = RulesInterpreter(rules_dir)
        rules = interpreter.get_experience_rules(max_tokens=30)

        assert len(rules) <= 2

    def test_build_system_prompt_section(self, tmp_path):
        """构建系统提示词片段。"""
        rules_dir = self._setup_rules(tmp_path)
        interpreter = RulesInterpreter(rules_dir)
        result = interpreter.build_system_prompt_section(
            task_context="分析竞品",
            constitution_budget=5000,
            experience_budget=3000,
        )

        assert "核心规则" in result["constitution_prompt"]
        assert "经验指导" in result["experience_prompt"]
        assert result["constitution_tokens"] > 0
        assert result["experience_tokens"] > 0
        assert len(result["rules_used"]) == 5

    def test_get_rule_by_name(self, tmp_path):
        """按名称查找规则。"""
        rules_dir = self._setup_rules(tmp_path)
        interpreter = RulesInterpreter(rules_dir)

        rule = interpreter.get_rule_by_name("identity")
        assert rule is not None
        assert rule.level == "constitution"

        assert interpreter.get_rule_by_name("nonexistent") is None

    def test_reload_picks_up_changes(self, tmp_path):
        """reload 能加载新增的规则。"""
        rules_dir = self._setup_rules(tmp_path)
        interpreter = RulesInterpreter(rules_dir)
        result1 = interpreter.load_rules()

        # 新增一条规则
        (tmp_path / "rules" / "experience" / "new_rule.md").write_text(
            "# 新规则\n\n新规则内容。\n"
        )

        result2 = interpreter.reload()
        assert result2["total_rules"] == result1["total_rules"] + 1

    def test_missing_rules_dir(self, tmp_path):
        """规则目录不存在时不崩溃。"""
        interpreter = RulesInterpreter(str(tmp_path / "nonexistent"))
        result = interpreter.load_rules()
        assert result["total_rules"] == 0

    def test_keywords_from_headings(self, tmp_path):
        """关键词从 Markdown 标题提取。"""
        rules_dir = tmp_path / "rules"
        (rules_dir / "experience").mkdir(parents=True)
        (rules_dir / "experience" / "test_rule.md").write_text(
            "# 主标题\n\n## 子标题一\n\n内容\n\n## 子标题二\n\n更多内容\n"
        )
        interpreter = RulesInterpreter(str(rules_dir))
        interpreter.load_rules()
        rule = interpreter.get_rule_by_name("test_rule")

        assert rule is not None
        keywords = rule.keywords
        assert "主标题" in keywords
        assert any("子标题" in kw for kw in keywords)


class TestRule:
    def test_token_estimate(self):
        """Token 估算。"""
        rule = Rule("test.md", "test", "experience", "Hello World 你好世界")
        assert rule.token_estimate() > 0

    def test_repr(self):
        """字符串表示。"""
        rule = Rule("test.md", "test", "experience", "content")
        assert "test" in repr(rule)
        assert "experience" in repr(rule)

    def test_keywords_extraction(self):
        """从内容标题提取关键词。"""
        rule = Rule("test.md", "test", "experience",
                    "# 分析策略\n\n## 竞品分析\n\n内容")
        kws = rule.keywords
        assert "分析策略" in " ".join(kws)
