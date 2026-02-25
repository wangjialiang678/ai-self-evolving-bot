# 任务 A7：Observer 引擎

> **优先级**: P2（依赖 A4 信号系统和 A3 指标系统）
> **预计工作量**: 3-4 天
> **类型**: Python 模块开发（含 LLM 调用）

---

## 项目背景

你在参与一个「自进化 AI 智能体系统」的开发。Observer（观察者）是系统的「眼睛」——它观察但不修改。两种模式：

1. **轻量模式**：每次任务后运行，用 Qwen 记录一行观察日志
2. **深度模式**：每日定时（或紧急触发），用 Claude Opus 4.6 生成综合分析报告

Observer 的输出是 Architect（架构师）的输入。Observer 只负责观察和报告，不做任何修改决策。

详细背景见 `docs/design/v3-2-system-design.md` 第 6.1 节

---

## 你要做什么

实现两个类：
1. `ObserverEngine` — 轻量观察 + 深度分析
2. `ObserverScheduler` — 调度逻辑（定时触发 + 紧急触发）

---

## 接口定义

```python
# extensions/observer/engine.py

class ObserverEngine:
    """Observer 引擎：观察系统运行状况，生成报告。"""

    def __init__(self, llm_client: BaseLLMClient,
                 workspace_path: str,
                 *,
                 light_model: str = "qwen",
                 deep_model: str = "opus"):
        """
        Args:
            llm_client: 多 Provider LLM 客户端（统一注册表）
            workspace_path: workspace/ 目录路径
            light_model: 轻量观察使用的 provider 名（默认 qwen）
            deep_model: 深度分析使用的 provider 名（默认 opus）
        """

    async def lightweight_observe(self, task_trace: dict,
                                   reflection_output: dict | None = None) -> dict:
        """
        每次任务后的轻量观察。

        Args:
            task_trace: 任务轨迹（同反思引擎的输入）
            reflection_output: 反思引擎的输出（可选）

        Returns:
            light_log 记录：
            {"timestamp": "...", "task_id": "...", "outcome": "...",
             "tokens": 2800, "model": "opus",
             "signals": ["user_pattern"],
             "error_type": "ERROR"|"PREFERENCE"|None,
             "note": "分析任务过长，用户要求简短"}

        行为：
        - 调用 Gemini Flash 生成一行观察笔记
        - 写入 workspace/observations/light_logs/{date}.jsonl
        """

    async def deep_analyze(self, trigger: str = "daily") -> dict:
        """
        深度分析：综合当日所有轻量日志、信号、规则，生成报告。

        Args:
            trigger: "daily" | "emergency"

        Returns:
            deep_report:
            {"trigger": "daily"|"emergency",
             "date": "2026-02-25",
             "tasks_analyzed": 12,
             "key_findings": [
               {"finding_id": "f_001",
                "type": "error_pattern"|"efficiency"|"skill_gap"|"preference",
                "description": "...",
                "confidence": "HIGH"|"MEDIUM"|"LOW",
                "evidence": [...],
                "recommendation": "..."}
             ],
             "overall_health": "good"|"degraded"|"critical"}

        行为：
        1. 读取当日 light_logs
        2. 读取 workspace/signals/active.jsonl
        3. 读取当前规则文件列表
        4. 调用 Opus 生成深度分析
        5. 写入 workspace/observations/deep_reports/{date}.md
        6. 同时返回结构化 dict
        """
```

```python
# extensions/observer/scheduler.py

class ObserverScheduler:
    """Observer 调度器：管理定时触发和紧急触发。"""

    def __init__(self, observer: ObserverEngine,
                 signal_store,  # SignalStore 实例
                 metrics,       # MetricsTracker 实例
                 config: dict):
        """
        Args:
            config:
                {"daily_time": "02:00",
                 "emergency_threshold": 3}
        """

    async def check_and_run(self) -> dict | None:
        """
        检查是否需要运行深度分析。

        触发条件（满足任一）：
        1. 当前时间在 daily_time 的 ±30分钟内，且今日未运行过
        2. 24h 内 CRITICAL 信号 ≥ emergency_threshold

        Returns:
            deep_report 或 None（未触发）
        """

    def get_next_run_time(self) -> str:
        """返回下次计划运行时间（ISO 8601）。"""

    def mark_daily_done(self):
        """标记今日定时分析已完成。"""
```

---

## 深度分析 Prompt

**System Prompt:**
```
你是 Observer（观察者），一个系统运行状况分析师。
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

key_findings 按优先级排序（error_pattern 最高）。
```

**User Message:**
```
=== 今日轻量观察日志 ===
{light_logs 内容}

=== 活跃信号 ===
{active signals}

=== 当前规则文件列表 ===
{rules 文件名列表}

触发方式: {trigger}
```

---

## 轻量观察 Prompt

**System Prompt:**
```
你是 Observer 的轻量模式。为以下任务写一行观察笔记。

输出格式（纯文本，一行，不超过 100 字）：
[观察到的关键信息，如异常、模式、值得注意的点]

如果任务完全正常，输出 "正常完成"。
```

---

## 深度报告 Markdown 模板

写入 `deep_reports/{date}.md` 的格式：

```markdown
# Observer 深度报告 — {date}

> 触发方式: {daily/emergency}
> 分析任务数: {tasks_analyzed}
> 系统健康度: {overall_health}

## 关键发现

### 1. [{type}] {description}
- **置信度**: {confidence}
- **证据**: {evidence}
- **建议**: {recommendation}

### 2. ...

## 数据概览
- 今日任务: {total} (成功 {success}, 部分 {partial}, 失败 {failure})
- 信号: {signals_count} 条 (CRITICAL: {critical}, HIGH: {high})
- Token 消耗: {tokens}
```

---

## 技术约束

- Python 3.11+
- 依赖：`core.llm_client.BaseLLMClient`
- 轻量观察用 `model="qwen"`（通过 `light_model` 参数配置）
- 深度分析用 `model="opus"`（通过 `deep_model` 参数配置）
- 使用单一 `LLMClient` 实例，通过 `model` 参数路由到不同 Provider
- JSONL 追加写入
- 深度报告同时写 Markdown 文件和返回 dict
- ObserverScheduler 不管理实际定时器（调用方负责定时调用 check_and_run）

---

## 测试要求

```python
# tests/test_observer.py

import pytest
import json
from pathlib import Path
from datetime import date


class TestObserverEngine:
    @pytest.mark.asyncio
    async def test_lightweight_writes_jsonl(self, tmp_path):
        """轻量观察写入 JSONL。"""
        ws = _setup_workspace(tmp_path)
        engine = _make_engine(ws)

        trace = _make_trace()
        log = await engine.lightweight_observe(trace)

        today = date.today().isoformat()
        log_file = ws / f"observations/light_logs/{today}.jsonl"
        assert log_file.exists()
        lines = log_file.read_text().strip().split("\n")
        assert len(lines) == 1
        assert json.loads(lines[0])["task_id"] == "task_042"

    @pytest.mark.asyncio
    async def test_lightweight_returns_log(self, tmp_path):
        """轻量观察返回正确格式。"""
        ws = _setup_workspace(tmp_path)
        engine = _make_engine(ws)

        log = await engine.lightweight_observe(_make_trace())
        assert "task_id" in log
        assert "outcome" in log
        assert "note" in log

    @pytest.mark.asyncio
    async def test_deep_analyze_reads_logs(self, tmp_path):
        """深度分析读取当日日志。"""
        ws = _setup_workspace(tmp_path)
        engine = _make_engine(ws, opus_response=json.dumps({
            "tasks_analyzed": 2,
            "key_findings": [
                {"type": "error_pattern", "description": "重复错误",
                 "confidence": "HIGH", "evidence": ["task_042"],
                 "recommendation": "添加规则"}
            ],
            "overall_health": "good",
        }))

        # 先写入一些轻量日志
        await engine.lightweight_observe(_make_trace("task_041"))
        await engine.lightweight_observe(_make_trace("task_042"))

        report = await engine.deep_analyze(trigger="daily")
        assert report["tasks_analyzed"] >= 1
        assert len(report["key_findings"]) >= 1

    @pytest.mark.asyncio
    async def test_deep_report_markdown(self, tmp_path):
        """深度报告写入 Markdown。"""
        ws = _setup_workspace(tmp_path)
        engine = _make_engine(ws, opus_response=json.dumps({
            "tasks_analyzed": 1,
            "key_findings": [],
            "overall_health": "good",
        }))

        await engine.lightweight_observe(_make_trace())
        await engine.deep_analyze(trigger="daily")

        today = date.today().isoformat()
        report_file = ws / f"observations/deep_reports/{today}.md"
        assert report_file.exists()
        content = report_file.read_text()
        assert "Observer 深度报告" in content

    @pytest.mark.asyncio
    async def test_deep_analyze_priority_order(self, tmp_path):
        """key_findings 按优先级排序。"""
        ws = _setup_workspace(tmp_path)
        engine = _make_engine(ws, opus_response=json.dumps({
            "tasks_analyzed": 5,
            "key_findings": [
                {"type": "preference", "description": "偏好",
                 "confidence": "LOW", "evidence": [], "recommendation": ""},
                {"type": "error_pattern", "description": "错误",
                 "confidence": "HIGH", "evidence": [], "recommendation": ""},
            ],
            "overall_health": "degraded",
        }))

        await engine.lightweight_observe(_make_trace())
        report = await engine.deep_analyze()

        # error_pattern 应排在 preference 前面
        if len(report["key_findings"]) >= 2:
            types = [f["type"] for f in report["key_findings"]]
            assert types.index("error_pattern") < types.index("preference")


class TestObserverScheduler:
    @pytest.mark.asyncio
    async def test_emergency_trigger(self, tmp_path):
        """24h 内 ≥3 次 CRITICAL 触发紧急分析。"""
        ws = _setup_workspace(tmp_path)
        engine = _make_engine(ws, opus_response=json.dumps({
            "tasks_analyzed": 0, "key_findings": [],
            "overall_health": "critical",
        }))

        from extensions.observer.scheduler import ObserverScheduler
        mock_store = _MockSignalStore(critical_count=3)
        mock_metrics = _MockMetrics()

        scheduler = ObserverScheduler(
            engine, mock_store, mock_metrics,
            config={"daily_time": "02:00", "emergency_threshold": 3}
        )

        result = await scheduler.check_and_run()
        assert result is not None  # 触发了

    @pytest.mark.asyncio
    async def test_no_emergency_below_threshold(self, tmp_path):
        """CRITICAL < 3 不触发紧急。"""
        ws = _setup_workspace(tmp_path)
        engine = _make_engine(ws)

        from extensions.observer.scheduler import ObserverScheduler
        mock_store = _MockSignalStore(critical_count=1)
        mock_metrics = _MockMetrics()

        scheduler = ObserverScheduler(
            engine, mock_store, mock_metrics,
            config={"daily_time": "25:00", "emergency_threshold": 3}  # daily 不会触发
        )

        result = await scheduler.check_and_run()
        assert result is None


# === Helpers ===

def _setup_workspace(tmp_path):
    ws = tmp_path / "workspace"
    for d in ["observations/light_logs", "observations/deep_reports",
              "signals", "rules/constitution", "rules/experience",
              "metrics/daily"]:
        (ws / d).mkdir(parents=True)
    (ws / "signals/active.jsonl").touch()
    return ws


def _make_engine(ws, opus_response=None):
    from extensions.observer.engine import ObserverEngine
    from core.llm_client import MockLLMClient

    if opus_response is None:
        opus_response = json.dumps({
            "tasks_analyzed": 1, "key_findings": [],
            "overall_health": "good",
        })

    llm = MockLLMClient(responses={
        "qwen": "正常完成",
        "gemini-flash": "正常完成",
        "opus": opus_response,
    })
    return ObserverEngine(llm_client=llm, workspace_path=str(ws))


def _make_trace(task_id="task_042"):
    return {
        "task_id": task_id,
        "user_message": "帮我分析",
        "system_response": "分析结果...",
        "user_feedback": None,
        "tools_used": [],
        "tokens_used": 2000,
        "model": "opus",
        "duration_ms": 10000,
    }


class _MockSignalStore:
    def __init__(self, critical_count=0):
        self._critical_count = critical_count

    def count_recent(self, signal_type=None, priority=None, hours=24):
        if priority == "CRITICAL":
            return self._critical_count
        return 0

    def get_active(self, **kwargs):
        return []


class _MockMetrics:
    def get_daily_summary(self, target_date=None):
        return {"tasks": {"total": 0, "success_rate": 0.0}}
```

---

## 交付物

```
extensions/observer/engine.py
extensions/observer/scheduler.py
extensions/observer/__init__.py    # 空文件（如不存在）
tests/test_observer.py
```

---

## 验收标准

- [ ] lightweight_observe 写入 JSONL 格式日志（按日期分文件）
- [ ] deep_analyze 读取当日日志和信号，生成结构化报告
- [ ] deep_analyze 同时写入 Markdown 报告文件
- [ ] key_findings 按优先级排序（error > efficiency > skill > preference）
- [ ] ObserverScheduler 正确判断定时触发
- [ ] ObserverScheduler 正确判断紧急触发（24h ≥3 CRITICAL）
- [ ] LLM 返回异常时优雅降级
- [ ] 以上测试全部通过

---

## 参考文档

- Observer：`docs/design/v3-2-system-design.md` 第 6.1 节
- 模块计划：`docs/dev/mvp-module-plan.md` A7 节
- 接口规范：`docs/dev/mvp-dev-guide.md` 第 2 节（接口 I4、I5）
