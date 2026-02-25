# MVP 开发指南 — 接口、测试、联调、分工

> **日期**: 2026-02-23
> **配套文档**：[mvp-module-plan.md](mvp-module-plan.md)（模块划分）、[v3-2-system-design.md](../design/v3-2-system-design.md)（完整设计）

---

## 目录

1. [项目背景索引](#1-项目背景索引codex-必读)
2. [模块间接口规范](#2-模块间接口规范)
3. [数据流全景](#3-数据流全景)
4. [各模块独立测试方案](#4-各模块独立测试方案)
5. [联调测试方案](#5-联调测试方案)
6. [开发顺序与流程](#6-开发顺序与流程)
7. [需要技术调研的模块](#7-需要技术调研的模块)
8. [我的子代理分工](#8-我的子代理分工)

---

## 1. 项目背景索引（Codex 必读）

### 1.1 一句话理解项目

> 构建一个能自我观察、自我反思、自主改进的 AI 智能体系统。核心是「规则驱动 + 进化闭环」——系统的行为由可读的规则文件定义，AI 可以在观察运行数据后提出修改这些规则的提案。

### 1.2 背景文档索引

| 文档 | 路径 | 读什么 | 什么时候读 |
|------|------|--------|----------|
| **完整设计方案** | `docs/design/v3-2-system-design.md` | 系统整体架构、各子系统设计 | 需要理解「为什么这样设计」时 |
| **场景文档** | `docs/design/v3-2-scenarios.md` | 23 个用户场景，理解系统实际体验 | 需要理解「最终效果是什么」时 |
| **模块划分** | `docs/dev/mvp-module-plan.md` | 模块分类、接口定义、验收标准 | 开始开发前必读 |
| **本文档** | `docs/dev/mvp-dev-guide.md` | 接口规范、测试方案、联调计划 | 开始开发前必读 |

### 1.3 核心概念速查

| 概念 | 含义 | 在哪里详细看 |
|------|------|------------|
| **规则文件** | 自然语言写的 Markdown 文件，定义系统行为。分宪法级（不可自主改）和经验级（可自主改） | 设计文档 5.2 |
| **反思** | 每次任务完成后，用 Gemini 提取一行教训。分 ERROR（真正错误）和 PREFERENCE（偏好偏差） | 设计文档 5.5 |
| **信号** | 从运行数据中提取的进化方向指标（如 user_correction, repeated_error） | 设计文档 5.6 |
| **Observer** | 观察者，轻量模式（每次任务后）+ 深度模式（每日定时），只观察不修改 | 设计文档 6.1 |
| **Architect** | 架构师，读取 Observer 报告，设计改进方案，执行修改。每日定时运行 | 设计文档 6.2 |
| **爆炸半径** | 限制单次修改的影响范围，Level 0 最多改 1 个文件，Level 1 最多 3 个 | 设计文档 6.6 |
| **审批级别** | Level 0 自主执行，Level 1 执行后通知，Level 2 先审批再执行，Level 3 需讨论 | 设计文档 6.7 |

### 1.4 技术约束

- **语言**：Python 3.11+
- **基座**：NanoBot 框架（极简 Python AI Agent 框架）
- **LLM**：Claude Opus 4.6（主力）+ Qwen 3.5（辅助/低成本任务），多 Provider 注册表架构
- **存储**：纯文件系统（Markdown/YAML/JSONL），不用数据库
- **通信**：Telegram Bot API
- **运行环境**：Mac 本地 24h
- **不使用**：Docker、外部数据库、LangChain/LlamaIndex、云服务

---

## 2. 模块间接口规范

### 2.1 接口全景图

```
用户消息
  │
  ▼
┌─────────────────────────────────────────────────┐
│                    Agent Loop                    │
│  ┌──────────┐  ┌──────────┐  ┌───────────────┐  │
│  │RuleInterp│─▶│ContextEng│─▶│  LLM Gateway  │  │
│  └──────────┘  └──────────┘  └───────┬───────┘  │
│       ▲             ▲                │           │
│       │             │                ▼           │
│  rules/*.md    ┌────┴────┐    ┌──────────┐      │
│                │MemoryMgr│    │  回复用户  │      │
│                └────┬────┘    └──────┬───┘      │
│                     │               │           │
└─────────────────────┼───────────────┼───────────┘
                      │               │
              ┌───────▼───────┐       │
              │  任务后处理链   │◄──────┘
              │               │
              │  ① 反思引擎    │──▶ reflection_output
              │  ② 信号检测    │──▶ signal
              │  ③ Observer轻量│──▶ light_log
              │  ④ 指标记录    │──▶ metrics_event
              └───────────────┘

              ┌──────────────────────────────────┐
              │         定时任务（Cron）           │
              │                                  │
              │  02:00  Observer 深度分析          │
              │    ↓    写入 deep_report          │
              │  03:00  Architect 工作流           │
              │    ↓    读取 report → 生成提案     │
              │    ↓    审批 → 执行 → 回滚管理     │
              └──────────────────────────────────┘
```

### 2.2 模块间数据传递格式

每两个模块之间的交互，都通过明确的数据结构传递。**不通过内存共享**，全部通过文件或函数参数。

#### 接口 I1: Agent Loop → 反思引擎

```python
# task_trace: Agent Loop 执行完任务后，组装这个结构传给反思引擎
task_trace = {
    "task_id": "task_042",
    "timestamp": "2026-02-25T10:15:30",
    "user_message": "帮我分析 Cursor 做对了什么",
    "system_response": "Cursor 做对了以下几点：...",
    "user_feedback": "太长了，只要结论" | None,
    "tools_used": ["web_search"],
    "tokens_used": 3200,
    "model": "opus",
    "duration_ms": 15000
}
```

#### 接口 I2: 反思引擎 → 信号系统

```python
# reflection_output: 反思引擎的输出，传给信号检测器
reflection_output = {
    "task_id": "task_042",
    "type": "ERROR" | "PREFERENCE" | "NONE",
    "outcome": "SUCCESS" | "PARTIAL" | "FAILURE",
    "lesson": "做了错误假设——以为用户要技术方案，实际要产品策略",
    "root_cause": "wrong_assumption" | "missed_consideration" |
                  "tool_misuse" | "knowledge_gap" | None,
    "reusable_experience": "技术方案设计前先确认用户需要的是技术还是产品视角" | None
}
```

#### 接口 I3: 信号系统 → 文件存储

```python
# signal: 信号检测器的输出，写入 active.jsonl
signal = {
    "signal_id": "sig_001",
    "signal_type": "user_correction",  # 8 种类型之一
    "priority": "MEDIUM",
    "source": "reflection:task_042",
    "description": "用户纠正了分析长度偏好",
    "related_tasks": ["task_042"],
    "timestamp": "2026-02-25T10:16:00",
    "status": "active"  # active | handled
}
```

#### 接口 I4: Observer 轻量 → 文件存储

```python
# light_log: Observer 轻量观察，写入 light_logs/{date}.jsonl
light_log = {
    "timestamp": "2026-02-25T10:16:30",
    "task_id": "task_042",
    "outcome": "PARTIAL",
    "tokens": 3200,
    "model": "opus",
    "signals": ["user_correction"],
    "error_type": "PREFERENCE",
    "note": "分析任务过长，用户要求简短"
}
```

#### 接口 I5: Observer 深度 → Architect

```python
# deep_report: Observer 深度分析的输出，写入 deep_reports/{date}.md
# Architect 读取这个文件。两者通过文件传递，不直接调用。
deep_report = {
    "trigger": "daily",
    "date": "2026-02-25",
    "tasks_analyzed": 12,
    "key_findings": [
        {
            "finding_id": "f_001",
            "type": "error_pattern",  # error_pattern | efficiency | skill_gap | preference
            "description": "分析类任务过长问题反复出现",
            "confidence": "HIGH",
            "evidence": ["task_028 纠正", "task_033 纠正", "task_042 纠正"],
            "recommendation": "新增分析类任务长度控制规则"
        }
    ],
    "overall_health": "good"
}
```

#### 接口 I6: Architect → 回滚系统

```python
# proposal: Architect 生成的提案
proposal = {
    "proposal_id": "prop_024",
    "level": 1,  # 审批级别 0-3
    "trigger_source": "observer_report:2026-02-25",
    "problem": "分析类任务过长",
    "solution": "在 task_strategies.md 中新增长度控制规则",
    "files_affected": ["workspace/rules/experience/task_strategies.md"],
    "blast_radius": "small",
    "expected_effect": "分析类任务用户纠正率下降",
    "verification_method": "下 5 次分析类任务的首次成功率",
    "verification_days": 5,
    "rollback_plan": "恢复 task_strategies.md 原版"
}

# 执行时调用回滚系统：
backup_id = rollback_manager.backup(
    file_paths=["workspace/rules/experience/task_strategies.md"],
    proposal_id="prop_024"
)
```

#### 接口 I7: 指标系统 → 回滚系统（自动回滚判断）

```python
# Architect 验证期结束时调用
should_rollback = rollback_manager.auto_rollback_check(
    proposal_id="prop_024",
    current_metrics=metrics.get_daily_summary(),    # 当前指标
    baseline_metrics=metrics.get_daily_summary("2026-02-25"),  # 修改前基线
    threshold=0.20
)
```

#### 接口 I8: 上下文引擎 → Compaction

```python
# 上下文引擎检测到 token 超限时调用
if compaction_engine.should_compact(current_tokens=18000, budget=20000):
    result = await compaction_engine.compact(
        conversation_history=conversation_messages,
        keep_recent=5
    )
    # result.compacted_history 替换原对话历史
```

### 2.3 文件系统作为接口

**核心原则**：Observer 和 Architect 之间、信号系统和 Observer 之间，通过文件交互而非直接函数调用。

```
反思引擎 ──写入──▶ workspace/rules/experience/error_patterns.md
                   workspace/memory/user/preferences.md

信号检测器 ─写入─▶ workspace/signals/active.jsonl

Observer轻量 ─写入─▶ workspace/observations/light_logs/{date}.jsonl

Observer深度 ─写入─▶ workspace/observations/deep_reports/{date}.md

Architect ──读取──▶ workspace/observations/deep_reports/{date}.md
           ──读取──▶ workspace/signals/active.jsonl
           ──读取──▶ workspace/rules/**/*.md
           ──写入──▶ workspace/architect/proposals/{id}.md
           ──修改──▶ workspace/rules/experience/*.md（通过回滚系统）

指标系统 ──写入──▶ workspace/metrics/events.jsonl
                   workspace/metrics/daily/{date}.yaml
```

---

## 3. 数据流全景

### 3.1 单次任务的完整数据流

```
用户发消息
  │
  ▼
[1] Agent Loop 接收
  │
  ▼
[2] 规则解释器读取 rules/*.md → 解析为 prompt 片段
  │
  ▼
[3] 记忆检索：从 memory/ 中搜索相关条目
  │
  ▼
[4] 上下文引擎组装：
    ┌──────────────────────────────────────┐
    │ token 预算分配：                      │
    │   系统身份 + 宪法规则     10-15%     │
    │   任务锚点                3-5%      │
    │   相关经验规则            5-10%     │
    │   相关记忆               10-20%    │
    │   对话历史               20-30%    │
    │   用户偏好                2-3%     │
    │   安全边际               ~25%      │
    └──────────────────────────────────────┘
  │
  ▼
[5] LLM 推理 → 生成回复（可能包含工具调用 → 循环直到完成）
  │
  ▼
[6] 回复用户
  │
  ▼
[7] === 任务后处理链（异步，用户不等待）===
  │
  ├─▶ [7a] 反思引擎（Qwen）
  │         输入: task_trace
  │         输出: reflection_output
  │         写入: error_patterns.md 或 preferences.md
  │
  ├─▶ [7b] 信号检测器
  │         输入: reflection_output + task_context
  │         输出: signal(s)
  │         写入: signals/active.jsonl
  │
  ├─▶ [7c] Observer 轻量观察（Qwen）
  │         输入: task_trace + reflection_output
  │         输出: light_log
  │         写入: observations/light_logs/{date}.jsonl
  │
  └─▶ [7d] 指标记录
            输入: task_trace + reflection_output
            写入: metrics/events.jsonl
```

### 3.2 每日定时任务的数据流

```
02:00 — Observer 深度分析
  读取: light_logs/{today}.jsonl + rules/*.md + big_picture.md
  输出: deep_reports/{today}.md
  │
  ▼
03:00 — Architect 工作流
  │
  ├─ 读取: deep_reports/{today}.md
  ├─ 读取: signals/active.jsonl
  ├─ 读取: rules/*.md + big_picture.md
  ├─ 读取: 上次提案的验证数据（metrics/）
  │
  ▼
  诊断问题（按优先级：错误 > 效率 > 技能 > 偏好）
  │
  ▼
  设计方案 → 判断审批级别
  │
  ├─ Level 0: 自主执行
  │    └─ rollback.backup() → 修改文件 → 无需通知
  │
  ├─ Level 1: 执行后通知
  │    └─ rollback.backup() → 修改文件 → Telegram 通知（排队到 08:30）
  │
  └─ Level 2+: 先审批
       └─ Telegram 发提案 → 等待用户回复 → 执行或放弃

  验证期开始 → Observer 持续收集数据
  │
  ▼
  验证期结束 → metrics 对比 → 有效(validated) / 无效(rollback)
```

---

## 4. 各模块独立测试方案

### 4.1 通用测试约定

- **框架**：`pytest` + `pytest-asyncio`
- **LLM Mock**：所有需要 LLM 的模块使用 `MockLLMClient`（固定返回）
- **文件系统**：每个测试用 `tmp_path` fixture 创建临时目录
- **命名**：`tests/test_{module_name}.py`
- **覆盖率目标**：核心逻辑 >80%

```python
# tests/conftest.py — 共用 fixtures

import pytest
import json
from pathlib import Path

@pytest.fixture
def workspace(tmp_path):
    """创建标准的 workspace 目录结构。"""
    dirs = [
        "rules/constitution", "rules/experience",
        "memory/user", "memory/projects", "memory/conversations",
        "memory/daily_summaries",
        "skills/learned", "skills/seed",
        "observations/light_logs", "observations/deep_reports",
        "signals", "architect/proposals", "architect/modifications",
        "backups", "metrics/daily", "logs"
    ]
    for d in dirs:
        (tmp_path / d).mkdir(parents=True)

    # 初始化空文件
    (tmp_path / "signals/active.jsonl").touch()
    (tmp_path / "signals/archive.jsonl").touch()
    (tmp_path / "metrics/events.jsonl").touch()
    (tmp_path / "architect/big_picture.md").write_text("# Big Picture\n")

    return tmp_path

@pytest.fixture
def mock_llm():
    """Mock LLM 客户端。"""
    class MockLLMClient:
        def __init__(self, responses=None):
            self.responses = responses or {}
            self.calls = []

        async def complete(self, system_prompt, user_message,
                          model="gemini-flash", max_tokens=2000):
            self.calls.append({
                "system_prompt": system_prompt,
                "user_message": user_message,
                "model": model
            })
            # 根据 model 返回不同的 mock 响应
            if model in self.responses:
                return self.responses[model]
            return '{"type": "NONE", "outcome": "SUCCESS", "lesson": "mock"}'

    return MockLLMClient

@pytest.fixture
def sample_task_trace():
    """标准的任务轨迹样本。"""
    return {
        "task_id": "task_042",
        "timestamp": "2026-02-25T10:15:30",
        "user_message": "帮我分析 Cursor 做对了什么",
        "system_response": "Cursor 做对了以下几点：1. xxx 2. xxx 3. xxx...",
        "user_feedback": "太长了，只要结论",
        "tools_used": ["web_search"],
        "tokens_used": 3200,
        "model": "opus",
        "duration_ms": 15000
    }
```

### 4.2 A1 种子规则 — 测试方案

**不需要代码测试**，但需要人工审查 checklist：

```
□ 每个规则文件使用 Markdown 格式，不使用 YAML front matter
□ identity.md 定义了系统名称、人格、对话风格
□ safety_boundaries.md 列出了所有不可修改底线
□ approval_levels.md 的 4 个级别有明确边界和示例
□ meta_rules.md 描述了规则系统的元规则
□ core_orchestration.md 描述了上下文组装优先级
□ task_strategies.md 包含至少 5 种任务类型的默认策略
□ interaction_patterns.md 包含"执行前主动澄清"规则
□ error_patterns.md 包含 4 种 AI 常见错误模式
□ 所有文件之间不矛盾（如 approval_levels 和 safety_boundaries 一致）
□ 经验级规则可以被 grep 关键词匹配到（验证规则解释器能找到它们）
```

### 4.3 A2 回滚系统 — 测试方案

```python
# tests/test_rollback.py

class TestRollbackManager:
    def test_backup_creates_directory(self, workspace):
        """备份创建正确的目录结构。"""
        rm = RollbackManager(str(workspace))
        # 创建一个规则文件
        rule_file = workspace / "rules/experience/task_strategies.md"
        rule_file.write_text("# 原始内容")

        backup_id = rm.backup([str(rule_file)], "prop_001")

        assert (workspace / f"backups/{backup_id}").exists()
        # 备份文件内容与原始一致

    def test_rollback_restores_file(self, workspace):
        """回滚正确恢复文件。"""
        rm = RollbackManager(str(workspace))
        rule_file = workspace / "rules/experience/task_strategies.md"
        rule_file.write_text("# 原始内容")

        backup_id = rm.backup([str(rule_file)], "prop_001")
        rule_file.write_text("# 修改后内容")

        result = rm.rollback(backup_id)
        assert result["status"] == "success"
        assert rule_file.read_text() == "# 原始内容"

    def test_backup_multiple_files(self, workspace):
        """多文件备份和恢复。"""

    def test_rollback_nonexistent_backup(self, workspace):
        """回滚不存在的备份返回错误。"""

    def test_list_backups_ordered(self, workspace):
        """列出备份按时间倒序。"""

    def test_cleanup_old_backups(self, workspace):
        """清理超过保留期的备份。"""

    def test_auto_rollback_triggers(self, workspace):
        """指标恶化超过阈值时触发自动回滚。"""
        rm = RollbackManager(str(workspace))
        baseline = {"tasks": {"success_rate": 0.85}}
        current = {"tasks": {"success_rate": 0.60}}  # 下降 29%

        triggered = rm.auto_rollback_check("prop_001", current, baseline, 0.20)
        assert triggered is True

    def test_auto_rollback_no_trigger(self, workspace):
        """指标轻微波动不触发回滚。"""
        baseline = {"tasks": {"success_rate": 0.85}}
        current = {"tasks": {"success_rate": 0.80}}  # 下降 6%

        triggered = rm.auto_rollback_check("prop_001", current, baseline, 0.20)
        assert triggered is False

    def test_concurrent_backups(self, workspace):
        """两次备份不互相干扰。"""
```

### 4.4 A3 指标追踪 — 测试方案

```python
# tests/test_metrics.py

class TestMetricsTracker:
    def test_record_task(self, workspace):
        """记录任务事件。"""
        mt = MetricsTracker(str(workspace / "metrics"))
        mt.record_task("task_001", "SUCCESS", 3200, "opus", 15000)

        events = (workspace / "metrics/events.jsonl").read_text().strip().split("\n")
        assert len(events) == 1
        event = json.loads(events[0])
        assert event["task_id"] == "task_001"

    def test_daily_summary(self, workspace):
        """每日汇总正确统计。"""
        mt = MetricsTracker(str(workspace / "metrics"))
        mt.record_task("task_001", "SUCCESS", 3200, "opus", 15000)
        mt.record_task("task_002", "FAILURE", 1500, "opus", 8000)
        mt.record_task("task_003", "SUCCESS", 2000, "gemini-flash", 5000)

        summary = mt.get_daily_summary()
        assert summary["tasks"]["total"] == 3
        assert summary["tasks"]["success"] == 2
        assert summary["tasks"]["success_rate"] == pytest.approx(0.667, rel=0.01)

    def test_success_rate_window(self, workspace):
        """滑动窗口成功率计算。"""

    def test_should_trigger_repair(self, workspace):
        """repair 模式触发判断。"""

    def test_flush_daily_yaml(self, workspace):
        """每日 YAML 文件格式正确。"""

    def test_empty_day(self, workspace):
        """空数据日不报错。"""
```

### 4.5 A4 信号系统 — 测试方案

```python
# tests/test_signals.py

class TestSignalDetector:
    def test_detect_user_correction(self, workspace):
        """用户纠正触发 user_correction 信号。"""
        store = SignalStore(str(workspace / "signals"))
        detector = SignalDetector(store)

        reflection = {
            "task_id": "task_042", "type": "PREFERENCE",
            "outcome": "PARTIAL", "lesson": "用户要简短"
        }
        context = {"user_corrections": 1}

        signals = detector.detect(reflection, context)
        assert any(s["signal_type"] == "user_correction" for s in signals)

    def test_detect_error_no_correction_signal(self, workspace):
        """ERROR 类型不生成 user_correction，而是 error_pattern。"""

    def test_detect_repeated_error(self, workspace):
        """7 天内同类错误 ≥2 次触发 repeated_error。"""

    def test_detect_performance_degradation(self, workspace):
        """成功率下降 >15% 触发 CRITICAL 信号。"""

    def test_no_signal_on_success(self, workspace):
        """成功且无异常时不生成信号（或只生成 LOW 的 rule_validated）。"""

class TestSignalStore:
    def test_add_and_get_active(self, workspace):
        """写入信号后能读取。"""

    def test_mark_handled(self, workspace):
        """标记处理后从 active 移到 archive。"""

    def test_count_recent(self, workspace):
        """时间窗口内计数正确。"""

    def test_filter_by_priority(self, workspace):
        """按优先级过滤。"""
```

### 4.6 A5 反思引擎 — 测试方案

```python
# tests/test_reflection.py

class TestReflectionEngine:
    @pytest.mark.asyncio
    async def test_classify_error(self, workspace, mock_llm):
        """正确分类为 ERROR。"""
        llm = mock_llm(responses={
            "gemini-flash": json.dumps({
                "type": "ERROR", "outcome": "FAILURE",
                "lesson": "错误假设", "root_cause": "wrong_assumption"
            })
        })
        engine = ReflectionEngine(llm, str(workspace / "memory"))

        trace = {
            "task_id": "task_035",
            "user_message": "设计用户邀请功能",
            "system_response": "邮件邀请方案...",
            "user_feedback": "不对，用户在微信",
            "tools_used": [], "tokens_used": 2000,
            "model": "opus", "duration_ms": 10000
        }

        result = await engine.lightweight_reflect(trace)
        assert result["type"] == "ERROR"
        assert result["root_cause"] == "wrong_assumption"

    @pytest.mark.asyncio
    async def test_classify_preference(self, workspace, mock_llm):
        """正确分类为 PREFERENCE。"""

    @pytest.mark.asyncio
    async def test_classify_none(self, workspace, mock_llm):
        """无异常时分类为 NONE。"""

    def test_write_error_to_patterns(self, workspace, mock_llm):
        """ERROR 写入 error_patterns.md。"""

    def test_write_preference_to_prefs(self, workspace, mock_llm):
        """PREFERENCE 写入 user/preferences.md。"""

    @pytest.mark.asyncio
    async def test_llm_timeout_handling(self, workspace, mock_llm):
        """LLM 超时时返回默认值而非崩溃。"""
```

### 4.7 A6 Compaction — 测试方案

```python
# tests/test_compaction.py

class TestCompactionEngine:
    def test_should_compact_threshold(self):
        """85% 阈值判断。"""
        engine = CompactionEngine(None, "/tmp")
        assert engine.should_compact(17000, 20000) is True   # 85%
        assert engine.should_compact(16000, 20000) is False   # 80%

    @pytest.mark.asyncio
    async def test_compact_preserves_recent(self, workspace, mock_llm):
        """保留最近 5 轮对话。"""

    @pytest.mark.asyncio
    async def test_compact_compression_ratio(self, workspace, mock_llm):
        """压缩比在 10-20%。"""

    @pytest.mark.asyncio
    async def test_flush_to_memory(self, workspace, mock_llm):
        """关键信息写入持久记忆。"""

    @pytest.mark.asyncio
    async def test_no_user_notification(self, workspace, mock_llm):
        """全程无任何用户通知或确认。"""

    @pytest.mark.asyncio
    async def test_verify_key_decisions(self, workspace, mock_llm):
        """压缩后关键决策点全部保留。"""
```

### 4.8 A7 Observer — 测试方案

```python
# tests/test_observer.py

class TestObserverEngine:
    @pytest.mark.asyncio
    async def test_lightweight_writes_jsonl(self, workspace, mock_llm):
        """轻量观察正确写入 JSONL。"""

    @pytest.mark.asyncio
    async def test_deep_analyze_reads_logs(self, workspace, mock_llm):
        """深度分析读取当日所有轻量日志。"""

    @pytest.mark.asyncio
    async def test_deep_analyze_priority_order(self, workspace, mock_llm):
        """key_findings 按 error > efficiency > skill > preference 排序。"""

    @pytest.mark.asyncio
    async def test_deep_report_markdown(self, workspace, mock_llm):
        """深度报告写入可读的 Markdown 文件。"""

class TestObserverScheduler:
    @pytest.mark.asyncio
    async def test_daily_trigger(self, workspace):
        """到定时时间触发深度分析。"""

    @pytest.mark.asyncio
    async def test_emergency_trigger(self, workspace):
        """24h 内 ≥3 次 critical 触发紧急分析。"""

    @pytest.mark.asyncio
    async def test_no_emergency_below_threshold(self, workspace):
        """critical < 3 不触发紧急。"""
```

---

## 5. 联调测试方案

### 5.1 联调原则

- **渐进式**：先两两联调，再三方联调，最后端到端
- **每次只加一个模块**：每次联调只新增一个模块，确保新增模块不破坏已有链路
- **用真实文件系统**：联调时使用临时 workspace（不 mock 文件操作）
- **LLM 仍可 mock**：联调阶段 LLM 调用仍用 Mock，端到端时才切真实 API

### 5.2 联调顺序（7 轮）

```
联调 1: 反思引擎 + 信号系统
  验证：反思输出能被信号检测器正确解析并生成信号

联调 2: 反思引擎 + 信号系统 + 指标追踪
  验证：一次任务后三个系统都正确记录数据

联调 3: 反思 + 信号 + Observer 轻量
  验证：任务后处理链完整运行（反思→信号→Observer 日志→指标）

联调 4: Observer 轻量 + Observer 深度 + 信号系统
  验证：深度分析能读取轻量日志和信号数据，生成报告

联调 5: Observer + Architect + 回滚系统
  验证：Architect 读取报告→生成提案→执行修改→备份正确

联调 6: 规则解释器 + 上下文引擎 + 记忆系统
  验证：规则文件+记忆被正确注入 LLM 上下文

联调 7: 端到端——全链路
  验证：用户消息→回复→反思→信号→Observer→Architect→修改→验证
```

### 5.3 联调测试用例

#### 联调 1: 反思 + 信号

```python
# tests/integration/test_reflection_signal.py

@pytest.mark.asyncio
async def test_error_reflection_generates_signal(workspace, mock_llm):
    """ERROR 类型反思 → 生成 error_pattern 信号。"""
    llm = mock_llm(responses={
        "gemini-flash": json.dumps({
            "type": "ERROR", "outcome": "FAILURE",
            "lesson": "错误假设", "root_cause": "wrong_assumption"
        })
    })

    reflection_engine = ReflectionEngine(llm, str(workspace / "memory"))
    signal_store = SignalStore(str(workspace / "signals"))
    signal_detector = SignalDetector(signal_store)

    # 执行反思
    trace = make_failed_task_trace()
    reflection = await reflection_engine.lightweight_reflect(trace)

    # 检测信号
    signals = signal_detector.detect(reflection, extract_context(trace))

    # 验证
    assert reflection["type"] == "ERROR"
    assert len(signals) >= 1
    assert signals[0]["priority"] in ("MEDIUM", "HIGH")

    # 验证信号写入文件
    active = signal_store.get_active()
    assert len(active) >= 1

@pytest.mark.asyncio
async def test_preference_reflection_no_high_signal(workspace, mock_llm):
    """PREFERENCE 类型反思 → 只生成 LOW 信号或不生成。"""
```

#### 联调 2: 反思 + 信号 + 指标

```python
@pytest.mark.asyncio
async def test_full_post_task_pipeline(workspace, mock_llm):
    """完整的任务后处理链。"""
    # 初始化所有组件
    reflection_engine = ReflectionEngine(...)
    signal_store = SignalStore(...)
    signal_detector = SignalDetector(...)
    metrics = MetricsTracker(...)

    trace = make_task_trace(outcome="PARTIAL", user_feedback="太长了")

    # 执行任务后处理链
    reflection = await reflection_engine.lightweight_reflect(trace)
    signals = signal_detector.detect(reflection, extract_context(trace))
    metrics.record_task(trace["task_id"], reflection["outcome"],
                       trace["tokens_used"], trace["model"], trace["duration_ms"],
                       user_corrections=1, error_type=reflection["type"])

    # 验证：三个系统都有数据
    assert (workspace / "memory/user/preferences.md").read_text()  # 偏好写入
    assert signal_store.get_active()  # 信号存在
    assert metrics.get_daily_summary()["tasks"]["total"] == 1  # 指标记录
```

#### 联调 5: Observer + Architect + 回滚

```python
@pytest.mark.asyncio
async def test_architect_reads_report_and_proposes(workspace, mock_llm):
    """Architect 读取 Observer 报告 → 生成提案 → 执行修改 → 备份正确。"""
    # 预置 Observer 报告
    report_path = workspace / "observations/deep_reports/2026-02-25.md"
    report_path.write_text(make_sample_report())

    # 预置规则文件
    rule_file = workspace / "rules/experience/task_strategies.md"
    rule_file.write_text("# 初始策略\n")

    # Architect 执行
    architect = ArchitectEngine(...)
    rollback = RollbackManager(str(workspace))

    proposals = await architect.analyze_and_propose()
    assert len(proposals) >= 1

    # 执行提案
    proposal = proposals[0]
    backup_id = rollback.backup(proposal["files_affected"], proposal["proposal_id"])
    architect.execute_proposal(proposal)

    # 验证：文件被修改 + 备份存在
    assert rule_file.read_text() != "# 初始策略\n"
    assert rollback.list_backups()[0]["proposal_id"] == proposal["proposal_id"]

    # 验证回滚
    rollback.rollback(backup_id)
    assert rule_file.read_text() == "# 初始策略\n"
```

#### 联调 7: 端到端

```python
@pytest.mark.asyncio
async def test_end_to_end_evolution_cycle(workspace):
    """完整的进化闭环：5 次同类任务，第 5 次应优于第 1 次。"""
    system = create_full_system(workspace)

    # 模拟 5 次分析类任务
    for i in range(5):
        trace = await system.process_message(f"分析竞品 #{i}")
        await system.post_task_pipeline(trace)

    # 触发 Observer 深度分析 + Architect
    await system.run_observer_deep()
    await system.run_architect()

    # 验证：规则文件被修改了
    strategies = (workspace / "rules/experience/task_strategies.md").read_text()
    assert "分析" in strategies  # 包含分析类任务相关规则

    # 验证：第 6 次任务使用了新规则
    trace6 = await system.process_message("分析竞品 #6")
    # 新规则生效后，输出应更简短
```

### 5.4 联调时间安排

```
联调 1-3（任务后处理链）：集成 A5+A4+A3+A7轻量 后立即做
  预计：1 天

联调 4（Observer 深度 + 信号）：A7 完成后做
  预计：0.5 天

联调 5（Architect + 回滚）：B5 开发过程中做
  预计：1 天（与 B5 开发并行）

联调 6（规则+上下文+记忆）：B2+B3 完成后做
  预计：0.5 天

联调 7（端到端）：所有模块完成后
  预计：2-3 天（含调试）
```

---

## 6. 开发顺序与流程

### 6.1 完整时间线（修订版）

```
═══════════════════════════════════════════════════════════════
Phase 0: 基座搭建（Day 1-2）
═══════════════════════════════════════════════════════════════

  我:
    B1 — NanoBot 基座 + LLM 网关
      ├── 安装 NanoBot、配置 API Key
      ├── 创建 Telegram Bot 并连接
      ├── 实现 LLMClient 多 Provider 注册表（Opus + Qwen）
      └── 交付：可运行的 NanoBot + 能收发 Telegram 消息

  Codex 同时:
    A1 — 种子规则 + 默认配置（1 天）
    A2 — 回滚系统（1-2 天）
    A3 — 指标追踪系统（1-2 天）

═══════════════════════════════════════════════════════════════
Phase 1: 核心引擎（Day 3-7）
═══════════════════════════════════════════════════════════════

  我:
    B2 — 规则解释器 + 上下文引擎（3-4 天）
      ├── 规则文件读取和解析
      ├── 上下文组装流水线（token 预算管理）
      ├── 规则注入 system prompt
      ├── 集成 A1 种子规则
      └── 验证：修改规则后系统行为改变

    B4 — Telegram 通道 + 审批流程（与 B2 部分并行，2-3 天）
      ├── 消息模板（提案通知、日报、紧急通知）
      ├── 审批交互（按钮回复解析）
      ├── 勿扰时段 + 消息排队
      └── 验证：Telegram 完成对话+审批流程

  Codex 同时:
    A4 — 信号系统（2-3 天）
    A5 — 反思引擎（2-3 天）
    A6 — Compaction 引擎（2-3 天）
    A7 — Observer 引擎（3-4 天）

═══════════════════════════════════════════════════════════════
Phase 2: 记忆 + 集成第一批（Day 8-12）
═══════════════════════════════════════════════════════════════

  我:
    B3 — 记忆系统（2-3 天）
      ├── 记忆存储（user/ + projects/ 分层）
      ├── 记忆检索（关键词全文搜索）
      ├── 记忆注入上下文
      └── 验证：第二次同类任务上下文包含第一次教训

    集成 A 类第一批（A2+A3+A5+A4）→ 联调 1-3
      ├── 接入反思引擎到任务后处理链
      ├── 接入信号系统
      ├── 接入指标追踪
      ├── 联调测试 1-3
      └── 集成 A6 Compaction 到上下文引擎

═══════════════════════════════════════════════════════════════
Phase 3: Architect + 进化闭环（Day 13-19）
═══════════════════════════════════════════════════════════════

  我:
    集成 A7 Observer → 联调 4

    B5 — Architect 引擎（4-5 天）
      ├── 读取 Observer 报告 + 信号 + 规则
      ├── 问题诊断（按优先级排序）
      ├── 方案设计 + 审批级别判断
      ├── 执行修改（通过回滚系统）
      ├── 提案发送（通过 Telegram）
      ├── 验证期管理
      └── 联调 5（与开发并行）

    B6 — Bootstrap 引导流程（1-2 天）
      ├── 首次对话引导（3 阶段）
      ├── 用户背景导入 + 项目导入
      └── 偏好确认 + 默认配置

═══════════════════════════════════════════════════════════════
Phase 4: 端到端集成（Day 20-23）
═══════════════════════════════════════════════════════════════

  我:
    B7 — 端到端集成 + 调试
      ├── 联调 6-7
      ├── 定时任务配置（Cron：Observer 02:00, Architect 03:00）
      ├── 连续运行 3-5 天验证
      └── 验证 MVP 成功标准
```

### 6.2 Codex 任务提交顺序

```
Day 1（立即提交）:
  ├── Codex-A1: 种子规则 + 默认配置
  ├── Codex-A2: 回滚系统
  └── Codex-A3: 指标追踪系统

Day 3（Phase 1 开始时提交）:
  ├── Codex-A4: 信号系统
  ├── Codex-A5: 反思引擎
  ├── Codex-A6: Compaction 引擎
  └── Codex-A7: Observer 引擎
```

### 6.3 关键里程碑

| Day | 里程碑 | 验证方式 |
|-----|--------|---------|
| 2 | NanoBot 能通过 Telegram 对话 | 手动测试 |
| 5 | 修改规则文件后系统行为改变 | 手动测试 |
| 7 | A1-A3 交付并通过独立测试 | pytest |
| 10 | A4-A7 交付并通过独立测试 | pytest |
| 12 | 任务后处理链完整运行（联调 1-3 通过） | pytest integration |
| 15 | Observer 深度报告有可操作发现 | 联调 4 |
| 19 | Architect 生成有价值提案 + 回滚可靠 | 联调 5 |
| 23 | 端到端闭环运行 + MVP 成功标准 | 联调 7 + 人工验证 |

---

## 7. 需要技术调研的模块

### 7.1 必须调研（影响架构）

| 调研项 | 影响模块 | 调研内容 | 方式 |
|--------|---------|---------|------|
| **NanoBot 框架** | B1, B2, B4 | 源码结构、扩展点、Agent Loop 机制、通道注册、Provider 注册 | GitHub 源码阅读 + 文档 |
| **NanoBot Cron/Heartbeat** | B5（定时触发） | 如何注册定时任务、执行上下文 | 源码阅读 |
| **Telegram Bot API** | B4 | inline keyboard（审批按钮）、消息排队、webhook vs polling | Telegram 官方文档 |

### 7.2 建议调研（有参考价值）

| 调研项 | 影响模块 | 调研内容 | 方式 |
|--------|---------|---------|------|
| **Claude API 最佳实践** | B2, A5, A7 | system prompt 组装、KV-cache 优化、结构化输出 | Anthropic 文档 |
| **Gemini API** | A5, A7 | Gemini Flash 调用方式、结构化输出、长上下文 | Google AI 文档 |
| **Cursor/Windsurf 的规则系统** | A1（种子规则参考） | .cursorrules / .windsurfrules 的最佳实践 | GitHub 搜索 + 社区 |
| **AI Agent 反思机制** | A5 | Reflexion 论文、Generative Agents 的反思实现 | 论文 + GitHub |
| **上下文压缩最佳实践** | A6 | MemGPT 的 compaction、Claude 的 context caching | 论文 + 文档 |

### 7.3 调研执行计划

```
Phase 0 之前（Day 0）:
  ├── 调研 NanoBot 框架（2-3 小时）
  │     └── 启动 Researcher 子代理
  ├── 调研 Telegram Bot API 审批交互（1 小时）
  │     └── 主要看 inline keyboard
  └── 调研 Claude + Gemini API（1 小时）

Phase 1 开始前:
  └── 调研 Cursor/Windsurf 规则系统（作为 A1 种子规则参考）
        └── 在 A1 任务描述中要求 Codex 先调研

其余调研按需在开发过程中进行。
```

---

## 8. 我的子代理分工

我在开发 B 类模块时，以下任务适合用子代理并行：

### 8.1 Researcher 子代理（调研类）

| 任务 | 时机 | 输出 |
|------|------|------|
| NanoBot 源码分析 | Phase 0 前 | `.claude/memory-bank/research/nanobot-architecture.md` |
| Telegram inline keyboard 实现 | Phase 1 B4 开发前 | 代码示例 |
| Claude API system prompt 最佳实践 | Phase 1 B2 开发前 | 组装策略文档 |
| Gemini Flash API 结构化输出 | Phase 1 A5 开发前 | 接口示例 |
| AI Agent 反思机制参考 | Phase 1 A5 任务描述中 | 设计参考 |

### 8.2 Implementer 子代理（独立编码）

| 任务 | 时机 | 为什么适合子代理 |
|------|------|----------------|
| `conftest.py` 和测试 fixtures | Phase 0 | 模板化，不需要上下文 |
| `LLMClient` 统一接口 + MockLLMClient | Phase 0 | 接口明确，独立模块 |
| Telegram 消息模板渲染 | Phase 1 B4 | 纯模板逻辑，不涉及系统架构 |
| workspace 目录初始化脚本 | Phase 0 | 简单的 mkdir + touch |
| 联调测试文件骨架 | Phase 2 | 按联调方案生成测试框架 |

### 8.3 Reviewer 子代理（审查）

| 任务 | 时机 |
|------|------|
| 审查 Codex 交付的 A 类模块代码 | 每个 A 类模块完成后 |
| 审查联调测试通过后的集成代码 | 联调 3、5、7 完成后 |
| 审查种子规则内容一致性 | A1 完成后 |

### 8.4 子代理使用策略

```
我在开发 B2（规则解释器）时:
  ├── 主线：我写核心逻辑
  ├── 子代理 Researcher：调研 Claude API prompt 组装最佳实践
  └── 子代理 Implementer：写 conftest.py 和测试 fixtures

我在开发 B4（Telegram）时:
  ├── 主线：我写通道集成
  └── 子代理 Implementer：写消息模板渲染

我在集成 A 类模块时:
  ├── 主线：我写集成代码
  ├── 子代理 Reviewer：审查 Codex 交付的代码
  └── 子代理 Implementer：写联调测试

我在开发 B5（Architect）时:
  └── 主线：独占上下文，最复杂模块不拆分
```

---

## 附录 A: Codex 任务提交模板

每个提交给 Codex 的任务应包含以下结构：

```markdown
# 任务：[模块名称]

## 项目背景
> 一段话说明项目是什么，让 Codex 理解上下文。
> 详细背景见 docs/design/v3-2-system-design.md

## 你要做什么
[明确的任务描述]

## 接口定义
[完整的 class/method 签名和文档]

## 输入/输出格式
[数据结构定义和示例]

## 技术约束
- Python 3.11+
- 不用外部数据库，纯文件操作
- 异步方法用 async/await
- [模块特定约束]

## 测试要求
[需要通过的测试用例列表]

## 交付物
[文件路径列表]

## 验收标准
[checklist]

## 参考文档
- 完整设计：docs/design/v3-2-system-design.md 第 X 节
- 模块计划：docs/dev/mvp-module-plan.md 第 X 节
- 开发指南：docs/dev/mvp-dev-guide.md 第 X 节
```

---

## 附录 B: 配置文件模板

### evo_config.yaml

```yaml
# 进化系统配置

# 多 Provider LLM 注册表
llm:
  providers:
    opus:
      type: anthropic
      model_id: "claude-opus-4-6"
      api_key_env: "PROXY_API_KEY"
      base_url: "https://vtok.ai"
    qwen:
      type: openai
      model_id: "qwen/qwen3-235b-a22b"
      api_key_env: "NVIDIA_API_KEY"
      base_url: "https://integrate.api.nvidia.com/v1"
      extra_body:
        chat_template_kwargs:
          thinking: false
  aliases:
    gemini-flash: qwen    # 向后兼容

agent_loop:
  model: "opus"

observer:
  light_mode:
    enabled: true
    model: "qwen"
  deep_mode:
    schedule: "02:00"
    model: "opus"
    emergency_threshold: 3  # 24h 内 critical 信号数

architect:
  schedule: "03:00"
  model: "opus"
  max_daily_proposals: 3

approval:
  levels:
    0: {action: "auto_execute", notify: false}
    1: {action: "execute_then_notify", notify: true}
    2: {action: "propose_then_wait", notify: true}
    3: {action: "discuss", notify: true}

rollback:
  auto_threshold: 0.20
  backup_retention_days: 30

blast_radius:
  level_0_max_files: 1
  level_1_max_files: 3

rate_limit:
  max_daily_modifications: 5
  min_interval_hours: 2

communication:
  quiet_hours: "22:00-08:00"
  daily_report: true
  daily_report_time: "08:30"

evolution_strategy:
  initial: "cautious"
  transitions:
    cautious_to_balanced: {min_days: 7, min_success_rate: 0.70}
    balanced_to_growth: {stale_days: 14, min_success_rate: 0.80}
    any_to_repair: {success_drop: 0.20, critical_threshold: 3}
    repair_to_balanced: {recovery_days: 2}
```
