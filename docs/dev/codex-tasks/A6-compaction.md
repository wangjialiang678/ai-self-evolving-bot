# 任务 A6：Compaction 引擎

> **优先级**: P1（上下文引擎在 token 超限时调用）
> **预计工作量**: 2-3 天
> **类型**: Python 模块开发（含 LLM 调用）

---

## 项目背景

你在参与一个「自进化 AI 智能体系统」的开发。当对话上下文接近 token 预算上限（85%）时，Compaction 引擎自动触发，将旧对话压缩为摘要。**全程对用户无感**——不需要确认、不需要通知。

详细背景见 `docs/design/v3-2-system-design.md` 第 5.3.3 节

---

## 接口定义

```python
# extensions/context/compaction.py

class CompactionEngine:
    """上下文压缩引擎。当 token 接近预算时自动压缩对话历史。"""

    def __init__(self, llm_client: BaseLLMClient, memory_dir: str):
        """
        Args:
            llm_client: LLM 客户端
            memory_dir: workspace/memory/ 路径
        """

    async def should_compact(self, current_tokens: int, budget: int) -> bool:
        """当 current_tokens / budget >= 0.85 时返回 True。"""

    async def compact(self, conversation_history: list[dict],
                      keep_recent: int = 5) -> dict:
        """
        执行 Compaction。

        Args:
            conversation_history:
                [{"role": "user"|"assistant", "content": "...",
                  "timestamp": "2026-02-25T10:00:00"}, ...]
            keep_recent: 保留最近 N 轮完整对话（1轮=1个user+1个assistant）

        Returns:
            {"compacted_history": [...],
             "summary": "...",
             "flushed_to_memory": [...],
             "original_tokens": 12000,
             "compacted_tokens": 4500,
             "compression_ratio": 0.375,
             "key_decisions_preserved": 5,
             "key_decisions_total": 5}

        流程：
        1. 分离：保留最近 keep_recent 轮 + 需要压缩的旧对话
        2. Pre-Compaction Flush：提取关键信息写入持久记忆
        3. 调用 LLM 生成压缩摘要
        4. 构建新历史：[摘要消息] + [保留的最近对话]
        5. 验证压缩质量
        """

    async def _flush_to_memory(self, messages: list[dict]) -> list[dict]:
        """
        Pre-Compaction Flush：提取关键决策和信息写入持久记忆。

        调用 LLM 从旧消息中提取：
        - 关键决策（用户做了什么决定）
        - 重要事实（提到的项目信息、偏好等）
        - 待办事项（提到但未完成的事）

        写入 workspace/memory/user/compaction_flush.jsonl

        Returns:
            提取的条目列表
        """

    async def verify_compaction(self, original: list[dict],
                                compacted: dict) -> dict:
        """
        验证压缩质量。

        比较原始和压缩后的内容，检查关键信息是否保留。

        Returns:
            {"quality": "good"|"acceptable"|"poor",
             "missing_key_info": [...],
             "key_decisions_preserved": 5,
             "key_decisions_total": 5}
        """
```

---

## LLM Prompt 模板

### 压缩摘要 Prompt

**System Prompt:**
```
你是一个对话压缩器。将以下对话历史压缩为简洁摘要。

要求：
1. 保留所有关键决策和结论
2. 保留重要的事实信息（数字、日期、名称）
3. 保留未完成的任务和待办事项
4. 去除寒暄、重复、中间推理过程
5. 使用认知层级转化：事实 → 规律 → 策略
6. 压缩为原文的 10-20%

输出格式：纯文本摘要，不要 JSON。
```

### 信息提取 Prompt（flush_to_memory）

**System Prompt:**
```
从以下对话中提取值得长期记住的信息。

按 JSON 数组格式输出：
[
  {"type": "decision", "content": "用户决定使用 React 而非 Vue"},
  {"type": "fact", "content": "项目截止日期是 3 月 15 日"},
  {"type": "preference", "content": "用户偏好简短回答"},
  {"type": "todo", "content": "需要调研 NanoBot 的 Cron 机制"}
]

如果没有值得提取的信息，返回空数组 []。
```

---

## 技术约束

- Python 3.11+
- 依赖：`core.llm_client.BaseLLMClient`
- Token 估算：简单用 `len(text) / 4` 近似（英文）或 `len(text) / 2`（中文混合）
- 压缩摘要调用 `model="gemini-flash"`
- 全程不向用户发送任何确认或通知
- 写入记忆文件使用追加模式

---

## 测试要求

```python
# tests/test_compaction.py

import pytest
import json
from core.llm_client import MockLLMClient


class TestCompactionEngine:
    def test_should_compact_threshold(self):
        """85% 阈值判断。"""
        from extensions.context.compaction import CompactionEngine
        engine = CompactionEngine(None, "/tmp")

        assert await engine.should_compact(17000, 20000) is True   # 85%
        assert await engine.should_compact(16000, 20000) is False  # 80%
        assert await engine.should_compact(20000, 20000) is True   # 100%

    @pytest.mark.asyncio
    async def test_compact_preserves_recent(self, tmp_path):
        """保留最近 5 轮对话。"""
        memory_dir = _setup_memory(tmp_path)
        llm = MockLLMClient(responses={
            "gemini-flash": "这是压缩后的摘要。用户在讨论项目架构。",
        })
        engine = CompactionEngine(llm, str(memory_dir))

        history = _make_long_history(20)  # 20 轮对话
        result = await engine.compact(history, keep_recent=5)

        # 最近 5 轮 = 10 条消息（user+assistant）
        recent_messages = [m for m in result["compacted_history"]
                          if m.get("role") in ("user", "assistant")
                          and "summary" not in m.get("type", "")]
        # 加上摘要消息，总共应该是 10 + 1
        assert len(result["compacted_history"]) <= 11

    @pytest.mark.asyncio
    async def test_compact_has_summary(self, tmp_path):
        """压缩结果包含摘要。"""
        memory_dir = _setup_memory(tmp_path)
        llm = MockLLMClient(responses={
            "gemini-flash": "项目讨论摘要",
        })
        engine = CompactionEngine(llm, str(memory_dir))

        history = _make_long_history(20)
        result = await engine.compact(history, keep_recent=5)

        assert result["summary"] != ""
        assert result["compression_ratio"] < 1.0

    @pytest.mark.asyncio
    async def test_compact_short_history_no_op(self, tmp_path):
        """短对话不需要压缩。"""
        memory_dir = _setup_memory(tmp_path)
        llm = MockLLMClient()
        engine = CompactionEngine(llm, str(memory_dir))

        history = _make_long_history(3)  # 只有 3 轮
        result = await engine.compact(history, keep_recent=5)

        # 不需要压缩，返回原样
        assert result["compacted_history"] == history

    @pytest.mark.asyncio
    async def test_flush_writes_to_memory(self, tmp_path):
        """Pre-Compaction Flush 写入记忆。"""
        memory_dir = _setup_memory(tmp_path)
        llm = MockLLMClient(responses={
            "gemini-flash": json.dumps([
                {"type": "decision", "content": "使用 React"},
                {"type": "preference", "content": "简短回答"},
            ]),
        })
        engine = CompactionEngine(llm, str(memory_dir))

        history = _make_long_history(20)
        result = await engine.compact(history, keep_recent=5)

        assert len(result["flushed_to_memory"]) >= 1
        flush_file = memory_dir / "user/compaction_flush.jsonl"
        assert flush_file.exists()


def _setup_memory(tmp_path):
    memory_dir = tmp_path / "memory"
    (memory_dir / "user").mkdir(parents=True)
    return memory_dir


def _make_long_history(rounds):
    """生成 N 轮对话历史。"""
    history = []
    for i in range(rounds):
        history.append({
            "role": "user",
            "content": f"第{i+1}轮用户消息：请帮我分析问题{i+1}",
            "timestamp": f"2026-02-25T{10+i//6:02d}:{(i%6)*10:02d}:00",
        })
        history.append({
            "role": "assistant",
            "content": f"第{i+1}轮助手回复：关于问题{i+1}的分析结果是..." + "详细内容" * 20,
            "timestamp": f"2026-02-25T{10+i//6:02d}:{(i%6)*10+5:02d}:00",
        })
    return history
```

---

## 交付物

```
extensions/context/compaction.py
extensions/context/__init__.py    # 空文件（如不存在）
tests/test_compaction.py
```

---

## 验收标准

- [ ] should_compact 在 85% 阈值时正确触发
- [ ] compact 保留最近 keep_recent 轮完整对话
- [ ] compact 对短对话不做无意义压缩
- [ ] 压缩结果包含摘要文本
- [ ] Pre-Compaction Flush 提取关键信息写入记忆文件
- [ ] 全程无任何用户通知或确认
- [ ] LLM 返回异常时优雅降级
- [ ] 以上测试全部通过

---

## 参考文档

- Compaction：`docs/design/v3-2-system-design.md` 第 5.3.3 节
- 模块计划：`docs/dev/mvp-module-plan.md` A6 节
- 接口规范：`docs/dev/mvp-dev-guide.md` 第 2 节（接口 I8）
