"""Multi-Agent Council — 提案审议委员会。

4 个委员角色用同一 LLM 依次扮演，对提案进行多维度审议。
"""

import json
import logging
import re
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


# ──────────────────────────────────────
#  委员角色定义
# ──────────────────────────────────────

COUNCIL_ROLES = {
    "safety": {
        "name": "安全委员",
        "emoji": "🛡️",
        "system_prompt": (
            "你是 AI 自进化系统的安全委员。你的职责是评估提案的安全性和风险。\n"
            "关注点：\n"
            "- 回滚可行性：如果方案失败，能否安全回滚？\n"
            "- 边界检查：方案是否可能影响核心功能？\n"
            "- 数据安全：是否有数据丢失或泄露风险？\n"
            "- 异常处理：极端情况下系统是否仍然稳定？\n\n"
            "请分析以下提案，给出你的 concern（担忧）和 recommendation（建议）。"
        ),
    },
    "efficiency": {
        "name": "效率委员",
        "emoji": "⚡",
        "system_prompt": (
            "你是 AI 自进化系统的效率委员。你的职责是评估提案的成本和效率影响。\n"
            "关注点：\n"
            "- Token 消耗：方案会增加多少 LLM 调用成本？\n"
            "- 延迟影响：是否会增加响应时间？\n"
            "- 资源占用：CPU/内存/存储开销如何？\n"
            "- 性价比：投入产出比是否合理？\n\n"
            "请分析以下提案，给出你的 concern（担忧）和 recommendation（建议）。"
        ),
    },
    "user_experience": {
        "name": "用户体验委员",
        "emoji": "👤",
        "system_prompt": (
            "你是 AI 自进化系统的用户体验委员。你的职责是从用户视角评估提案。\n"
            "关注点：\n"
            "- 用户感知：用户能否感受到改进？\n"
            "- 交互质量：对话体验是否会变好或变差？\n"
            "- 通知体验：通知频率和时机是否合理？\n"
            "- 学习成本：用户是否需要适应新的交互方式？\n\n"
            "请分析以下提案，给出你的 concern（担忧）和 recommendation（建议）。"
        ),
    },
    "long_term": {
        "name": "长期委员",
        "emoji": "🔭",
        "system_prompt": (
            "你是 AI 自进化系统的长期规划委员。你的职责是从架构演进角度评估提案。\n"
            "关注点：\n"
            "- 架构影响：方案是否引入技术债？\n"
            "- 可扩展性：未来扩展时是否需要重构？\n"
            "- 一致性：是否与系统整体设计方向一致？\n"
            "- 可维护性：代码是否易于理解和维护？\n\n"
            "请分析以下提案，给出你的 concern（担忧）和 recommendation（建议）。"
        ),
    },
}


# ──────────────────────────────────────
#  数据结构
# ──────────────────────────────────────

@dataclass
class CouncilMemberReview:
    """单个委员的审议结果。"""
    role: str            # safety | efficiency | user_experience | long_term
    name: str            # 安全委员 | 效率委员 | ...
    concern: str         # 担忧/发现的问题
    recommendation: str  # 建议/改进方向


@dataclass
class CouncilReview:
    """完整的审议会结果。"""
    proposal_id: str
    reviews: list[CouncilMemberReview] = field(default_factory=list)
    conclusion: str = ""   # "通过" | "修改后通过" | "否决"
    summary: str = ""      # 综合摘要

    def is_approved(self) -> bool:
        return self.conclusion == "通过"

    def needs_revision(self) -> bool:
        return self.conclusion == "修改后通过"

    def is_rejected(self) -> bool:
        return self.conclusion == "否决"


# ──────────────────────────────────────
#  Council 审议逻辑
# ──────────────────────────────────────

def _build_proposal_text(proposal: dict) -> str:
    """将提案 dict 格式化为人类可读文本。"""
    parts = []
    parts.append(f"提案 ID：{proposal.get('proposal_id', '未知')}")
    if "problem" in proposal:
        parts.append(f"\n问题描述：\n{proposal['problem']}")
    if "solution" in proposal:
        parts.append(f"\n解决方案：\n{proposal['solution']}")
    if "files_affected" in proposal:
        files = proposal["files_affected"]
        if isinstance(files, list):
            files = "、".join(files)
        parts.append(f"\n影响文件：{files}")
    if "priority" in proposal:
        parts.append(f"\n优先级：{proposal['priority']}")
    if "risk_level" in proposal:
        parts.append(f"\n风险等级：{proposal['risk_level']}")
    return "\n".join(parts)


def _parse_member_response(text: str) -> tuple[str, str]:
    """从 LLM 自由文本中提取 concern 和 recommendation。

    Returns:
        (concern, recommendation)
    """
    concern = ""
    recommendation = ""

    # 尝试匹配 "concern:" / "担忧:"
    concern_match = re.search(
        r"(?:concern|担忧)\s*[:：]\s*(.+?)(?=(?:recommendation|建议)\s*[:：]|$)",
        text,
        re.IGNORECASE | re.DOTALL,
    )
    if concern_match:
        concern = concern_match.group(1).strip()

    # 尝试匹配 "recommendation:" / "建议:"
    rec_match = re.search(
        r"(?:recommendation|建议)\s*[:：]\s*(.+)",
        text,
        re.IGNORECASE | re.DOTALL,
    )
    if rec_match:
        recommendation = rec_match.group(1).strip()

    # fallback：整段作为 concern
    if not concern:
        concern = text.strip()
        recommendation = "无特别建议"

    return concern, recommendation


_VALID_CONCLUSIONS = {"通过", "修改后通过", "否决"}


def _parse_conclusion_response(text: str) -> tuple[str, str]:
    """从综合结论 LLM 返回（预期 JSON）中提取 conclusion 和 summary。

    Returns:
        (conclusion, summary)
    """
    # 尝试提取 JSON 块（支持 ```json ... ``` 包裹）
    json_text = text.strip()
    json_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", json_text, re.DOTALL)
    if json_match:
        json_text = json_match.group(1)
    else:
        # 尝试直接找 { ... }
        brace_match = re.search(r"\{.*\}", json_text, re.DOTALL)
        if brace_match:
            json_text = brace_match.group(0)

    try:
        data = json.loads(json_text)
        conclusion = data.get("conclusion", "")
        summary = data.get("summary", "")
        if conclusion in _VALID_CONCLUSIONS:
            return conclusion, summary
    except (json.JSONDecodeError, ValueError):
        pass

    # 解析失败：默认修改后通过
    logger.warning("Failed to parse conclusion JSON, defaulting to '修改后通过'")
    return "修改后通过", ""


async def run_council_review(
    proposal: dict,
    llm_client,
    model: str = "opus",
) -> "CouncilReview":
    """对提案进行 4 委员审议。

    用同一 LLM 依次扮演 4 个委员角色，每个委员输出 concern 和 recommendation。
    最后用一次额外 LLM 调用生成综合 conclusion。

    Args:
        proposal: 提案字典，至少包含 proposal_id, problem, solution
        llm_client: LLM 客户端实例（有 complete(system_prompt, user_message, model) 方法）
        model: 使用的模型名

    Returns:
        CouncilReview 包含所有委员审议和最终结论
    """
    proposal_id = proposal.get("proposal_id", "unknown")
    proposal_text = _build_proposal_text(proposal)
    council_review = CouncilReview(proposal_id=proposal_id)

    # ── 1. 依次调用 4 个委员 ──
    for role_key, role_info in COUNCIL_ROLES.items():
        try:
            response = await llm_client.complete(
                system_prompt=role_info["system_prompt"],
                user_message=proposal_text,
                model=model,
            )
            concern, recommendation = _parse_member_response(response)
        except Exception as exc:
            logger.error(f"Council member '{role_key}' LLM call failed: {exc}")
            concern = f"审议失败：{exc}"
            recommendation = "无特别建议"

        council_review.reviews.append(
            CouncilMemberReview(
                role=role_key,
                name=role_info["name"],
                concern=concern,
                recommendation=recommendation,
            )
        )

    # ── 2. 综合结论 ──
    reviews_text = "\n\n".join(
        f"【{r.name}】\n担忧：{r.concern}\n建议：{r.recommendation}"
        for r in council_review.reviews
    )
    conclusion_system = (
        "你是 AI 自进化系统的审议主席。根据以下 4 位委员的审议意见，给出最终结论。\n"
        "结论必须是以下三者之一：\"通过\"、\"修改后通过\"、\"否决\"。\n"
        "请以 JSON 格式输出：{\"conclusion\": \"...\", \"summary\": \"综合摘要\"}"
    )
    conclusion_user = (
        f"提案：{proposal_text}\n\n"
        f"委员审议意见：\n{reviews_text}"
    )

    try:
        conclusion_response = await llm_client.complete(
            system_prompt=conclusion_system,
            user_message=conclusion_user,
            model=model,
        )
        conclusion, summary = _parse_conclusion_response(conclusion_response)
    except Exception as exc:
        logger.error(f"Council conclusion LLM call failed: {exc}")
        conclusion, summary = "修改后通过", ""

    council_review.conclusion = conclusion
    council_review.summary = summary

    logger.info(
        f"Council review for '{proposal_id}' completed: {conclusion} "
        f"({len(council_review.reviews)} reviews)"
    )
    return council_review
