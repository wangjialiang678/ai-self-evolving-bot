"""Conversation compaction engine (A6)."""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path

from core.llm_client import BaseLLMClient

logger = logging.getLogger(__name__)

_SUMMARY_SYSTEM_PROMPT = """你是一个对话压缩器。将以下对话历史压缩为简洁摘要。

要求：
1. 保留所有关键决策和结论
2. 保留重要的事实信息（数字、日期、名称）
3. 保留未完成的任务和待办事项
4. 去除寒暄、重复、中间推理过程
5. 使用认知层级转化：事实 → 规律 → 策略
6. 压缩为原文的 10-20%

输出格式：纯文本摘要，不要 JSON。"""

_FLUSH_SYSTEM_PROMPT = """从以下对话中提取值得长期记住的信息。

按 JSON 数组格式输出：
[
  {"type": "decision", "content": "用户决定使用 React 而非 Vue"},
  {"type": "fact", "content": "项目截止日期是 3 月 15 日"},
  {"type": "preference", "content": "用户偏好简短回答"},
  {"type": "todo", "content": "需要调研 NanoBot 的 Cron 机制"}
]

如果没有值得提取的信息，返回空数组 []。"""


class CompactionEngine:
    """Compacts long conversation history when token usage approaches budget."""

    def __init__(self, llm_client: BaseLLMClient | None, memory_dir: str):
        """
        Args:
            llm_client: LLM client.
            memory_dir: ``workspace/memory`` path.
        """
        self.llm_client = llm_client
        self.memory_dir = Path(memory_dir)
        self.user_memory_dir = self.memory_dir / "user"
        self.user_memory_dir.mkdir(parents=True, exist_ok=True)
        self.flush_log_path = self.user_memory_dir / "compaction_flush.jsonl"

    def should_compact(self, current_tokens: int, budget: int) -> bool:
        """Return ``True`` when current usage reaches >=85% of budget."""
        if budget <= 0:
            return False
        return (current_tokens / budget) >= 0.85

    async def compact(self, conversation_history: list[dict], keep_recent: int = 5) -> dict:
        """
        Compact conversation history and preserve recent rounds.

        Args:
            conversation_history: full message history.
            keep_recent: keep last N rounds (1 round = user + assistant).
        """
        original_tokens = self._estimate_messages_tokens(conversation_history)
        keep_recent = max(keep_recent, 0)
        keep_count = keep_recent * 2

        if len(conversation_history) <= keep_count:
            stats = {
                "original_tokens": original_tokens,
                "compacted_tokens": original_tokens,
                "compression_ratio": 1.0,
                "key_decisions_preserved": 0,
                "key_decisions_total": 0,
            }
            return {
                "compacted_history": conversation_history,
                "compressed_history": conversation_history,
                "summary": "",
                "flushed_to_memory": [],
                "stats": stats,
                **stats,
            }

        old_messages = conversation_history[:-keep_count] if keep_count > 0 else conversation_history
        recent_messages = conversation_history[-keep_count:] if keep_count > 0 else []

        flushed_items = await self._flush_to_memory(old_messages)
        summary = await self._summarize(old_messages)

        summary_message = {
            "role": "system",
            "type": "summary",
            "content": summary,
            "timestamp": datetime.now().replace(microsecond=0).isoformat(),
        }
        compacted_history = [summary_message, *recent_messages]

        compacted_tokens = self._estimate_messages_tokens(compacted_history)
        compression_ratio = (compacted_tokens / original_tokens) if original_tokens > 0 else 1.0

        verification = await self.verify_compaction(
            original=old_messages,
            compacted={
                "summary": summary,
                "flushed_to_memory": flushed_items,
            },
        )

        stats = {
            "original_tokens": original_tokens,
            "compacted_tokens": compacted_tokens,
            "compression_ratio": compression_ratio,
            "key_decisions_preserved": verification["key_decisions_preserved"],
            "key_decisions_total": verification["key_decisions_total"],
        }

        return {
            "compacted_history": compacted_history,
            "compressed_history": compacted_history,
            "summary": summary,
            "flushed_to_memory": flushed_items,
            "stats": stats,
            **stats,
        }

    async def _flush_to_memory(self, messages: list[dict]) -> list[dict]:
        """
        Extract key entries from old messages and append to memory log.

        Returns:
            Extracted entries list.
        """
        if not messages or self.llm_client is None:
            return []

        user_message = self._messages_to_text(messages)
        extracted = []

        try:
            raw = await self.llm_client.complete(
                system_prompt=_FLUSH_SYSTEM_PROMPT,
                user_message=user_message,
                model="gemini-flash",
                max_tokens=800,
            )
            extracted = self._parse_json_array(raw)
        except Exception as exc:  # pragma: no cover - defensive logging
            logger.error("Flush-to-memory call failed: %s", exc)
            extracted = []

        if not extracted:
            return []

        now = datetime.now().replace(microsecond=0).isoformat()
        try:
            with self.flush_log_path.open("a", encoding="utf-8") as f:
                for item in extracted:
                    payload = {
                        "timestamp": now,
                        "type": item.get("type"),
                        "content": item.get("content"),
                    }
                    f.write(json.dumps(payload, ensure_ascii=False) + "\n")
        except Exception as exc:  # pragma: no cover - defensive logging
            logger.error("Failed to write compaction flush log: %s", exc)

        return extracted

    async def verify_compaction(self, original: list[dict], compacted: dict) -> dict:
        """
        Verify whether key decisions were preserved after compaction.

        Returns:
            Quality assessment dict.
        """
        decisions = self._extract_key_decisions(original)
        key_total = len(decisions)
        if key_total == 0:
            return {
                "quality": "good",
                "missing_key_info": [],
                "key_decisions_preserved": 0,
                "key_decisions_total": 0,
            }

        summary_text = str(compacted.get("summary", "") or "")
        flushed = compacted.get("flushed_to_memory", [])
        flushed_text = " ".join(str(item.get("content", "")) for item in flushed if isinstance(item, dict))
        target_text = f"{summary_text} {flushed_text}"

        preserved = 0
        missing: list[str] = []
        for decision in decisions:
            if decision in target_text:
                preserved += 1
            else:
                missing.append(decision)

        ratio = preserved / key_total
        if ratio >= 1.0:
            quality = "good"
        elif ratio >= 0.7:
            quality = "acceptable"
        else:
            quality = "poor"

        return {
            "quality": quality,
            "missing_key_info": missing,
            "key_decisions_preserved": preserved,
            "key_decisions_total": key_total,
        }

    async def _summarize(self, messages: list[dict]) -> str:
        """Generate summary text for old messages with graceful fallback."""
        if not messages:
            return ""
        text = self._messages_to_text(messages)
        if self.llm_client is None:
            return text[:500]
        try:
            raw = await self.llm_client.complete(
                system_prompt=_SUMMARY_SYSTEM_PROMPT,
                user_message=text,
                model="gemini-flash",
                max_tokens=1200,
            )
            summary = (raw or "").strip()
            if summary:
                return summary
        except Exception as exc:  # pragma: no cover - defensive logging
            logger.error("Compaction summary call failed: %s", exc)
        return text[:500]

    @staticmethod
    def _messages_to_text(messages: list[dict]) -> str:
        """Serialize message list into compact plain text."""
        parts = []
        for msg in messages:
            role = msg.get("role", "unknown")
            content = msg.get("content", "")
            timestamp = msg.get("timestamp", "")
            parts.append(f"[{timestamp}] {role}: {content}")
        return "\n".join(parts)

    @staticmethod
    def _estimate_messages_tokens(messages: list[dict]) -> int:
        """Estimate tokens from message contents using a lightweight heuristic."""
        total_chars = 0
        non_ascii_chars = 0
        for msg in messages:
            text = str(msg.get("content", "") or "")
            total_chars += len(text)
            non_ascii_chars += sum(1 for ch in text if ord(ch) > 127)

        if total_chars == 0:
            return 0

        # Heuristic: mostly ASCII -> /4, mixed/CJK -> /2
        if non_ascii_chars / total_chars > 0.2:
            return max(1, total_chars // 2)
        return max(1, total_chars // 4)

    @staticmethod
    def _parse_json_array(raw: str) -> list[dict]:
        """Parse LLM response as JSON list with tolerant extraction."""
        if not raw:
            return []
        text = raw.strip()
        try:
            parsed = json.loads(text)
            if isinstance(parsed, list):
                return [item for item in parsed if isinstance(item, dict)]
        except json.JSONDecodeError:
            pass

        start = text.find("[")
        end = text.rfind("]")
        if start == -1 or end == -1 or end <= start:
            return []
        try:
            parsed = json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            return []
        if not isinstance(parsed, list):
            return []
        return [item for item in parsed if isinstance(item, dict)]

    @staticmethod
    def _extract_key_decisions(messages: list[dict]) -> list[str]:
        """
        Extract candidate key decisions from raw messages.

        This is intentionally heuristic to avoid extra model calls in verification.
        """
        keywords = ("决定", "决定用", "决定使用", "deadline", "截止", "TODO", "待办")
        extracted: list[str] = []
        for msg in messages:
            content = str(msg.get("content", "") or "")
            if not content:
                continue
            if any(key in content for key in keywords):
                extracted.append(content[:80])
        # De-duplicate preserving order.
        seen = set()
        unique = []
        for item in extracted:
            if item in seen:
                continue
            seen.add(item)
            unique.append(item)
        return unique
