# MVP 模块划分与并行开发计划

> **日期**: 2026-02-23
> **目标**: 将 MVP 拆分为独立模块，支持多代理并行开发

---

## 1. 模块依赖关系图

```
                    ┌──────────────┐
                    │  Phase 0     │
                    │  NanoBot 基座 │
                    └──────┬───────┘
                           │
              ┌────────────┼────────────┐
              ▼            ▼            ▼
     ┌────────────┐ ┌───────────┐ ┌──────────────┐
     │ 规则解释器  │ │ Telegram  │ │ LLM 网关     │
     │ (rules/)   │ │ 通道适配   │ │ (Opus+Gemini)│
     └─────┬──────┘ └─────┬─────┘ └──────┬───────┘
           │              │              │
           ▼              │              │
     ┌───────────────┐    │              │
     │ 上下文引擎     │◄───┤              │
     │ (核心中枢)     │    │              │
     └──┬──┬──┬──┬──┘    │              │
        │  │  │  │       │              │
        ▼  │  │  ▼       │              │
  ┌──────┐ │  │ ┌──────┐ │         ┌────┴────┐
  │记忆   │ │  │ │种子   │ │         │反思引擎  │
  │系统   │ │  │ │规则+  │ │         │(Gemini) │
  │      │ │  │ │默认   │ │         └────┬────┘
  └──┬───┘ │  │ │配置   │ │              │
     │     │  │ └──────┘ │              ▼
     │     │  │          │         ┌─────────┐
     │     │  └──────────┤         │信号系统   │
     │     │             │         └────┬────┘
     │     ▼             │              │
     │  ┌──────────┐     │              ▼
     │  │Compaction│     │         ┌─────────┐
     │  └──────────┘     │         │Observer  │
     │                   │         └────┬────┘
     │                   │              │
     │                   │              ▼
     │                   │    ┌─────────────────┐
     │                   │    │   Architect      │
     │                   │    │ + 审批流程        │◄── ┌──────────┐
     │                   │    └────────┬────────┘    │回滚系统   │
     │                   │             │             └──────────┘
     │                   │             ▼
     │                   │    ┌─────────────────┐
     │                   └───►│  指标系统        │
     │                        └─────────────────┘
     │
     └──────────►  Bootstrap 引导流程
```

---

## 2. 模块分类：独立度评估

### A 类：独立模块（可交给 Codex 并行开发）

这些模块接口清晰、耦合度低，只需定义好输入/输出格式即可独立开发和测试。

| # | 模块 | 独立度 | 原因 | 预计工作量 |
|---|------|:------:|------|:---------:|
| A1 | **种子规则 + Best Practice 默认配置** | ⭐⭐⭐⭐⭐ | 纯内容文件，无代码依赖 | 1 天 |
| A2 | **回滚系统** | ⭐⭐⭐⭐⭐ | 纯文件操作，输入=文件路径，输出=备份/恢复 | 1-2 天 |
| A3 | **指标追踪系统** | ⭐⭐⭐⭐⭐ | 纯数据收集，输入=事件，输出=YAML 文件 | 1-2 天 |
| A4 | **信号系统** | ⭐⭐⭐⭐ | 规则匹配+存储，输入=反思输出，输出=信号 JSONL | 2-3 天 |
| A5 | **反思引擎** | ⭐⭐⭐⭐ | 独立 LLM 调用，输入=任务轨迹，输出=结构化反思 | 2-3 天 |
| A6 | **Compaction 引擎** | ⭐⭐⭐⭐ | 独立压缩逻辑，输入=对话历史，输出=压缩摘要 | 2-3 天 |
| A7 | **Observer 引擎** | ⭐⭐⭐ | 两种模式，但需要读取多种数据源 | 3-4 天 |

### B 类：核心模块（由我开发，需要大量上下文和集成知识）

这些模块耦合度高，是系统的"神经中枢"，需要深入理解 NanoBot 架构和模块间交互。

| # | 模块 | 为什么不能独立 | 预计工作量 |
|---|------|--------------|:---------:|
| B1 | **NanoBot 基座搭建 + LLM 网关** | 所有模块的基础，需要通读 NanoBot 源码 | 1-2 天 |
| B2 | **规则解释器 + 上下文引擎** | 系统核心中枢，决定每次 LLM 看到什么 | 3-4 天 |
| B3 | **记忆系统（存储+检索+注入）** | 与上下文引擎深度耦合，写入/读取/注入一体 | 2-3 天 |
| B4 | **Telegram 通道 + 审批流程** | 与 NanoBot 通道系统深度集成 | 2-3 天 |
| B5 | **Architect 引擎** | 最复杂模块，读取所有子系统数据做决策 | 4-5 天 |
| B6 | **Bootstrap 引导流程** | 串联记忆+规则+配置+Telegram，首次体验关键 | 1-2 天 |
| B7 | **端到端集成 + 调试** | 所有模块的粘合剂 | 2-3 天 |

---

## 3. 独立模块详细需求（Codex 交付标准）

### A1: 种子规则 + Best Practice 默认配置

**交付物**：
```
config/defaults/
  task_strategies.md        # 默认任务策略
  interaction_patterns.md   # 默认交互模式（含执行前澄清规则）
  error_patterns.md         # 已知 AI 错误模式

workspace/rules/constitution/
  identity.md               # 系统身份和人格
  safety_boundaries.md      # 安全红线
  approval_levels.md        # 四级审批定义
  meta_rules.md             # 规则系统运作方式
  core_orchestration.md     # 核心编排逻辑

workspace/rules/experience/
  task_strategies.md         # 初始为 defaults 的副本
  reflection_templates.md    # 反思维度和格式
  memory_strategies.md       # 记忆存取策略
  interaction_patterns.md    # 初始为 defaults 的副本
  user_preferences.md        # 空文件
  error_patterns.md          # 初始为 defaults 的副本
  tool_usage_tips.md         # 空文件
```

**需求**：
- 宪法级规则：参考设计文档 5.2.1，定义系统身份、安全边界、审批级别、元规则、编排逻辑
- 经验级默认值：参考 5.2.2 + 8.2.1，写出通用的 Best Practice
- `interaction_patterns.md` 必须包含"执行前主动澄清"规则
- `error_patterns.md` 必须包含设计文档 5.5.2 中的四种 AI 常见错误模式
- 每个文件需有清晰的结构（YAML front matter + Markdown 正文）

**验收标准**：
- [ ] 5 个宪法级规则文件内容完整且互不矛盾
- [ ] 5 个经验级规则文件有合理的默认策略
- [ ] identity.md 定义了系统人格和对话风格
- [ ] safety_boundaries.md 定义了不可修改底线
- [ ] approval_levels.md 定义了 Level 0-3 的明确边界和示例
- [ ] 所有文件人类可读，无需代码即可理解

**参考**：设计文档 5.2.1, 5.2.2, 8.2.1, 6.7

---

### A2: 回滚系统

**交付物**：
```
extensions/evolution/rollback.py
tests/test_rollback.py
```

**接口定义**：
```python
class RollbackManager:
    def __init__(self, workspace_path: str, backup_dir: str = "backups"):
        """初始化。workspace_path 是 workspace/ 目录路径。"""

    def backup(self, file_paths: list[str], proposal_id: str) -> str:
        """
        修改前备份指定文件。
        返回 backup_id（格式：{timestamp}_{proposal_id}）
        备份存储在 workspace/backups/{backup_id}/ 下，保持原始目录结构。
        """

    def rollback(self, backup_id: str) -> dict:
        """
        回滚到指定备份。
        返回 {"restored_files": [...], "status": "success"/"failed"}
        """

    def list_backups(self, limit: int = 10) -> list[dict]:
        """
        列出最近的备份。
        返回 [{"backup_id": "...", "proposal_id": "...", "timestamp": "...",
                "files": [...], "status": "active"/"rolled_back"}]
        """

    def cleanup(self, retention_days: int = 30):
        """清理过期备份。"""

    def auto_rollback_check(self, proposal_id: str,
                            current_metrics: dict,
                            baseline_metrics: dict,
                            threshold: float = 0.20) -> bool:
        """
        检查是否需要自动回滚。
        如果 current 相对 baseline 恶化超过 threshold，执行回滚并返回 True。
        """
```

**验收标准**：
- [ ] backup() 创建完整的目录结构副本
- [ ] rollback() 能准确恢复文件到备份状态
- [ ] 并发安全：两次 backup 不会互相干扰
- [ ] auto_rollback_check 正确比较指标并触发回滚
- [ ] cleanup 只删除超过 retention 天数的备份
- [ ] 所有方法有完整的错误处理（文件不存在、权限问题等）
- [ ] 测试覆盖：正常备份恢复、回滚后再回滚、空备份、损坏备份

---

### A3: 指标追踪系统

**交付物**：
```
extensions/evolution/metrics.py
tests/test_metrics.py
```

**接口定义**：
```python
class MetricsTracker:
    def __init__(self, metrics_dir: str):
        """metrics_dir 指向 workspace/metrics/"""

    def record_task(self, task_id: str, outcome: str, tokens: int,
                    model: str, duration_ms: int,
                    user_corrections: int = 0,
                    error_type: str | None = None):
        """
        记录一次任务结果。
        outcome: "SUCCESS" | "PARTIAL" | "FAILURE"
        error_type: "ERROR" | "PREFERENCE" | None
        """

    def record_signal(self, signal_type: str, priority: str, source: str):
        """记录一次信号检测。"""

    def record_proposal(self, proposal_id: str, level: int,
                        status: str, files_affected: list[str]):
        """
        记录一次 Architect 提案。
        status: "proposed" | "approved" | "rejected" | "executed" | "rolled_back" | "validated"
        """

    def get_daily_summary(self, date: str | None = None) -> dict:
        """
        获取某天的汇总指标。默认今天。
        返回格式见设计文档 12.2 核心指标追踪。
        """

    def get_success_rate(self, days: int = 7) -> float:
        """获取过去 N 天的任务成功率。"""

    def get_trend(self, metric: str, days: int = 30) -> list[dict]:
        """获取某指标的趋势数据（日粒度）。"""

    def should_trigger_repair(self) -> bool:
        """
        判断是否应该切换到 repair 模式。
        条件：3 天成功率下降 >20% 或 24h 内 critical ≥3
        """

    def flush_daily(self):
        """将今日数据写入 daily_metrics.yaml 文件。"""
```

**数据存储格式**：
```
workspace/metrics/
  daily/
    2026-02-25.yaml    # 每日汇总（格式见设计文档 12.2）
  events.jsonl         # 实时事件流（task/signal/proposal 事件）
```

**验收标准**：
- [ ] record_task 正确写入 events.jsonl
- [ ] get_daily_summary 正确汇总当日所有事件
- [ ] get_success_rate 正确计算滑动窗口成功率
- [ ] should_trigger_repair 正确判断 repair 触发条件
- [ ] flush_daily 生成与设计文档一致的 YAML 格式
- [ ] 高频写入不丢数据（JSONL 追加写入）
- [ ] 测试覆盖：空数据、边界日期、跨天统计

---

### A4: 信号系统

**交付物**：
```
extensions/signals/detector.py
extensions/signals/store.py
tests/test_signals.py
```

**接口定义**：
```python
class SignalDetector:
    def __init__(self, signal_store: SignalStore):
        pass

    def detect(self, reflection_output: dict, task_context: dict) -> list[dict]:
        """
        从反思输出和任务上下文中检测信号。

        reflection_output 格式：
          {"task_id": "task_042", "type": "ERROR"|"PREFERENCE",
           "outcome": "SUCCESS"|"PARTIAL"|"FAILURE",
           "lesson": "...", "root_cause": "..."|None}

        task_context 格式：
          {"tokens_used": 3200, "model": "opus", "duration_ms": 15000,
           "user_corrections": 1, "task_type": "analysis"}

        返回检测到的信号列表：
          [{"signal_type": "user_correction"|"repeated_error"|"performance_degradation"|
                          "rule_unused"|"capability_gap"|"efficiency_opportunity"|
                          "user_pattern"|"rule_validated",
            "priority": "LOW"|"MEDIUM"|"HIGH"|"CRITICAL",
            "source": "...",
            "description": "...",
            "related_tasks": ["task_042"],
            "timestamp": "2026-02-25T10:15:30"}]
        """

    def detect_patterns(self, lookback_hours: int = 168) -> list[dict]:
        """
        检测跨任务的信号模式（如 repeated_error, performance_degradation）。
        lookback_hours 默认 7 天。
        """


class SignalStore:
    def __init__(self, signals_dir: str):
        """signals_dir 指向 workspace/signals/"""

    def add(self, signal: dict):
        """写入 active.jsonl"""

    def get_active(self, priority: str | None = None,
                   signal_type: str | None = None) -> list[dict]:
        """获取未处理的信号，可按优先级和类型过滤。"""

    def mark_handled(self, signal_ids: list[str], handler: str):
        """标记信号为已处理，移到 archive.jsonl。"""

    def count_recent(self, signal_type: str, hours: int = 24) -> int:
        """统计最近 N 小时内某类型信号数量。"""
```

**信号类型定义**（来自设计文档）：

| 信号类型 | 触发条件 | 默认优先级 |
|---------|---------|----------|
| `user_correction` | 用户纠正了系统输出 | MEDIUM |
| `repeated_error` | 同类错误 7 天内 ≥2 次 | HIGH |
| `performance_degradation` | 3 天成功率下降 >15% | CRITICAL |
| `rule_unused` | 规则 14 天未触发 | LOW |
| `capability_gap` | 任务因能力不足失败 | MEDIUM |
| `efficiency_opportunity` | token 消耗异常高 | LOW |
| `user_pattern` | 用户行为重复出现 | MEDIUM |
| `rule_validated` | 规则被使用且效果良好 | LOW |

**验收标准**：
- [ ] 8 种信号类型全部实现，触发条件与上表一致
- [ ] detect() 能从单次反思输出中提取信号
- [ ] detect_patterns() 能从历史数据中识别跨任务模式
- [ ] SignalStore 的 JSONL 读写正确，支持按条件过滤
- [ ] mark_handled 正确将信号从 active 移到 archive
- [ ] count_recent 正确统计时间窗口内的信号
- [ ] 测试覆盖：各信号类型触发、边界条件、空数据

---

### A5: 反思引擎

**交付物**：
```
extensions/memory/reflection.py
tests/test_reflection.py
```

**接口定义**：
```python
class ReflectionEngine:
    def __init__(self, llm_client, memory_dir: str):
        """
        llm_client: 可调用 LLM 的客户端（Gemini Flash）
        memory_dir: workspace/memory/ 路径
        """

    async def lightweight_reflect(self, task_trace: dict) -> dict:
        """
        每次任务完成后的轻量反思（Gemini Flash, ~几百 token）。

        task_trace 格式：
          {"task_id": "task_042",
           "user_message": "...",
           "system_response": "...",
           "user_feedback": "..." | None,   # 用户的纠正或确认
           "tools_used": [...],
           "tokens_used": 3200,
           "model": "opus",
           "duration_ms": 15000}

        返回：
          {"task_id": "task_042",
           "type": "ERROR" | "PREFERENCE" | "NONE",
           "outcome": "SUCCESS" | "PARTIAL" | "FAILURE",
           "lesson": "做了错误假设——以为用户要技术方案，实际要产品策略",
           "root_cause": "wrong_assumption" | "missed_consideration" |
                        "tool_misuse" | "knowledge_gap" | None,
           "reusable_experience": "..." | None}
        """

    def write_reflection(self, reflection: dict):
        """
        将反思结果写入对应文件：
        - ERROR 类型 → 追加到 workspace/rules/experience/error_patterns.md
        - PREFERENCE 类型 → 追加到 workspace/memory/user/preferences.md
        - 所有类型 → 写入 Observer 轻量日志
        """
```

**LLM 调用的 Prompt 模板**（供实现参考）：

```
你是一个反思引擎。分析以下任务执行轨迹，提取教训。

任务轨迹：
{task_trace}

请按以下格式输出：
1. 分类（ERROR/PREFERENCE/NONE）：
   - ERROR: 有正确答案但做错了（错误假设、遗漏考虑、工具误用、知识不足）
   - PREFERENCE: 没有标准答案，只是不符合用户习惯（回复长度、格式、风格）
   - NONE: 无异常
2. 结果（SUCCESS/PARTIAL/FAILURE）
3. 一句话教训
4. 如果是 ERROR，根因分类
5. 可复用的经验（如有）
```

**验收标准**：
- [ ] lightweight_reflect 能正确分类 ERROR vs PREFERENCE vs NONE
- [ ] ERROR 类型的反思包含 root_cause 分类
- [ ] write_reflection 将不同类型写入不同文件
- [ ] LLM 调用有超时和错误处理
- [ ] 输出格式稳定可解析
- [ ] 测试覆盖：成功任务、失败任务、用户纠正、无反馈
- [ ] 测试可用 mock LLM client 运行（不需真实 API）

---

### A6: Compaction 引擎

**交付物**：
```
extensions/context/compaction.py
tests/test_compaction.py
```

**接口定义**：
```python
class CompactionEngine:
    def __init__(self, llm_client, memory_dir: str):
        """
        llm_client: LLM 客户端（用于生成摘要）
        memory_dir: workspace/memory/ 路径
        """

    async def should_compact(self, current_tokens: int, budget: int) -> bool:
        """当 current_tokens / budget >= 0.85 时返回 True。"""

    async def compact(self, conversation_history: list[dict],
                      keep_recent: int = 5) -> dict:
        """
        执行 Compaction。

        conversation_history: [{"role": "user"|"assistant", "content": "...", "timestamp": "..."}]
        keep_recent: 保留最近 N 轮完整对话

        流程：
        1. Pre-Compaction Flush: 提取关键信息写入持久记忆
        2. 生成压缩摘要（原文的 10-20%）
        3. 认知层级转化：事实 → 规律 → 策略
        4. 保留最近 keep_recent 轮，其余替换为摘要
        5. 压缩验证：检查关键信息是否保留

        返回：
          {"compacted_history": [...],      # 新的对话历史
           "summary": "...",                # 生成的摘要
           "flushed_to_memory": [...],      # 写入持久记忆的条目
           "original_tokens": 12000,
           "compacted_tokens": 4500,
           "compression_ratio": 0.375,
           "key_decisions_preserved": 5,
           "key_decisions_total": 5}
        """

    async def verify_compaction(self, original: list[dict],
                                compacted: dict) -> dict:
        """
        验证压缩质量。
        返回 {"quality": "good"|"acceptable"|"poor",
               "missing_key_info": [...]}
        """
```

**验收标准**：
- [ ] should_compact 在 85% 阈值时正确触发
- [ ] compact 保留最近 N 轮完整对话
- [ ] compact 生成的摘要为原文 10-20%
- [ ] Pre-Compaction Flush 正确提取关键决策写入记忆文件
- [ ] 认知层级转化：输出包含策略级提炼
- [ ] verify_compaction 能检测关键信息丢失
- [ ] 全程不向用户发送任何确认或通知（无感化）
- [ ] 测试覆盖：短对话（不需压缩）、长对话、决策密集对话、闲聊对话

---

### A7: Observer 引擎

**交付物**：
```
extensions/observer/engine.py
extensions/observer/scheduler.py
tests/test_observer.py
```

**接口定义**：
```python
class ObserverEngine:
    def __init__(self, llm_client_gemini, llm_client_opus,
                 workspace_path: str):
        pass

    async def lightweight_observe(self, task_trace: dict) -> dict:
        """
        每次任务后的轻量观察（Gemini Flash）。
        写入 workspace/observations/light_logs/ 的 JSONL。

        返回 JSONL 记录：
          {"timestamp": "...", "task_id": "...", "outcome": "...",
           "tokens": 2800, "model": "opus",
           "signals": ["user_pattern"],
           "error_type": "ERROR"|"PREFERENCE"|None,
           "note": "..."}
        """

    async def deep_analyze(self, trigger: str = "daily") -> dict:
        """
        深度分析（Opus，数千 token）。
        trigger: "daily" | "emergency"

        读取：当日所有轻量日志 + 规则文件 + Big Picture
        重点关注：真正错误（而非偏好偏差）

        输出深度报告写入 workspace/observations/deep_reports/{date}.md

        返回报告结构：
          {"trigger": "daily"|"emergency",
           "date": "2026-02-25",
           "tasks_analyzed": 12,
           "key_findings": [
             {"type": "error_pattern"|"efficiency"|"skill_gap"|"preference",
              "description": "...",
              "confidence": "HIGH"|"MEDIUM"|"LOW",
              "related_signals": [...],
              "recommendation": "..."}
           ],
           "overall_health": "good"|"degraded"|"critical"}
        """


class ObserverScheduler:
    def __init__(self, observer: ObserverEngine,
                 signal_store: SignalStore,
                 metrics: MetricsTracker,
                 config: dict):
        """
        config 包含：
          daily_time: "02:00"   # 每日定时
          emergency_threshold: 3  # 24h 内 critical 信号数触发紧急
        """

    async def check_and_run(self):
        """
        检查是否需要运行深度分析：
        - 到了每日定时时间 → deep_analyze("daily")
        - 24h 内 critical 信号 ≥ threshold → deep_analyze("emergency")
        """

    def get_next_run_time(self) -> str:
        """返回下次计划运行时间。"""
```

**验收标准**：
- [ ] lightweight_observe 正确写入 JSONL 格式日志
- [ ] deep_analyze 读取当日所有日志并生成结构化报告
- [ ] deep_analyze 的 key_findings 按优先级排序（error > efficiency > skill > preference）
- [ ] 深度报告写入 Markdown 文件，人类可读
- [ ] ObserverScheduler 正确判断定时触发和紧急触发
- [ ] 紧急触发只在 24h 内 ≥3 次 critical 时启动
- [ ] 测试覆盖：正常日、无任务日、紧急触发日
- [ ] 测试可用 mock LLM client 运行

---

## 4. 核心模块开发顺序（我来做）

```
B1: NanoBot 基座 + LLM 网关           ─── Phase 0 (1-2 天)
  │
  ├── B2: 规则解释器 + 上下文引擎      ─── Phase 1 (3-4 天)
  │     │
  │     └── B3: 记忆系统               ─── Phase 1-2 (2-3 天)
  │
  ├── B4: Telegram 通道 + 审批流程      ─── Phase 1 (2-3 天，可与 B2 并行)
  │
  ├── B5: Architect 引擎               ─── Phase 3 (4-5 天，需要 A4-A7 完成)
  │     │
  │     └── 集成 A 类模块
  │
  ├── B6: Bootstrap 引导流程            ─── Phase 3 (1-2 天)
  │
  └── B7: 端到端集成 + 调试             ─── Phase 4 (2-3 天)
```

---

## 5. 并行开发时间线

```
Week 1:
  ┌─────────────────────────────────────────────────────┐
  │ 我: B1 NanoBot 基座 → B2 规则解释器+上下文引擎       │
  │     → B4 Telegram 通道                              │
  ├─────────────────────────────────────────────────────┤
  │ Codex-1: A1 种子规则 + 默认配置                      │ ← 1 天完成
  │ Codex-2: A2 回滚系统                                │ ← 1-2 天完成
  │ Codex-3: A3 指标追踪系统                             │ ← 1-2 天完成
  └─────────────────────────────────────────────────────┘

Week 2:
  ┌─────────────────────────────────────────────────────┐
  │ 我: B3 记忆系统 → 集成 A1 种子规则                   │
  ├─────────────────────────────────────────────────────┤
  │ Codex-4: A4 信号系统                                │ ← 2-3 天完成
  │ Codex-5: A5 反思引擎                                │ ← 2-3 天完成
  │ Codex-6: A6 Compaction 引擎                         │ ← 2-3 天完成
  │ Codex-7: A7 Observer 引擎                           │ ← 3-4 天完成
  └─────────────────────────────────────────────────────┘

Week 3:
  ┌─────────────────────────────────────────────────────┐
  │ 我: 集成 A2-A7 → B5 Architect 引擎                  │
  │     → B6 Bootstrap 引导                             │
  └─────────────────────────────────────────────────────┘

Week 4:
  ┌─────────────────────────────────────────────────────┐
  │ 我: B7 端到端集成 + 调试 + 验证 MVP 成功标准          │
  └─────────────────────────────────────────────────────┘
```

**关键路径**：B1 → B2 → B3 → 集成 A 类 → B5 → B7

**并行最大化**：Week 1-2 期间 7 个 Codex 任务可同时进行，与我的核心开发并行。

---

## 6. 集成契约（所有模块共用）

### 6.1 文件系统约定

所有模块操作的工作目录为 `workspace/`，目录结构固定：
```
workspace/
├── rules/constitution/     # 宪法级规则（A1 创建）
├── rules/experience/       # 经验级规则（A1 创建，Architect 修改）
├── memory/user/            # 用户级记忆
├── memory/projects/        # 项目级记忆
├── memory/conversations/   # 对话记录
├── memory/daily_summaries/ # 每日摘要
├── skills/                 # 技能文件
├── observations/light_logs/  # Observer 轻量日志 (JSONL)
├── observations/deep_reports/  # Observer 深度报告 (MD)
├── signals/active.jsonl    # 未处理信号
├── signals/archive.jsonl   # 已处理信号
├── architect/proposals/    # Architect 提案
├── architect/modifications/  # 修改记录
├── architect/big_picture.md  # 系统蓝图
├── backups/                # 回滚备份
├── metrics/daily/          # 每日指标
├── metrics/events.jsonl    # 事件流
└── logs/                   # 运行日志
```

### 6.2 通用数据格式

- **时间戳**：ISO 8601，`2026-02-25T10:15:30`
- **ID 格式**：`task_042`, `signal_001`, `proposal_023`, `backup_20260225_101530_023`
- **JSONL 文件**：每行一个 JSON 对象，追加写入
- **YAML 文件**：标准 YAML，`PyYAML` 兼容
- **Markdown 文件**：人类可读，可包含 YAML front matter

### 6.3 LLM Client 接口

所有需要调用 LLM 的模块（A5, A6, A7）使用统一接口：

```python
class LLMClient:
    async def complete(self, system_prompt: str, user_message: str,
                       model: str = "gemini-flash",
                       max_tokens: int = 2000) -> str:
        """返回 LLM 的文本响应。"""
```

开发时可用 Mock：
```python
class MockLLMClient:
    async def complete(self, system_prompt, user_message, **kwargs):
        return '{"type": "NONE", "outcome": "SUCCESS", "lesson": "mock"}'
```

### 6.4 错误处理约定

- 文件操作失败 → 记录日志 + 返回错误状态（不抛异常到调用方）
- LLM 调用超时 → 重试 1 次 → 返回 None
- 数据格式错误 → 记录日志 + 跳过该条目

---

## 7. 任务分配建议

### 给 Codex 的任务（独立模块）

| 优先级 | 模块 | 预估 | 建议顺序 |
|:------:|------|:----:|:-------:|
| P0 | A1 种子规则 + 默认配置 | 1 天 | 最先（B2 需要） |
| P0 | A2 回滚系统 | 1-2 天 | 第一批 |
| P0 | A3 指标追踪 | 1-2 天 | 第一批 |
| P1 | A4 信号系统 | 2-3 天 | 第二批 |
| P1 | A5 反思引擎 | 2-3 天 | 第二批 |
| P1 | A6 Compaction | 2-3 天 | 第二批 |
| P2 | A7 Observer | 3-4 天 | 第二批（依赖 A4） |

### 我负责的任务（核心+集成）

| 优先级 | 模块 | 预估 | 顺序 |
|:------:|------|:----:|:----:|
| P0 | B1 NanoBot 基座 + LLM 网关 | 1-2 天 | 1 |
| P0 | B2 规则解释器 + 上下文引擎 | 3-4 天 | 2 |
| P0 | B4 Telegram 通道 + 审批 | 2-3 天 | 2（与 B2 并行） |
| P1 | B3 记忆系统 | 2-3 天 | 3 |
| P1 | B5 Architect 引擎 | 4-5 天 | 4 |
| P2 | B6 Bootstrap 引导 | 1-2 天 | 5 |
| P2 | B7 集成 + 调试 | 2-3 天 | 6 |

---

## 8. MVP 成功标准（最终验收）

从设计文档 15.3 摘出，集成后验证：

| # | 标准 | 度量 |
|---|------|------|
| 1 | 闭环完整性 | 连续 5 个同类任务，第 5 次明显优于第 1 次 |
| 2 | Observer 有效性 | 20 条观察笔记中 >50% 含可操作洞察 |
| 3 | Architect 可用性 | 提案包含问题+方案+预期效果+影响评估 |
| 4 | 主动沟通 | 一周内主动消息中有用占比 >70% |
| 5 | 规则活性 | 两周内至少有规则被验证或修改 |
| 6 | 回滚可靠性 | 故意引入坏规则，自动回滚生效 |
| 7 | 交互闭环 | Telegram 完成完整对话+审批流程 |
