"""上下文引擎 — token 预算管理与 prompt 组装。"""

import logging
from dataclasses import dataclass, field

from core.rules import RulesInterpreter

logger = logging.getLogger(__name__)

# 默认 token 预算（基于 200k 窗口模型）
DEFAULT_TOTAL_BUDGET = 150000  # 模型窗口 × 0.75
DEFAULT_OUTPUT_RESERVE = 8000  # 预留输出


@dataclass
class TokenBudget:
    """Token 预算分配。"""
    total: int = DEFAULT_TOTAL_BUDGET
    output_reserve: int = DEFAULT_OUTPUT_RESERVE

    # 各区域占比
    system_identity_ratio: float = 0.12   # 系统身份 + 宪法规则 10-15%
    task_anchor_ratio: float = 0.04       # 任务锚点 3-5%
    experience_rules_ratio: float = 0.08  # 相关经验规则 5-10%
    memory_ratio: float = 0.15            # 相关记忆 10-20%
    history_ratio: float = 0.25           # 对话历史 20-30%
    preferences_ratio: float = 0.02       # 用户偏好 2-3%
    error_trace_ratio: float = 0.03       # 错误轨迹 0-5%
    # 剩余 ~31% 为安全边际

    @property
    def available(self) -> int:
        return self.total - self.output_reserve

    def get_budget(self, section: str) -> int:
        ratio_map = {
            "system_identity": self.system_identity_ratio,
            "task_anchor": self.task_anchor_ratio,
            "experience_rules": self.experience_rules_ratio,
            "memory": self.memory_ratio,
            "history": self.history_ratio,
            "preferences": self.preferences_ratio,
            "error_trace": self.error_trace_ratio,
        }
        ratio = ratio_map.get(section, 0)
        return int(self.available * ratio)


@dataclass
class ContextSection:
    """上下文的一个区段。"""
    name: str
    content: str
    tokens: int = 0
    priority: int = 0  # 越高越优先保留


@dataclass
class AssembledContext:
    """组装完成的上下文。"""
    system_prompt: str = ""
    conversation_history: list[dict] = field(default_factory=list)
    total_tokens: int = 0
    sections_used: list[str] = field(default_factory=list)
    budget_usage: dict = field(default_factory=dict)


def estimate_tokens(text: str) -> int:
    """粗略估算 token 数（中英混合取 len/2）。"""
    if not text:
        return 0
    return len(text) // 2


def truncate_to_tokens(text: str, max_tokens: int) -> str:
    """截断文本到指定 token 预算。"""
    if estimate_tokens(text) <= max_tokens:
        return text
    # 粗略：每 token ≈ 2 字符
    max_chars = max_tokens * 2
    return text[:max_chars] + "\n\n[... 因 token 预算限制已截断 ...]"


class ContextEngine:
    """上下文引擎。负责 token 预算管理和 prompt 组装。"""

    def __init__(
        self,
        rules_interpreter: RulesInterpreter,
        budget: TokenBudget | None = None,
    ):
        """
        Args:
            rules_interpreter: 规则解释器实例
            budget: token 预算配置（None 使用默认值）
        """
        self.rules = rules_interpreter
        self.budget = budget or TokenBudget()
        self._task_anchor: str | None = None

    def set_task_anchor(self, anchor: str | None):
        """设置当前任务锚点。"""
        self._task_anchor = anchor

    def assemble(
        self,
        user_message: str,
        conversation_history: list[dict] | None = None,
        memories: list[str] | None = None,
        user_preferences: str = "",
        error_trace: str = "",
    ) -> AssembledContext:
        """
        组装完整上下文。

        按优先级从高到低组装各区段，在 token 预算内最大化信息密度。

        宪法规则在前（稳定，cache 友好），经验规则在后（动态）。

        Args:
            user_message: 当前用户消息
            conversation_history: 对话历史 [{"role": "user"|"assistant", "content": "..."}]
            memories: 检索到的相关记忆片段
            user_preferences: 用户偏好摘要
            error_trace: 相关错误轨迹

        Returns:
            AssembledContext 包含组装好的 system_prompt 和裁剪后的对话历史
        """
        conversation_history = conversation_history or []
        memories = memories or []

        result = AssembledContext()
        sections: list[ContextSection] = []
        budget_usage = {}

        # === 1. 系统身份 + 宪法规则（最高优先级，放前部） ===
        identity_budget = self.budget.get_budget("system_identity")
        rules_result = self.rules.build_system_prompt_section(
            task_context=user_message,
            constitution_budget=identity_budget,
            experience_budget=0,  # 经验规则单独处理
        )
        if rules_result["constitution_prompt"]:
            sections.append(ContextSection(
                name="constitution",
                content=rules_result["constitution_prompt"],
                tokens=rules_result["constitution_tokens"],
                priority=100,
            ))
        budget_usage["constitution"] = rules_result["constitution_tokens"]

        # === 2. 任务锚点 ===
        if self._task_anchor:
            anchor_budget = self.budget.get_budget("task_anchor")
            anchor_text = truncate_to_tokens(
                f"## 当前任务\n\n{self._task_anchor}", anchor_budget
            )
            anchor_tokens = estimate_tokens(anchor_text)
            sections.append(ContextSection(
                name="task_anchor",
                content=anchor_text,
                tokens=anchor_tokens,
                priority=90,
            ))
            budget_usage["task_anchor"] = anchor_tokens

        # === 3. 经验规则（动态，放后部） ===
        exp_budget = self.budget.get_budget("experience_rules")
        exp_result = self.rules.build_system_prompt_section(
            task_context=user_message,
            constitution_budget=0,
            experience_budget=exp_budget,
        )
        if exp_result["experience_prompt"]:
            sections.append(ContextSection(
                name="experience_rules",
                content=exp_result["experience_prompt"],
                tokens=exp_result["experience_tokens"],
                priority=70,
            ))
        budget_usage["experience_rules"] = exp_result["experience_tokens"]

        # === 4. 相关记忆 ===
        if memories:
            mem_budget = self.budget.get_budget("memory")
            memory_text = "## 相关记忆\n\n" + "\n\n---\n\n".join(memories)
            memory_text = truncate_to_tokens(memory_text, mem_budget)
            mem_tokens = estimate_tokens(memory_text)
            sections.append(ContextSection(
                name="memory",
                content=memory_text,
                tokens=mem_tokens,
                priority=60,
            ))
            budget_usage["memory"] = mem_tokens

        # === 5. 用户偏好 ===
        if user_preferences:
            pref_budget = self.budget.get_budget("preferences")
            pref_text = truncate_to_tokens(
                f"## 用户偏好\n\n{user_preferences}", pref_budget
            )
            pref_tokens = estimate_tokens(pref_text)
            sections.append(ContextSection(
                name="preferences",
                content=pref_text,
                tokens=pref_tokens,
                priority=50,
            ))
            budget_usage["preferences"] = pref_tokens

        # === 6. 错误轨迹 ===
        if error_trace:
            err_budget = self.budget.get_budget("error_trace")
            err_text = truncate_to_tokens(
                f"## 需避免的错误\n\n{error_trace}", err_budget
            )
            err_tokens = estimate_tokens(err_text)
            sections.append(ContextSection(
                name="error_trace",
                content=err_text,
                tokens=err_tokens,
                priority=40,
            ))
            budget_usage["error_trace"] = err_tokens

        # === 组装 system prompt ===
        # 按优先级排序：高优先级在前（宪法规则前置利于 KV-cache）
        sections.sort(key=lambda s: s.priority, reverse=True)
        system_parts = [s.content for s in sections if s.content]
        result.system_prompt = "\n\n".join(system_parts)
        system_tokens = sum(s.tokens for s in sections)

        # === 7. 对话历史（在 system prompt 之后分配剩余预算） ===
        history_budget = self.budget.get_budget("history")
        trimmed_history = self._trim_history(conversation_history, history_budget)
        history_tokens = sum(
            estimate_tokens(m.get("content", "")) for m in trimmed_history
        )
        budget_usage["history"] = history_tokens

        result.conversation_history = trimmed_history
        result.total_tokens = system_tokens + history_tokens
        result.sections_used = [s.name for s in sections]
        result.budget_usage = budget_usage

        logger.info(
            f"Context assembled: {result.total_tokens} tokens, "
            f"sections={result.sections_used}"
        )
        return result

    def _trim_history(
        self,
        history: list[dict],
        max_tokens: int,
    ) -> list[dict]:
        """
        裁剪对话历史到 token 预算内。

        策略：保留最近的消息，从最老的开始丢弃。
        """
        if not history:
            return []

        # 从最新往最老累加，直到超出预算
        result = []
        used = 0
        for msg in reversed(history):
            msg_tokens = estimate_tokens(msg.get("content", ""))
            if used + msg_tokens > max_tokens:
                break
            result.append(msg)
            used += msg_tokens

        # 恢复原始顺序
        result.reverse()
        return result

    def get_current_usage(self, context: AssembledContext) -> dict:
        """获取当前上下文的 token 使用情况报告。"""
        available = self.budget.available
        return {
            "total_tokens": context.total_tokens,
            "budget_available": available,
            "usage_ratio": context.total_tokens / available if available > 0 else 0,
            "sections": context.budget_usage,
            "needs_compaction": (context.total_tokens / available) >= 0.85
                if available > 0 else False,
        }
