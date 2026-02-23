"""Agent Loop — 核心执行循环，串联所有模块。

数据流：
  用户消息 → 规则解释器 → 记忆检索 → 上下文组装 → LLM 推理 → 回复
  → 异步后处理链：反思 → 信号检测 → Observer 轻量 → 指标记录
"""

import asyncio
import logging
import time
import uuid
from datetime import datetime
from pathlib import Path

from core.context import ContextEngine
from core.llm_client import BaseLLMClient
from core.memory import MemoryStore
from core.rules import RulesInterpreter

logger = logging.getLogger(__name__)


class AgentLoop:
    """核心 Agent 执行循环。

    职责：
    1. 接收用户消息，组装上下文，调用 LLM
    2. 管理对话历史
    3. 执行任务后处理链（反思 → 信号 → Observer → 指标）
    4. 检测并执行对话压缩
    """

    def __init__(
        self,
        workspace_path: str | Path,
        llm_client: BaseLLMClient,
        *,
        llm_client_light: BaseLLMClient | None = None,
        model: str = "opus",
        max_history_rounds: int = 20,
    ):
        """
        Args:
            workspace_path: workspace 根目录
            llm_client: 主力 LLM（Claude Opus）
            llm_client_light: 轻量 LLM（Qwen / Gemini Flash）用于反思和 Observer
            model: 默认推理模型
            max_history_rounds: 最大保留对话轮数
        """
        self.workspace = Path(workspace_path)
        self.llm = llm_client
        self.llm_light = llm_client_light or llm_client
        self.model = model
        self.max_history_rounds = max_history_rounds

        # --- Core 模块 ---
        rules_dir = str(self.workspace / "rules")
        self.rules = RulesInterpreter(rules_dir)
        self.rules.load_rules()

        self.memory = MemoryStore(self.workspace)
        self.context_engine = ContextEngine(self.rules)

        # --- 对话状态 ---
        self._conversation_history: list[dict] = []
        self._task_counter: int = 0

        # --- 扩展模块（延迟初始化，允许部分缺失） ---
        self._reflection_engine = None
        self._signal_detector = None
        self._signal_store = None
        self._observer_engine = None
        self._metrics_tracker = None
        self._compaction_engine = None

        self._init_extensions()

    def _init_extensions(self):
        """尝试初始化扩展模块，缺失则跳过。"""
        # 反思引擎
        try:
            from extensions.memory.reflection import ReflectionEngine
            memory_dir = str(self.workspace / "memory")
            self._reflection_engine = ReflectionEngine(self.llm_light, memory_dir)
        except Exception as e:
            logger.warning("ReflectionEngine not available: %s", e)

        # 信号系统
        try:
            from extensions.signals.store import SignalStore
            from extensions.signals.detector import SignalDetector
            signals_dir = str(self.workspace / "signals")
            self._signal_store = SignalStore(signals_dir)
            self._signal_detector = SignalDetector(self._signal_store)
        except Exception as e:
            logger.warning("SignalDetector not available: %s", e)

        # Observer
        try:
            from extensions.observer.engine import ObserverEngine
            self._observer_engine = ObserverEngine(
                llm_client_gemini=self.llm_light,
                llm_client_opus=self.llm,
                workspace_path=str(self.workspace),
            )
        except Exception as e:
            logger.warning("ObserverEngine not available: %s", e)

        # 指标追踪
        try:
            from extensions.evolution.metrics import MetricsTracker
            metrics_dir = str(self.workspace / "metrics")
            self._metrics_tracker = MetricsTracker(metrics_dir)
        except Exception as e:
            logger.warning("MetricsTracker not available: %s", e)

        # Compaction
        try:
            from extensions.context.compaction import CompactionEngine
            memory_dir = str(self.workspace / "memory")
            self._compaction_engine = CompactionEngine(self.llm_light, memory_dir)
        except Exception as e:
            logger.warning("CompactionEngine not available: %s", e)

    async def process_message(
        self,
        user_message: str,
        *,
        user_feedback: str | None = None,
        project: str | None = None,
    ) -> dict:
        """处理一条用户消息，返回完整任务轨迹。

        Args:
            user_message: 用户输入
            user_feedback: 对上一轮回复的反馈（用于反思）
            project: 当前项目名（用于项目级记忆）

        Returns:
            task_trace dict，包含 response、task_id 等
        """
        start_time = time.monotonic()
        self._task_counter += 1
        task_id = f"task_{self._task_counter:04d}"
        timestamp = datetime.now().replace(microsecond=0).isoformat()

        # [1] 记忆检索
        memories = self.memory.get_relevant_memories(
            query=user_message, project=project, max_results=5
        )
        user_preferences = self.memory.get_user_preferences()

        # [2] 上下文组装
        self.context_engine.set_task_anchor(user_message[:200])
        assembled = self.context_engine.assemble(
            user_message=user_message,
            conversation_history=self._conversation_history,
            memories=memories,
            user_preferences=user_preferences,
        )

        # [3] Compaction 检查
        if self._compaction_engine and self._compaction_engine.should_compact(
            assembled.total_tokens, 150_000
        ):
            try:
                result = await self._compaction_engine.compact(
                    self._conversation_history, keep_recent=5
                )
                self._conversation_history = result["compacted_history"]
                logger.info(
                    "Compaction done: %d → %d tokens",
                    result.get("original_tokens", 0),
                    result.get("compacted_tokens", 0),
                )
                # 重新组装
                assembled = self.context_engine.assemble(
                    user_message=user_message,
                    conversation_history=self._conversation_history,
                    memories=memories,
                    user_preferences=user_preferences,
                )
            except Exception as e:
                logger.error("Compaction failed: %s", e)

        # [4] LLM 推理
        try:
            response = await self.llm.complete(
                system_prompt=assembled.system_prompt,
                user_message=user_message,
                model=self.model,
                max_tokens=4000,
            )
        except Exception as e:
            logger.error("LLM call failed: %s", e)
            response = f"抱歉，处理消息时出错：{e}"

        if not response:
            logger.warning("LLM returned empty response for message: %.80s", user_message)
            response = "抱歉，暂时无法生成回复，请稍后再试。"

        duration_ms = int((time.monotonic() - start_time) * 1000)

        # [5] 更新对话历史
        self._conversation_history.append({"role": "user", "content": user_message})
        self._conversation_history.append({"role": "assistant", "content": response})
        self._trim_history()

        # [6] 组装 task_trace
        task_trace = {
            "task_id": task_id,
            "timestamp": timestamp,
            "user_message": user_message,
            "system_response": response,
            "user_feedback": user_feedback,
            "tools_used": [],
            "tokens_used": assembled.total_tokens,
            "model": self.model,
            "duration_ms": duration_ms,
        }

        # [7] 异步后处理链
        asyncio.ensure_future(self._post_task_pipeline(task_trace))

        return task_trace

    async def _post_task_pipeline(self, task_trace: dict):
        """任务后处理链：反思 → 信号检测 → Observer → 指标。"""
        reflection_output = None

        # [7a] 反思引擎
        if self._reflection_engine:
            try:
                reflection_output = await self._reflection_engine.lightweight_reflect(
                    task_trace
                )
                logger.info(
                    "Reflection: type=%s outcome=%s",
                    reflection_output.get("type"),
                    reflection_output.get("outcome"),
                )
            except Exception as e:
                logger.error("Reflection failed: %s", e)

        # [7b] 信号检测
        if self._signal_detector and reflection_output:
            try:
                task_context = {
                    "task_id": task_trace["task_id"],
                    "user_corrections": 1 if task_trace.get("user_feedback") else 0,
                    "tokens_used": task_trace.get("tokens_used", 0),
                    "output_type": reflection_output.get("type", "NONE"),
                    "outcome": reflection_output.get("outcome", "SUCCESS"),
                    "root_cause": reflection_output.get("root_cause"),
                    "rules_used": [],
                }
                signals = self._signal_detector.detect(reflection_output, task_context)
                if signals:
                    logger.info("Signals detected: %d", len(signals))
            except Exception as e:
                logger.error("Signal detection failed: %s", e)

        # [7c] Observer 轻量观察
        if self._observer_engine:
            try:
                await self._observer_engine.lightweight_observe(
                    task_trace, reflection_output
                )
            except Exception as e:
                logger.error("Observer lightweight failed: %s", e)

        # [7d] 指标记录
        if self._metrics_tracker:
            try:
                outcome = "SUCCESS"
                error_type = None
                user_corrections = 0
                if reflection_output:
                    outcome = reflection_output.get("outcome", "SUCCESS")
                    if reflection_output.get("type") in ("ERROR", "PREFERENCE"):
                        error_type = reflection_output["type"]
                    if task_trace.get("user_feedback"):
                        user_corrections = 1

                self._metrics_tracker.record_task(
                    task_id=task_trace["task_id"],
                    outcome=outcome,
                    tokens=task_trace.get("tokens_used", 0),
                    model=task_trace.get("model", "unknown"),
                    duration_ms=task_trace.get("duration_ms", 0),
                    user_corrections=user_corrections,
                    error_type=error_type,
                )
            except Exception as e:
                logger.error("Metrics recording failed: %s", e)

    def _trim_history(self):
        """裁剪对话历史到 max_history_rounds。"""
        max_messages = self.max_history_rounds * 2
        if len(self._conversation_history) > max_messages:
            self._conversation_history = self._conversation_history[-max_messages:]

    def get_conversation_history(self) -> list[dict]:
        """返回当前对话历史。"""
        return list(self._conversation_history)

    def clear_history(self):
        """清空对话历史。"""
        self._conversation_history.clear()
        self._task_counter = 0

    async def get_daily_summary(self) -> dict | None:
        """获取今日指标汇总。"""
        if not self._metrics_tracker:
            return None
        return self._metrics_tracker.get_daily_summary()

    async def run_deep_analysis(self, trigger: str = "daily") -> dict | None:
        """手动触发 Observer 深度分析。"""
        if not self._observer_engine:
            return None
        return await self._observer_engine.deep_analyze(trigger=trigger)
