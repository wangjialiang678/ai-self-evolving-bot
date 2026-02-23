"""规则解释器 — 读取、解析和注入规则到 system prompt。

规则文件为纯 Markdown 格式，不使用 YAML front matter。
名称从文件名推断，关键词从内容标题和正文提取。
"""

import logging
import re
from pathlib import Path

logger = logging.getLogger(__name__)


class Rule:
    """单条规则的数据结构。"""

    def __init__(
        self,
        file_path: str,
        name: str,
        level: str,
        content: str,
        metadata: dict | None = None,
    ):
        self.file_path = file_path
        self.name = name
        self.level = level  # "constitution" | "experience"
        self.content = content
        self.metadata = metadata or {}

    @property
    def keywords(self) -> list[str]:
        """从内容中提取关键词（标题词 + metadata 中的 keywords）。"""
        kws = list(self.metadata.get("keywords", []))
        # 从 Markdown 标题提取关键词
        for match in re.finditer(r"^#+\s+(.+)$", self.content, re.MULTILINE):
            heading = match.group(1).strip()
            kws.extend(heading.split())
        return kws

    def token_estimate(self) -> int:
        """粗略估算 token 数（中英混合取 len/2）。"""
        return len(self.content) // 2

    def __repr__(self):
        return f"Rule({self.name}, level={self.level}, ~{self.token_estimate()}tok)"


def parse_rule_file(file_path: Path) -> Rule | None:
    """解析规则 Markdown 文件（纯 Markdown，不使用 YAML front matter）。"""
    try:
        text = file_path.read_text(encoding="utf-8")
    except Exception as e:
        logger.error(f"Failed to read rule file {file_path}: {e}")
        return None

    content = text.strip()

    # 判断规则级别
    level = "experience"
    if "constitution" in str(file_path):
        level = "constitution"

    name = file_path.stem

    return Rule(
        file_path=str(file_path),
        name=name,
        level=level,
        content=content,
    )


class RulesInterpreter:
    """规则解释器。读取规则文件、按相关性过滤、生成 prompt 片段。"""

    def __init__(self, rules_dir: str):
        """
        Args:
            rules_dir: workspace/rules/ 目录路径
        """
        self.rules_dir = Path(rules_dir)
        self._constitution: list[Rule] = []
        self._experience: list[Rule] = []
        self._loaded = False

    def load_rules(self) -> dict:
        """
        加载所有规则文件。

        Returns:
            {"constitution": [Rule, ...], "experience": [Rule, ...],
             "total_rules": int, "total_tokens": int}
        """
        self._constitution = []
        self._experience = []

        constitution_dir = self.rules_dir / "constitution"
        experience_dir = self.rules_dir / "experience"

        for directory, target_list in [
            (constitution_dir, self._constitution),
            (experience_dir, self._experience),
        ]:
            if not directory.exists():
                logger.warning(f"Rules directory not found: {directory}")
                continue
            for md_file in sorted(directory.glob("*.md")):
                rule = parse_rule_file(md_file)
                if rule and rule.content:
                    target_list.append(rule)

        self._loaded = True
        total_tokens = sum(r.token_estimate() for r in self._constitution + self._experience)
        logger.info(
            f"Loaded {len(self._constitution)} constitution + "
            f"{len(self._experience)} experience rules ({total_tokens} est. tokens)"
        )
        return {
            "constitution": self._constitution,
            "experience": self._experience,
            "total_rules": len(self._constitution) + len(self._experience),
            "total_tokens": total_tokens,
        }

    def get_constitution_rules(self) -> list[Rule]:
        """返回所有宪法级规则（始终注入）。"""
        if not self._loaded:
            self.load_rules()
        return self._constitution

    def get_experience_rules(
        self,
        task_context: str = "",
        max_tokens: int | None = None,
    ) -> list[Rule]:
        """
        返回与当前任务相关的经验级规则。

        Args:
            task_context: 当前任务描述（用于相关性过滤）
            max_tokens: 最大 token 预算（超出则截断低相关度的）

        Returns:
            过滤并排序后的经验规则列表
        """
        if not self._loaded:
            self.load_rules()

        if not task_context:
            # 无上下文时返回全部（受 token 限制）
            rules = list(self._experience)
        else:
            # 按相关性排序：关键词匹配得分
            scored = []
            for rule in self._experience:
                score = self._relevance_score(rule, task_context)
                scored.append((score, rule))
            scored.sort(key=lambda x: x[0], reverse=True)
            rules = [rule for _, rule in scored]

        # Token 预算截断
        if max_tokens is not None:
            result = []
            used = 0
            for rule in rules:
                est = rule.token_estimate()
                if used + est > max_tokens:
                    break
                result.append(rule)
                used += est
            return result

        return rules

    def _relevance_score(self, rule: Rule, task_context: str) -> float:
        """计算规则与任务的相关性分数（支持中英文）。"""
        score = 0.0
        context_lower = task_context.lower()

        # 关键词双向子串匹配
        for kw in rule.keywords:
            kw_lower = kw.lower()
            if kw_lower in context_lower:
                score += 2.0
            elif context_lower in kw_lower:
                score += 1.5

        # 规则名称匹配
        name_readable = rule.name.replace("_", " ").lower()
        if name_readable in context_lower or context_lower in name_readable:
            score += 1.0

        # 字符 bigram 重叠（适用于中文无空格文本）
        rule_preview = rule.content[:300].lower()
        ctx_bigrams = {context_lower[i:i+2] for i in range(len(context_lower) - 1)}
        rule_bigrams = {rule_preview[i:i+2] for i in range(len(rule_preview) - 1)}
        overlap = len(ctx_bigrams & rule_bigrams)
        if overlap > 0:
            score += min(overlap * 0.3, 3.0)

        # 基础分
        score += 0.01

        return score

    def build_system_prompt_section(
        self,
        task_context: str = "",
        constitution_budget: int = 3000,
        experience_budget: int = 2000,
    ) -> dict:
        """
        构建系统提示词的规则部分。

        宪法级规则放在前部（稳定，cache 友好）。
        经验级规则放在后部（动态追加）。

        Args:
            task_context: 当前任务描述
            constitution_budget: 宪法规则 token 预算
            experience_budget: 经验规则 token 预算

        Returns:
            {"constitution_prompt": str,
             "experience_prompt": str,
             "constitution_tokens": int,
             "experience_tokens": int,
             "rules_used": list[str]}
        """
        # 宪法级：全部注入（受预算限制）
        constitution_rules = self.get_constitution_rules()
        constitution_parts = []
        constitution_tokens = 0
        for rule in constitution_rules:
            est = rule.token_estimate()
            if constitution_tokens + est > constitution_budget:
                logger.warning(f"Constitution budget exceeded, skipping {rule.name}")
                break
            constitution_parts.append(f"### {rule.name}\n\n{rule.content}")
            constitution_tokens += est

        # 经验级：按相关性过滤
        experience_rules = self.get_experience_rules(task_context, max_tokens=experience_budget)
        experience_parts = []
        experience_tokens = 0
        for rule in experience_rules:
            experience_parts.append(f"### {rule.name}\n\n{rule.content}")
            experience_tokens += rule.token_estimate()

        constitution_prompt = ""
        if constitution_parts:
            constitution_prompt = "## 核心规则\n\n" + "\n\n".join(constitution_parts)

        experience_prompt = ""
        if experience_parts:
            experience_prompt = "## 经验指导\n\n" + "\n\n".join(experience_parts)

        rules_used = [r.name for r in constitution_rules[:len(constitution_parts)]] + \
                     [r.name for r in experience_rules]

        return {
            "constitution_prompt": constitution_prompt,
            "experience_prompt": experience_prompt,
            "constitution_tokens": constitution_tokens,
            "experience_tokens": experience_tokens,
            "rules_used": rules_used,
        }

    def get_rule_by_name(self, name: str) -> Rule | None:
        """按名称查找规则。"""
        if not self._loaded:
            self.load_rules()
        for rule in self._constitution + self._experience:
            if rule.name == name:
                return rule
        return None

    def reload(self):
        """重新加载所有规则（规则文件被修改后调用）。"""
        self._loaded = False
        return self.load_rules()
