"""Task-level reflection engine (A5)."""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path

from core.llm_client import BaseLLMClient

logger = logging.getLogger(__name__)

_VALID_TYPES = {"ERROR", "PREFERENCE", "NONE"}
_VALID_OUTCOMES = {"SUCCESS", "PARTIAL", "FAILURE"}
_VALID_ROOT_CAUSES = {
    "wrong_assumption",
    "missed_consideration",
    "tool_misuse",
    "knowledge_gap",
}

_SYSTEM_PROMPT = """你是一个反思引擎。分析以下任务执行轨迹，提取教训。

请严格按以下 JSON 格式输出（不要添加任何其他文字）：
{
  "type": "ERROR 或 PREFERENCE 或 NONE",
  "outcome": "SUCCESS 或 PARTIAL 或 FAILURE",
  "lesson": "一句话总结教训",
  "root_cause": "wrong_assumption 或 missed_consideration 或 tool_misuse 或 knowledge_gap 或 null",
  "reusable_experience": "可复用的经验，或 null"
}

分类规则：
- ERROR: 有正确答案但做错了（错误假设、遗漏关键考虑、工具误用、知识不足）
- PREFERENCE: 没有标准答案，只是不符合用户习惯（回复太长、格式不合口味、语气偏差）
- NONE: 无异常

如果是 ERROR，必须填写 root_cause。
如果是 PREFERENCE 或 NONE，root_cause 填 null。"""


class ReflectionEngine:
    """Run lightweight post-task reflection with Gemini Flash-compatible model."""

    def __init__(self, llm_client: BaseLLMClient, memory_dir: str):
        """
        Args:
            llm_client: LLM client (mock in tests).
            memory_dir: ``workspace/memory`` path.
        """
        self.llm_client = llm_client
        self.memory_dir = Path(memory_dir)
        self.user_dir = self.memory_dir / "user"
        self.user_dir.mkdir(parents=True, exist_ok=True)

        self.reflections_log = self.user_dir / "reflections.jsonl"
        self.preferences_md = self.user_dir / "preferences.md"
        self.error_log_jsonl = self.user_dir / "error_log.jsonl"

        self.rules_experience_dir = self.memory_dir.parent / "rules" / "experience"
        self.error_patterns_md = self.rules_experience_dir / "error_patterns.md"

    async def lightweight_reflect(self, task_trace: dict) -> dict:
        """
        Analyze one task trace and extract reflection.

        The method always returns a valid dict and never raises.
        """
        task_id = str(task_trace.get("task_id", "unknown_task"))
        user_message = str(task_trace.get("user_message", "") or "")
        system_response = str(task_trace.get("system_response", "") or "")
        user_feedback = task_trace.get("user_feedback")
        tools_used = task_trace.get("tools_used", [])
        tokens_used = task_trace.get("tokens_used", 0)
        duration_ms = task_trace.get("duration_ms", 0)

        user_prompt = (
            f"任务ID: {task_id}\n"
            f"用户消息: {user_message}\n"
            f"系统回复: {system_response[:500]}\n"
            f"用户反馈: {user_feedback if user_feedback is not None else '无'}\n"
            f"使用工具: {tools_used}\n"
            f"消耗 token: {tokens_used}\n"
            f"耗时: {duration_ms}ms"
        )

        fallback = self._fallback_result(task_id)

        try:
            llm_raw = await self.llm_client.complete(
                system_prompt=_SYSTEM_PROMPT,
                user_message=user_prompt,
                model="gemini-flash",
                max_tokens=500,
            )
        except Exception as exc:  # pragma: no cover - defensive logging
            logger.error("Reflection LLM call failed: %s", exc)
            result = fallback
            self.write_reflection(result)
            return result

        parsed = self._parse_llm_output(llm_raw)
        if parsed is None:
            result = fallback
        else:
            result = self._normalize_result(task_id, parsed)

        self.write_reflection(result)
        return result

    def write_reflection(self, reflection: dict) -> None:
        """
        Persist reflection outputs by type.

        - ``ERROR`` -> append to ``rules/experience/error_patterns.md``
          and ``memory/user/error_log.jsonl`` (compat log).
        - ``PREFERENCE`` -> append to ``memory/user/preferences.md``.
        - all types -> append to ``memory/user/reflections.jsonl``.
        """
        self.user_dir.mkdir(parents=True, exist_ok=True)
        self.rules_experience_dir.mkdir(parents=True, exist_ok=True)

        safe_reflection = dict(reflection)
        safe_reflection.setdefault("timestamp", datetime.now().replace(microsecond=0).isoformat())

        # All reflections -> reflections.jsonl
        try:
            with self.reflections_log.open("a", encoding="utf-8") as f:
                f.write(json.dumps(safe_reflection, ensure_ascii=False) + "\n")
        except Exception as exc:  # pragma: no cover - defensive logging
            logger.error("Failed to write reflections.jsonl: %s", exc)

        reflect_type = str(safe_reflection.get("type", "NONE")).upper()
        lesson = str(safe_reflection.get("lesson", "") or "")
        task_id = str(safe_reflection.get("task_id", "unknown_task"))

        if reflect_type == "PREFERENCE":
            try:
                if not self.preferences_md.exists():
                    self.preferences_md.write_text("# 用户偏好\n\n", encoding="utf-8")
                with self.preferences_md.open("a", encoding="utf-8") as f:
                    f.write(f"- {safe_reflection['timestamp']} [{task_id}] {lesson}\n")
            except Exception as exc:  # pragma: no cover - defensive logging
                logger.error("Failed to write preferences.md: %s", exc)

        if reflect_type == "ERROR":
            # Compatibility log for test/doc variations.
            try:
                with self.error_log_jsonl.open("a", encoding="utf-8") as f:
                    f.write(json.dumps(safe_reflection, ensure_ascii=False) + "\n")
            except Exception as exc:  # pragma: no cover - defensive logging
                logger.error("Failed to write error_log.jsonl: %s", exc)

            try:
                if not self.error_patterns_md.exists():
                    self.error_patterns_md.write_text("# 错误模式\n\n", encoding="utf-8")
                with self.error_patterns_md.open("a", encoding="utf-8") as f:
                    root = safe_reflection.get("root_cause")
                    f.write(f"- {safe_reflection['timestamp']} [{task_id}] ({root}) {lesson}\n")
            except Exception as exc:  # pragma: no cover - defensive logging
                logger.error("Failed to write error_patterns.md: %s", exc)

    @staticmethod
    def _fallback_result(task_id: str) -> dict:
        """Default reflection payload when LLM output is invalid."""
        return {
            "task_id": task_id,
            "type": "NONE",
            "outcome": "SUCCESS",
            "lesson": "reflection_failed",
            "root_cause": None,
            "reusable_experience": None,
        }

    @staticmethod
    def _parse_llm_output(text: str) -> dict | None:
        """Parse JSON response, including best-effort extraction from mixed text."""
        if not text:
            return None

        stripped = text.strip()
        try:
            data = json.loads(stripped)
            return data if isinstance(data, dict) else None
        except json.JSONDecodeError:
            pass

        start = stripped.find("{")
        end = stripped.rfind("}")
        if start == -1 or end == -1 or end <= start:
            return None
        try:
            data = json.loads(stripped[start : end + 1])
        except json.JSONDecodeError:
            return None
        return data if isinstance(data, dict) else None

    @staticmethod
    def _normalize_result(task_id: str, parsed: dict) -> dict:
        """Normalize parsed LLM JSON to strict schema."""
        ref_type = str(parsed.get("type", "NONE")).upper()
        if ref_type not in _VALID_TYPES:
            ref_type = "NONE"

        outcome = str(parsed.get("outcome", "SUCCESS")).upper()
        if outcome not in _VALID_OUTCOMES:
            outcome = "SUCCESS"

        lesson = str(parsed.get("lesson", "") or "").strip() or "reflection_failed"
        root_cause = parsed.get("root_cause")
        reusable_experience = parsed.get("reusable_experience")

        if ref_type == "ERROR":
            if root_cause not in _VALID_ROOT_CAUSES:
                root_cause = "knowledge_gap"
        else:
            root_cause = None

        if reusable_experience is not None:
            reusable_experience = str(reusable_experience).strip() or None

        return {
            "task_id": task_id,
            "type": ref_type,
            "outcome": outcome,
            "lesson": lesson,
            "root_cause": root_cause,
            "reusable_experience": reusable_experience,
        }
