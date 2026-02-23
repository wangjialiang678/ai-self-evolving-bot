"""Observer engine: lightweight post-task observations and deep reports."""

from __future__ import annotations

import json
import logging
from datetime import date, datetime
from pathlib import Path

from core.llm_client import BaseLLMClient

logger = logging.getLogger(__name__)

_LIGHT_SYSTEM_PROMPT = """你是 Observer 的轻量模式。为以下任务写一行观察笔记。

输出格式（纯文本，一行，不超过 100 字）：
[观察到的关键信息，如异常、模式、值得注意的点]

如果任务完全正常，输出 "正常完成"。"""

_DEEP_SYSTEM_PROMPT = """你是 Observer（观察者），一个系统运行状况分析师。
你的职责是观察和报告，不做修改决策。

分析以下数据，识别值得关注的模式和问题。

重点关注（按优先级）：
1. 真正的错误模式（错误假设、遗漏考虑）— 不是偏好偏差
2. 系统效率问题（token 浪费、重复劳动）
3. 技能和知识缺口
4. 用户偏好变化（最低优先级，简单记录即可）

请按以下 JSON 格式输出：
{
  "tasks_analyzed": 12,
  "key_findings": [
    {
      "type": "error_pattern 或 efficiency 或 skill_gap 或 preference",
      "description": "具体发现",
      "confidence": "HIGH 或 MEDIUM 或 LOW",
      "evidence": ["task_028 纠正", "task_033 纠正"],
      "recommendation": "建议的改进方向（给 Architect 参考）"
    }
  ],
  "overall_health": "good 或 degraded 或 critical"
}

key_findings 按优先级排序（error_pattern 最高）。"""

_FINDING_PRIORITY = {
    "error_pattern": 0,
    "efficiency": 1,
    "skill_gap": 2,
    "preference": 3,
}


class ObserverEngine:
    """Observer engine for lightweight and deep analysis modes."""

    def __init__(
        self,
        llm_client_gemini: BaseLLMClient,
        llm_client_opus: BaseLLMClient,
        workspace_path: str,
    ):
        """
        Args:
            llm_client_gemini: lightweight mode model client.
            llm_client_opus: deep analysis model client.
            workspace_path: path to ``workspace``.
        """
        self.llm_client_gemini = llm_client_gemini
        self.llm_client_opus = llm_client_opus
        self.workspace_path = Path(workspace_path)

        self.light_logs_dir = self.workspace_path / "observations" / "light_logs"
        self.deep_reports_dir = self.workspace_path / "observations" / "deep_reports"
        self.signals_path = self.workspace_path / "signals" / "active.jsonl"
        self.rules_dir = self.workspace_path / "rules"

        self.light_logs_dir.mkdir(parents=True, exist_ok=True)
        self.deep_reports_dir.mkdir(parents=True, exist_ok=True)
        self.signals_path.parent.mkdir(parents=True, exist_ok=True)
        self.signals_path.touch(exist_ok=True)

    async def lightweight_observe(self, task_trace: dict, reflection_output: dict | None = None) -> dict:
        """
        Write one lightweight observation log after each task.

        Args:
            task_trace: task execution trace.
            reflection_output: optional reflection output.
        """
        task_id = str(task_trace.get("task_id", "unknown_task"))
        tokens = int(task_trace.get("tokens_used", 0) or 0)
        model = str(task_trace.get("model", "unknown"))

        outcome = "SUCCESS"
        error_type = None
        signals: list[str] = []
        if reflection_output:
            outcome = str(reflection_output.get("outcome", "SUCCESS"))
            ref_type = reflection_output.get("type")
            error_type = ref_type if ref_type in ("ERROR", "PREFERENCE") else None
            if ref_type == "ERROR":
                signals.append("task_failure")
            elif ref_type == "PREFERENCE":
                signals.append("user_pattern")
        elif task_trace.get("user_feedback"):
            outcome = "PARTIAL"
            signals.append("user_pattern")

        user_prompt = (
            f"任务ID: {task_id}\n"
            f"用户消息: {task_trace.get('user_message', '')}\n"
            f"系统回复: {str(task_trace.get('system_response', '') or '')[:500]}\n"
            f"用户反馈: {task_trace.get('user_feedback') if task_trace.get('user_feedback') is not None else '无'}\n"
            f"反思输出: {reflection_output if reflection_output is not None else '无'}"
        )

        note = "正常完成"
        try:
            llm_note = await self.llm_client_gemini.complete(
                system_prompt=_LIGHT_SYSTEM_PROMPT,
                user_message=user_prompt,
                model="gemini-flash",
                max_tokens=120,
            )
            if llm_note and llm_note.strip():
                note = llm_note.strip().splitlines()[0][:100]
        except Exception as exc:  # pragma: no cover - defensive logging
            logger.error("Lightweight observe call failed: %s", exc)

        now = datetime.now().replace(microsecond=0)
        light_log = {
            "timestamp": now.isoformat(),
            "task_id": task_id,
            "outcome": outcome,
            "tokens": tokens,
            "model": model,
            "signals": signals,
            "error_type": error_type,
            "note": note or "正常完成",
        }

        path = self.light_logs_dir / f"{date.today().isoformat()}.jsonl"
        self._append_jsonl(path, light_log)
        return light_log

    async def deep_analyze(self, trigger: str = "daily") -> dict:
        """
        Generate deep analysis report from today's observations and active signals.

        Args:
            trigger: ``daily`` or ``emergency``.
        """
        today = date.today().isoformat()
        light_logs = self._read_jsonl(self.light_logs_dir / f"{today}.jsonl")
        active_signals = self._read_jsonl(self.signals_path)
        rule_files = self._list_rule_files()

        user_message = (
            "=== 今日轻量观察日志 ===\n"
            f"{json.dumps(light_logs, ensure_ascii=False)}\n\n"
            "=== 活跃信号 ===\n"
            f"{json.dumps(active_signals, ensure_ascii=False)}\n\n"
            "=== 当前规则文件列表 ===\n"
            f"{json.dumps(rule_files, ensure_ascii=False)}\n\n"
            f"触发方式: {trigger}"
        )

        parsed = None
        try:
            raw = await self.llm_client_opus.complete(
                system_prompt=_DEEP_SYSTEM_PROMPT,
                user_message=user_message,
                model="opus",
                max_tokens=2000,
            )
            parsed = self._parse_json_object(raw)
        except Exception as exc:  # pragma: no cover - defensive logging
            logger.error("Deep analyze LLM call failed: %s", exc)

        if parsed is None:
            parsed = {
                "tasks_analyzed": len(light_logs),
                "key_findings": [],
                "overall_health": "good",
            }

        findings = parsed.get("key_findings", [])
        if not isinstance(findings, list):
            findings = []
        normalized_findings = []
        for idx, finding in enumerate(findings, start=1):
            if not isinstance(finding, dict):
                continue
            normalized_findings.append(
                {
                    "finding_id": finding.get("finding_id") or f"f_{idx:03d}",
                    "type": finding.get("type", "preference"),
                    "description": finding.get("description", ""),
                    "confidence": finding.get("confidence", "LOW"),
                    "evidence": finding.get("evidence", []),
                    "recommendation": finding.get("recommendation", ""),
                }
            )
        normalized_findings.sort(key=lambda f: _FINDING_PRIORITY.get(str(f.get("type")), 99))

        report = {
            "trigger": trigger,
            "date": today,
            "tasks_analyzed": int(parsed.get("tasks_analyzed", len(light_logs)) or 0),
            "key_findings": normalized_findings,
            "overall_health": str(parsed.get("overall_health", "good")),
        }

        markdown = self._render_markdown_report(report, light_logs, active_signals)
        report_path = self.deep_reports_dir / f"{today}.md"
        report_path.write_text(markdown, encoding="utf-8")
        return report

    def _list_rule_files(self) -> list[str]:
        """Return current rule markdown files under workspace/rules."""
        if not self.rules_dir.exists():
            return []
        return sorted(str(path.relative_to(self.workspace_path)) for path in self.rules_dir.rglob("*.md"))

    @staticmethod
    def _append_jsonl(path: Path, payload: dict) -> None:
        """Append one JSON record to JSONL file."""
        try:
            with path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(payload, ensure_ascii=False) + "\n")
        except Exception as exc:  # pragma: no cover - defensive logging
            logger.error("Failed to append JSONL %s: %s", path, exc)

    @staticmethod
    def _read_jsonl(path: Path) -> list[dict]:
        """Read JSONL file while skipping invalid lines."""
        if not path.exists():
            return []
        rows: list[dict] = []
        try:
            with path.open("r", encoding="utf-8") as f:
                for line in f:
                    raw = line.strip()
                    if not raw:
                        continue
                    try:
                        item = json.loads(raw)
                    except json.JSONDecodeError:
                        logger.warning("Invalid JSONL line skipped: %s", path)
                        continue
                    if isinstance(item, dict):
                        rows.append(item)
        except Exception as exc:  # pragma: no cover - defensive logging
            logger.error("Failed to read JSONL %s: %s", path, exc)
            return []
        return rows

    @staticmethod
    def _parse_json_object(raw: str) -> dict | None:
        """Parse a dict from model output with best-effort extraction."""
        if not raw:
            return None
        text = raw.strip()
        try:
            parsed = json.loads(text)
            return parsed if isinstance(parsed, dict) else None
        except json.JSONDecodeError:
            pass

        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end == -1 or end <= start:
            return None
        try:
            parsed = json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            return None
        return parsed if isinstance(parsed, dict) else None

    @staticmethod
    def _render_markdown_report(report: dict, light_logs: list[dict], active_signals: list[dict]) -> str:
        """Render deep report markdown content."""
        tasks_total = len(light_logs)
        success = len([row for row in light_logs if row.get("outcome") == "SUCCESS"])
        partial = len([row for row in light_logs if row.get("outcome") == "PARTIAL"])
        failure = len([row for row in light_logs if row.get("outcome") == "FAILURE"])
        critical = len([row for row in active_signals if row.get("priority") == "CRITICAL"])
        high = len([row for row in active_signals if row.get("priority") == "HIGH"])
        tokens = sum(int(row.get("tokens", 0) or 0) for row in light_logs)

        lines = [
            f"# Observer 深度报告 — {report['date']}",
            "",
            f"> 触发方式: {report['trigger']}",
            f"> 分析任务数: {report['tasks_analyzed']}",
            f"> 系统健康度: {report['overall_health']}",
            "",
            "## 关键发现",
            "",
        ]
        findings = report.get("key_findings", [])
        if findings:
            for idx, finding in enumerate(findings, start=1):
                lines.extend(
                    [
                        f"### {idx}. [{finding.get('type')}] {finding.get('description')}",
                        f"- **置信度**: {finding.get('confidence')}",
                        f"- **证据**: {finding.get('evidence')}",
                        f"- **建议**: {finding.get('recommendation')}",
                        "",
                    ]
                )
        else:
            lines.extend(["暂无高置信度发现。", ""])

        lines.extend(
            [
                "## 数据概览",
                f"- 今日任务: {tasks_total} (成功 {success}, 部分 {partial}, 失败 {failure})",
                f"- 信号: {len(active_signals)} 条 (CRITICAL: {critical}, HIGH: {high})",
                f"- Token 消耗: {tokens}",
                "",
            ]
        )

        return "\n".join(lines)
