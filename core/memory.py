"""记忆系统 — 分层存储、关键词检索、上下文注入。

四层记忆架构：
- 工作记忆：上下文窗口（由 ContextEngine 管理）
- 情节记忆：对话记录 (conversations/)
- 语义记忆：核心知识 (MEMORY.md, preferences.md, profile.md)
- 程序性记忆：经验规则 + 技能 (rules/experience/, skills/)

两个维度：
- 用户级：跨项目共享 (memory/user/)
- 项目级：项目特定 (memory/projects/{project}/)
"""

import json
import logging
import re
from datetime import datetime, timedelta
from pathlib import Path

logger = logging.getLogger(__name__)


class MemoryStore:
    """分级记忆系统 — 存储、检索、注入上下文。

    MVP 阶段使用关键词全文搜索，后续可升级为向量检索。
    """

    def __init__(self, workspace_path: str | Path):
        """
        Args:
            workspace_path: workspace/ 根目录路径
        """
        self.workspace = Path(workspace_path)
        self.user_dir = self.workspace / "memory" / "user"
        self.projects_dir = self.workspace / "memory" / "projects"
        self.conversations_dir = self.workspace / "memory" / "conversations"
        self.summaries_dir = self.workspace / "memory" / "daily_summaries"
        self._ensure_dirs()

    def _ensure_dirs(self):
        """确保目录结构存在。"""
        for d in [self.user_dir, self.projects_dir,
                  self.conversations_dir, self.summaries_dir]:
            d.mkdir(parents=True, exist_ok=True)

    # ──────────────────────────────────────
    #  写入
    # ──────────────────────────────────────

    def save_user_memory(self, key: str, content: str) -> Path:
        """写入/更新用户级记忆。

        Args:
            key: 文件名（不含 .md），如 "profile", "preferences", "MEMORY"
            content: Markdown 内容

        Returns:
            写入的文件路径
        """
        path = self.user_dir / f"{key}.md"
        path.write_text(content, encoding="utf-8")
        logger.info(f"User memory saved: {key} ({len(content)} chars)")
        return path

    def save_project_memory(self, project: str, key: str, content: str) -> Path:
        """写入/更新项目级记忆。

        Args:
            project: 项目标识符
            key: 文件名（不含 .md），如 "context", "strategies"
            content: Markdown 内容

        Returns:
            写入的文件路径
        """
        proj_dir = self.projects_dir / project
        proj_dir.mkdir(parents=True, exist_ok=True)
        path = proj_dir / f"{key}.md"
        path.write_text(content, encoding="utf-8")
        logger.info(f"Project memory saved: {project}/{key} ({len(content)} chars)")
        return path

    def append_preference(self, preference: str) -> None:
        """追加一条用户偏好到 preferences.md。

        Args:
            preference: 偏好描述（一行文本）
        """
        path = self.user_dir / "preferences.md"
        timestamp = datetime.now().strftime("%Y-%m-%d")

        if not path.exists():
            path.write_text(
                "# 用户偏好\n\n> 由系统从交互中自动提取。\n\n",
                encoding="utf-8",
            )

        with open(path, "a", encoding="utf-8") as f:
            f.write(f"- [{timestamp}] {preference}\n")
        logger.info(f"Preference appended: {preference[:50]}...")

    def append_error_pattern(self, pattern: str, source: str = "") -> None:
        """追加一条错误模式（来自反思引擎）。

        Args:
            pattern: 错误描述
            source: 来源（如 task_id）
        """
        path = self.user_dir / "error_patterns.md"
        timestamp = datetime.now().strftime("%Y-%m-%d")

        if not path.exists():
            path.write_text(
                "# 已发现的错误模式\n\n> 由反思引擎自动提取。\n\n",
                encoding="utf-8",
            )

        with open(path, "a", encoding="utf-8") as f:
            source_tag = f" (from {source})" if source else ""
            f.write(f"- [{timestamp}]{source_tag} {pattern}\n")
        logger.info(f"Error pattern appended: {pattern[:50]}...")

    def save_conversation(
        self,
        conversation_id: str,
        messages: list[dict],
        metadata: dict | None = None,
    ) -> Path:
        """保存对话记录。

        Args:
            conversation_id: 对话 ID
            messages: [{"role": "user"|"assistant", "content": "...", ...}]
            metadata: 对话元数据（摘要、标签等）

        Returns:
            保存的文件路径
        """
        record = {
            "conversation_id": conversation_id,
            "timestamp": datetime.now().isoformat(),
            "messages": messages,
            "metadata": metadata or {},
        }
        path = self.conversations_dir / f"{conversation_id}.json"
        path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
        logger.info(f"Conversation saved: {conversation_id} ({len(messages)} messages)")
        return path

    def save_daily_summary(self, date: str, summary: str) -> Path:
        """保存每日摘要。

        Args:
            date: 日期字符串 YYYY-MM-DD
            summary: Markdown 格式摘要

        Returns:
            保存的文件路径
        """
        path = self.summaries_dir / f"{date}.md"
        path.write_text(summary, encoding="utf-8")
        logger.info(f"Daily summary saved: {date}")
        return path

    # ──────────────────────────────────────
    #  检索
    # ──────────────────────────────────────

    def search(
        self,
        query: str,
        scope: str = "all",
        project: str | None = None,
        max_results: int = 5,
    ) -> list[dict]:
        """基于关键词搜索相关记忆。

        MVP 使用子串匹配 + 中文 bigram 重叠评分。

        Args:
            query: 搜索查询
            scope: "all" | "user" | "project" | "conversations" | "summaries"
            project: 项目名（scope="project" 时必需）
            max_results: 最大返回数

        Returns:
            [{"source": 文件路径, "content": 匹配片段, "score": 相关性分数}]
        """
        candidates = []

        if scope in ("all", "user"):
            candidates.extend(self._scan_dir(self.user_dir, "*.md"))

        if scope in ("all", "project") and project:
            proj_dir = self.projects_dir / project
            if proj_dir.exists():
                candidates.extend(self._scan_dir(proj_dir, "*.md"))

        if scope in ("all", "summaries"):
            candidates.extend(self._scan_dir(self.summaries_dir, "*.md"))

        if scope in ("all", "conversations"):
            candidates.extend(self._scan_conversations(query))

        # 评分并排序
        scored = []
        for candidate in candidates:
            score = self._relevance_score(query, candidate["content"])
            if score > 0:
                scored.append({
                    "source": candidate["source"],
                    "content": candidate["content"],
                    "score": score,
                })

        scored.sort(key=lambda x: x["score"], reverse=True)
        return scored[:max_results]

    def get_relevant_memories(
        self,
        query: str,
        project: str | None = None,
        max_results: int = 5,
    ) -> list[str]:
        """获取与查询相关的记忆片段（用于上下文注入）。

        这是给 ContextEngine.assemble(memories=...) 用的便捷方法。

        Args:
            query: 当前任务/消息文本
            project: 当前项目名
            max_results: 最大返回数

        Returns:
            相关记忆片段的文本列表
        """
        results = self.search(query, scope="all", project=project, max_results=max_results)
        return [r["content"] for r in results]

    def get_user_preferences(self) -> str:
        """获取用户偏好摘要（用于上下文注入）。"""
        path = self.user_dir / "preferences.md"
        if not path.exists():
            return ""
        return path.read_text(encoding="utf-8")

    def get_user_profile(self) -> str:
        """获取用户画像。"""
        path = self.user_dir / "profile.md"
        if not path.exists():
            return ""
        return path.read_text(encoding="utf-8")

    def get_semantic_memory(self) -> str:
        """获取核心语义记忆 (MEMORY.md)。"""
        path = self.user_dir / "MEMORY.md"
        if not path.exists():
            return ""
        return path.read_text(encoding="utf-8")

    def get_recent_errors(self, days: int = 7) -> str:
        """获取最近 N 天的错误模式。

        Args:
            days: 回溯天数

        Returns:
            最近的错误模式文本
        """
        path = self.user_dir / "error_patterns.md"
        if not path.exists():
            return ""

        content = path.read_text(encoding="utf-8")
        cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")

        # 过滤最近 N 天的条目
        recent_lines = []
        for line in content.split("\n"):
            # 匹配 - [YYYY-MM-DD] 格式
            match = re.match(r"^- \[(\d{4}-\d{2}-\d{2})\]", line)
            if match:
                if match.group(1) >= cutoff:
                    recent_lines.append(line)
            elif not line.startswith("- ["):
                # 保留标题和非条目行
                recent_lines.append(line)

        return "\n".join(recent_lines).strip()

    def get_project_context(self, project: str) -> str:
        """获取项目上下文。"""
        path = self.projects_dir / project / "context.md"
        if not path.exists():
            return ""
        return path.read_text(encoding="utf-8")

    def get_daily_summary(self, date: str) -> str | None:
        """获取某日摘要。"""
        path = self.summaries_dir / f"{date}.md"
        if not path.exists():
            return None
        return path.read_text(encoding="utf-8")

    def list_conversations(self, limit: int = 20) -> list[dict]:
        """列出最近的对话记录。

        Returns:
            [{"conversation_id": "...", "timestamp": "...", "message_count": N}]
        """
        files = sorted(
            self.conversations_dir.glob("*.json"),
            key=lambda f: f.stat().st_mtime,
            reverse=True,
        )[:limit]

        result = []
        for f in files:
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                result.append({
                    "conversation_id": data.get("conversation_id", f.stem),
                    "timestamp": data.get("timestamp", ""),
                    "message_count": len(data.get("messages", [])),
                    "metadata": data.get("metadata", {}),
                })
            except (json.JSONDecodeError, KeyError):
                logger.warning(f"Skipping malformed conversation file: {f}")
        return result

    # ──────────────────────────────────────
    #  内部方法
    # ──────────────────────────────────────

    def _scan_dir(self, directory: Path, pattern: str) -> list[dict]:
        """扫描目录下的文件，返回内容列表。"""
        results = []
        for f in directory.glob(pattern):
            try:
                content = f.read_text(encoding="utf-8")
                if content.strip():
                    results.append({
                        "source": str(f),
                        "content": content,
                    })
            except Exception as e:
                logger.warning(f"Failed to read {f}: {e}")
        return results

    def _scan_conversations(self, query: str) -> list[dict]:
        """扫描对话记录，提取与查询相关的片段。"""
        results = []
        for f in sorted(
            self.conversations_dir.glob("*.json"),
            key=lambda f: f.stat().st_mtime,
            reverse=True,
        )[:50]:  # 只看最近 50 个对话
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                messages = data.get("messages", [])
                # 拼接对话内容做搜索
                full_text = "\n".join(
                    m.get("content", "") for m in messages
                )
                if full_text.strip():
                    # 提取匹配片段而非全文
                    snippet = self._extract_snippet(full_text, query, max_chars=500)
                    if snippet:
                        results.append({
                            "source": str(f),
                            "content": snippet,
                        })
            except (json.JSONDecodeError, KeyError):
                pass
        return results

    def _extract_snippet(self, text: str, query: str, max_chars: int = 500) -> str | None:
        """从文本中提取与查询最相关的片段。"""
        query_lower = query.lower()
        text_lower = text.lower()

        # 查找查询在文本中的位置
        pos = text_lower.find(query_lower)
        if pos == -1:
            # 尝试查找查询中的单个词
            for word in query_lower.split():
                if len(word) >= 2:
                    pos = text_lower.find(word)
                    if pos >= 0:
                        break
            # 对中文也尝试 bigram
            if pos == -1:
                for i in range(len(query_lower) - 1):
                    bigram = query_lower[i:i+2]
                    pos = text_lower.find(bigram)
                    if pos >= 0:
                        break

        if pos == -1:
            return None

        # 提取片段（以匹配位置为中心）
        start = max(0, pos - max_chars // 2)
        end = min(len(text), pos + max_chars // 2)
        snippet = text[start:end].strip()

        if start > 0:
            snippet = "..." + snippet
        if end < len(text):
            snippet = snippet + "..."

        return snippet

    def _relevance_score(self, query: str, content: str) -> float:
        """计算查询与内容的相关性分数。

        MVP 使用：子串匹配 + 中文 bigram 重叠。
        """
        if not query or not content:
            return 0.0

        score = 0.0
        query_lower = query.lower()
        content_lower = content.lower()[:1000]  # 只看前 1000 字符

        # 完整查询匹配
        if query_lower in content_lower:
            score += 5.0

        # 逐词匹配
        words = [w for w in query_lower.split() if len(w) >= 2]
        for word in words:
            if word in content_lower:
                score += 2.0

        # 中文 bigram 重叠
        query_bigrams = {query_lower[i:i+2] for i in range(len(query_lower) - 1)}
        content_bigrams = {content_lower[i:i+2] for i in range(len(content_lower) - 1)}
        if query_bigrams:
            overlap = len(query_bigrams & content_bigrams)
            score += min(overlap * 0.3, 3.0)

        return score
