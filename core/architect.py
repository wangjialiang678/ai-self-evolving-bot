"""B5 Architect Engine — 读取 Observer 报告，诊断问题，设计并执行改进提案。"""

from __future__ import annotations

import json
import logging
from datetime import date, datetime
from pathlib import Path
from typing import Any

from core.council import CouncilReview, run_council_review
from core.llm_client import BaseLLMClient

logger = logging.getLogger(__name__)

# ──────────────────────────────────────
#  审批级别规则
# ──────────────────────────────────────

_BLAST_RADIUS_LEVEL = {
    "trivial": 0,
    "small": 1,
    "medium": 2,
    "large": 3,
}

_MAX_FILES_PER_LEVEL = {0: 1, 1: 3, 2: 5}  # level 3: >5 files

# ──────────────────────────────────────
#  提示词
# ──────────────────────────────────────

_DIAGNOSE_SYSTEM = """你是 Architect（架构师），负责从 Observer 报告中诊断问题并设计改进方案。

根据输入的 Observer 报告和活跃信号，生成一个或多个改进提案。

诊断优先级：
1. error_pattern（错误模式）— 最高优先级
2. efficiency（效率问题）
3. skill_gap（技能缺口）
4. preference（用户偏好）— 最低优先级

每个提案输出如下 JSON 格式（数组）：
[
  {
    "proposal_id": "prop_XXX",
    "level": 0,
    "trigger_source": "observer_report:YYYY-MM-DD",
    "problem": "问题描述",
    "solution": "方案描述",
    "files_affected": ["rules/experience/task_strategies.md"],
    "blast_radius": "trivial|small|medium|large",
    "expected_effect": "预期效果",
    "verification_method": "验证方法",
    "verification_days": 5,
    "rollback_plan": "回滚方案",
    "new_content": "要写入文件的新规则内容（Markdown）"
  }
]

如果没有需要改进的地方，返回空数组 []。
只输出 JSON，不要有其他文字。"""

_DESIGN_CONTENT_SYSTEM = """你是 Architect，负责根据提案设计具体的规则文件修改内容。

输出新的 Markdown 规则内容，直接替换目标文件。只输出 Markdown 内容，不要有其他说明。"""


# ──────────────────────────────────────
#  ArchitectEngine
# ──────────────────────────────────────

class ArchitectEngine:
    """Architect 引擎：读取 Observer 报告 → 诊断 → 提案 → 执行 → 验证。"""

    def __init__(
        self,
        workspace_path: str | Path,
        llm_client: BaseLLMClient,
        rollback_manager=None,
        telegram_channel=None,
    ):
        self.workspace_path = Path(workspace_path)
        self.llm_client = llm_client
        self.rollback_manager = rollback_manager
        self.telegram_channel = telegram_channel

        self.proposals_dir = self.workspace_path / "architect" / "proposals"
        self.deep_reports_dir = self.workspace_path / "observations" / "deep_reports"
        self.signals_path = self.workspace_path / "signals" / "active.jsonl"

        self.proposals_dir.mkdir(parents=True, exist_ok=True)

    # ──────────────────────────────────
    #  Public API
    # ──────────────────────────────────

    async def analyze_and_propose(self) -> list[dict]:
        """读取最新 Observer 报告和信号，生成提案列表。"""
        report_content, report_date = self._read_latest_report()
        if not report_content:
            return []

        signals = self._read_active_signals()

        user_message = (
            f"=== Observer 深度报告 ({report_date}) ===\n"
            f"{report_content}\n\n"
            f"=== 活跃信号 ===\n"
            f"{json.dumps(signals, ensure_ascii=False)}\n"
        )

        raw = ""
        try:
            raw = await self.llm_client.complete(
                system_prompt=_DIAGNOSE_SYSTEM,
                user_message=user_message,
                model="opus",
                max_tokens=3000,
            )
        except Exception as exc:
            logger.error("Architect LLM call failed: %s", exc)
            return []

        proposals = self._parse_proposals(raw, report_date)
        for proposal in proposals:
            self._save_proposal(proposal)
        return proposals

    async def execute_proposal(self, proposal: dict) -> dict:
        """执行一个提案（备份 → 修改文件 → 通知）。"""
        proposal_id = proposal.get("proposal_id", "unknown")
        level = self.determine_approval_level(proposal)
        proposal["level"] = level

        # Level 2+: 触发 Council 审议
        if level >= 2:
            council_review = await self._run_council_if_needed(proposal)
            if council_review is not None:
                proposal["council_review"] = self._council_review_to_dict(council_review)
                self._save_proposal(proposal)

                if council_review.is_rejected():
                    self._update_proposal_status(proposal_id, "rejected")
                    await self._notify_council(proposal, council_review)
                    return {"status": "rejected", "backup_id": None}

                if council_review.needs_revision():
                    self._update_proposal_status(proposal_id, "needs_revision")
                    await self._notify_council(proposal, council_review)
                    return {"status": "needs_revision", "backup_id": None}

                # 通过：继续走正常流程（Level 3 仍需人工批准，Level 2 也需人工批准）
                await self._notify_council(proposal, council_review)

        # Level 3: 需讨论，不自动执行
        if level == 3:
            self._update_proposal_status(proposal_id, "pending_discussion")
            await self._notify(proposal, "pending_discussion")
            return {"status": "pending_approval", "backup_id": None}

        # Level 2: 先审批再执行
        if level == 2:
            self._update_proposal_status(proposal_id, "pending_approval")
            await self._notify(proposal, "pending_approval")
            return {"status": "pending_approval", "backup_id": None}

        # Level 0 / 1: 执行
        files_affected = proposal.get("files_affected", [])
        backup_id = None

        try:
            if self.rollback_manager and files_affected:
                backup_id = self.rollback_manager.backup(files_affected, proposal_id)
        except Exception as exc:
            logger.error("Backup failed for %s: %s", proposal_id, exc)
            self._update_proposal_status(proposal_id, "failed")
            return {"status": "failed", "backup_id": None}

        try:
            await self._apply_changes(proposal)
        except Exception as exc:
            logger.error("Apply changes failed for %s: %s", proposal_id, exc)
            self._update_proposal_status(proposal_id, "failed")
            return {"status": "failed", "backup_id": backup_id}

        self._update_proposal_status(proposal_id, "executed", backup_id=backup_id)

        # Level 1: 执行后通知
        if level == 1:
            await self._notify(proposal, "executed")

        return {"status": "executed", "backup_id": backup_id}

    async def check_verification(self, proposal_id: str) -> dict:
        """检查提案验证期是否结束，评估效果。"""
        proposal = self._load_proposal(proposal_id)
        if not proposal:
            return {"status": "not_found", "proposal_id": proposal_id}

        current_status = proposal.get("status", "")
        if current_status not in ("executed", "verifying"):
            return {"status": current_status, "proposal_id": proposal_id}

        executed_at_str = proposal.get("executed_at", "")
        verification_days = int(proposal.get("verification_days", 5))

        if not executed_at_str:
            return {"status": "verifying", "proposal_id": proposal_id}

        try:
            executed_at = datetime.fromisoformat(executed_at_str)
        except ValueError:
            return {"status": "verifying", "proposal_id": proposal_id}

        elapsed_days = (datetime.now() - executed_at).days
        if elapsed_days < verification_days:
            self._update_proposal_status(proposal_id, "verifying")
            return {
                "status": "verifying",
                "proposal_id": proposal_id,
                "elapsed_days": elapsed_days,
                "remaining_days": verification_days - elapsed_days,
            }

        # 验证期结束 — 评估效果
        validated = await self._evaluate_effect(proposal)
        if validated:
            self._update_proposal_status(proposal_id, "validated")
            return {"status": "validated", "proposal_id": proposal_id}
        else:
            # 回滚
            backup_id = proposal.get("backup_id")
            if backup_id and self.rollback_manager:
                self.rollback_manager.rollback(backup_id)
            self._update_proposal_status(proposal_id, "rolled_back")
            return {"status": "rolled_back", "proposal_id": proposal_id}

    def get_pending_proposals(self) -> list[dict]:
        """获取待处理的提案列表。"""
        pending = []
        if not self.proposals_dir.exists():
            return pending
        for path in sorted(self.proposals_dir.glob("*.json")):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                if data.get("status") in ("pending_approval", "pending_discussion", "new"):
                    pending.append(data)
            except Exception as exc:
                logger.warning("Failed to read proposal %s: %s", path, exc)
        return pending

    def determine_approval_level(self, proposal: dict) -> int:
        """根据 blast_radius 和 files_affected 判断审批级别。"""
        files_count = len(proposal.get("files_affected", []))
        blast_radius = str(proposal.get("blast_radius", "small")).lower()

        # 超过 5 个文件或 large → Level 3
        if files_count > 5 or blast_radius == "large":
            return 3

        # 按 blast_radius 判断
        radius_level = _BLAST_RADIUS_LEVEL.get(blast_radius, 1)

        # 文件数校验：如果文件数超过该级别的上限，升级
        for level in (0, 1, 2):
            max_files = _MAX_FILES_PER_LEVEL[level]
            if files_count <= max_files and radius_level <= level:
                return level

        return 2

    # ──────────────────────────────────
    #  Internal helpers
    # ──────────────────────────────────

    def _read_latest_report(self) -> tuple[str, str]:
        """读取最新的 Observer 深度报告，返回 (内容, 日期字符串)。"""
        if not self.deep_reports_dir.exists():
            return "", ""
        reports = sorted(self.deep_reports_dir.glob("*.md"), reverse=True)
        if not reports:
            return "", ""
        latest = reports[0]
        report_date = latest.stem  # e.g. "2026-02-25"
        try:
            content = latest.read_text(encoding="utf-8")
            return content, report_date
        except Exception as exc:
            logger.error("Failed to read report %s: %s", latest, exc)
            return "", ""

    def _read_active_signals(self) -> list[dict]:
        """读取活跃信号。"""
        if not self.signals_path.exists():
            return []
        rows: list[dict] = []
        try:
            for line in self.signals_path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                    if isinstance(obj, dict):
                        rows.append(obj)
                except json.JSONDecodeError:
                    pass
        except Exception as exc:
            logger.error("Failed to read signals: %s", exc)
        return rows

    def _parse_proposals(self, raw: str, report_date: str) -> list[dict]:
        """解析 LLM 返回的提案 JSON。"""
        if not raw:
            return []
        text = raw.strip()

        # 尝试直接解析
        parsed = self._try_parse_json(text)
        if parsed is None:
            # 尝试从 ``` 代码块中提取
            if "```" in text:
                start = text.find("[", text.find("```"))
                end = text.rfind("]")
                if start != -1 and end != -1:
                    parsed = self._try_parse_json(text[start:end + 1])
            if parsed is None:
                # 兜底：找第一个 [ ... ]
                start = text.find("[")
                end = text.rfind("]")
                if start != -1 and end != -1:
                    parsed = self._try_parse_json(text[start:end + 1])

        if not isinstance(parsed, list):
            logger.warning("Architect LLM returned non-list: %s", text[:200])
            return []

        proposals = []
        for idx, item in enumerate(parsed, start=1):
            if not isinstance(item, dict):
                continue
            # 保证 proposal_id 存在（含微秒确保同日多次调用不碰撞）
            if not item.get("proposal_id"):
                item["proposal_id"] = (
                    f"prop_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}_{idx:03d}"
                )
            # 保证 trigger_source
            if not item.get("trigger_source"):
                item["trigger_source"] = f"observer_report:{report_date}"
            # 保证 status
            item.setdefault("status", "new")
            item.setdefault("created_at", datetime.now().replace(microsecond=0).isoformat())
            proposals.append(item)

        return proposals

    def _save_proposal(self, proposal: dict) -> None:
        """保存提案到 JSON 文件。"""
        proposal_id = proposal.get("proposal_id", "unknown")
        path = self.proposals_dir / f"{proposal_id}.json"
        try:
            path.write_text(
                json.dumps(proposal, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception as exc:
            logger.error("Failed to save proposal %s: %s", proposal_id, exc)

    def _load_proposal(self, proposal_id: str) -> dict | None:
        """从文件加载提案。"""
        path = self.proposals_dir / f"{proposal_id}.json"
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.error("Failed to load proposal %s: %s", proposal_id, exc)
            return None

    def _update_proposal_status(
        self,
        proposal_id: str,
        status: str,
        backup_id: str | None = None,
    ) -> None:
        """更新提案状态。"""
        proposal = self._load_proposal(proposal_id)
        if not proposal:
            return
        proposal["status"] = status
        if status == "executed":
            proposal["executed_at"] = datetime.now().replace(microsecond=0).isoformat()
        if backup_id:
            proposal["backup_id"] = backup_id
        self._save_proposal(proposal)

    async def _apply_changes(self, proposal: dict) -> None:
        """将提案内容写入目标文件。"""
        files_affected = proposal.get("files_affected", [])
        new_content = proposal.get("new_content", "")

        if not files_affected:
            return

        if not new_content:
            # 没有预先生成内容，让 LLM 生成
            try:
                new_content = await self.llm_client.complete(
                    system_prompt=_DESIGN_CONTENT_SYSTEM,
                    user_message=(
                        f"提案问题：{proposal.get('problem', '')}\n"
                        f"方案：{proposal.get('solution', '')}\n"
                        f"目标文件：{files_affected[0]}"
                    ),
                    model="opus",
                    max_tokens=1500,
                )
            except Exception as exc:
                logger.error("Content generation failed: %s", exc)
                raise RuntimeError(f"Content generation failed: {exc}") from exc

            if not new_content:
                raise RuntimeError("LLM returned empty content, refusing to overwrite file")

        # 写入第一个目标文件（experience 级别只改一个文件）
        target_rel = files_affected[0]
        target_path = (self.workspace_path / target_rel).resolve()
        workspace_resolved = self.workspace_path.resolve()
        # 路径安全校验：禁止写 workspace 以外的文件
        if not target_path.is_relative_to(workspace_resolved):
            raise ValueError(
                f"Path traversal rejected: {target_rel!r} resolves outside workspace"
            )
        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.write_text(new_content, encoding="utf-8")
        logger.info("Wrote new content to %s", target_path)

    async def _evaluate_effect(self, proposal: dict) -> bool:
        """评估提案效果（简化版：询问 LLM 或检查信号）。"""
        # 简单策略：读取当前信号，如果没有同类问题的新信号则认为成功
        signals = self._read_active_signals()
        problem = proposal.get("problem", "").lower()

        # 粗略：如果活跃信号中没有 HIGH/CRITICAL 的同类问题，认为验证通过
        critical_related = [
            s for s in signals
            if s.get("priority") in ("CRITICAL", "HIGH")
        ]
        return len(critical_related) == 0

    async def _notify(self, proposal: dict, event: str) -> None:
        """通过 Telegram 通知用户。"""
        if not self.telegram_channel:
            return
        try:
            if event in ("pending_approval", "pending_discussion"):
                await self.telegram_channel.send_proposal(proposal)
            else:
                # executed — 发送效果通知
                await self.telegram_channel.send_message(
                    text=f"提案 {proposal.get('proposal_id')} 已执行。\n方案：{proposal.get('solution', '')}",
                    message_type="architect",
                )
        except Exception as exc:
            logger.error("Telegram notification failed: %s", exc)

    async def _run_council_if_needed(self, proposal: dict) -> CouncilReview | None:
        """运行 Council 审议，失败时返回 None（不阻塞流程）。"""
        try:
            return await run_council_review(proposal, self.llm_client)
        except Exception as exc:
            logger.error("Council review failed for %s: %s", proposal.get("proposal_id"), exc)
            return None

    @staticmethod
    def _council_review_to_dict(council_review: CouncilReview) -> dict:
        """将 CouncilReview 转换为可序列化的 dict。"""
        return {
            "proposal_id": council_review.proposal_id,
            "conclusion": council_review.conclusion,
            "summary": council_review.summary,
            "reviews": [
                {
                    "role": r.role,
                    "name": r.name,
                    "concern": r.concern,
                    "recommendation": r.recommendation,
                }
                for r in council_review.reviews
            ],
        }

    async def _notify_council(self, proposal: dict, council_review: CouncilReview) -> None:
        """发送 Council 审议摘要通知。"""
        if not self.telegram_channel:
            return
        try:
            summary_text = (
                f"Council 审议结果：{council_review.conclusion}\n"
                f"提案 {proposal.get('proposal_id')}：{proposal.get('problem', '')}\n"
                f"摘要：{council_review.summary}"
            )
            await self.telegram_channel.send_message(
                text=summary_text,
                message_type="council",
            )
        except Exception as exc:
            logger.error("Council Telegram notification failed: %s", exc)

    @staticmethod
    def _try_parse_json(text: str) -> Any:
        """尝试解析 JSON，失败返回 None。"""
        try:
            return json.loads(text)
        except (json.JSONDecodeError, ValueError):
            return None
