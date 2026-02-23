# Codex 开发指南

## 项目概述

AI自进化系统 (evo-agent) — 一个规则驱动的自我进化 AI Agent 系统。你负责开发 A 类独立模块（A1-A7），每个模块有独立的 feature branch。

## 仓库结构

```
├── core/                  # 核心模块（B类，不要修改）
│   ├── llm_client.py      # LLM 客户端抽象
│   └── workspace.py       # 工作空间管理
├── extensions/            # 扩展模块（你的工作区域）
│   ├── evolution/         # A2 回滚, A3 指标
│   ├── signals/           # A4 信号系统
│   ├── context/           # A6 Compaction
│   ├── memory/            # A5 反思引擎
│   └── observer/          # A7 Observer
├── config/                # 配置文件
│   └── defaults/          # A1 默认配置
├── workspace/             # 运行时数据目录
│   └── rules/             # A1 规则文件
├── tests/                 # 测试
├── docs/dev/codex-tasks/  # 你的任务详细规格书
└── pyproject.toml         # 项目配置
```

## 分支策略

每个任务对应一个 feature branch，从 `main` 分出：

| 分支 | 任务 | 优先级 |
|------|------|--------|
| `feat/A1-seed-rules` | 种子规则 + 默认配置 | P0 |
| `feat/A2-rollback` | 回滚系统 | P0 |
| `feat/A3-metrics` | 指标追踪 | P0 |
| `feat/A4-signals` | 信号系统 | P1 |
| `feat/A5-reflection` | 反思引擎 | P1 |
| `feat/A6-compaction` | Compaction 引擎 | P1 |
| `feat/A7-observer` | Observer 引擎 | P2 |

### 批次划分

- **批次1（立即可做）**: A1, A2, A3 — 完全独立，无依赖
- **批次2（批次1合并后）**: A4, A5, A6, A7 — 部分依赖 A3

## 任务规格书

每个任务的详细规格在 `docs/dev/codex-tasks/` 下：

- [A1-seed-rules.md](../docs/dev/codex-tasks/A1-seed-rules.md)
- [A2-rollback.md](../docs/dev/codex-tasks/A2-rollback.md)
- [A3-metrics.md](../docs/dev/codex-tasks/A3-metrics.md)
- [A4-signals.md](../docs/dev/codex-tasks/A4-signals.md)
- [A5-reflection.md](../docs/dev/codex-tasks/A5-reflection.md)
- [A6-compaction.md](../docs/dev/codex-tasks/A6-compaction.md)
- [A7-observer.md](../docs/dev/codex-tasks/A7-observer.md)

**务必先读对应的规格书再开始编码。**

## 开发规范

### Python 版本与依赖

- Python >= 3.11
- 依赖见 `pyproject.toml`
- 测试框架: pytest + pytest-asyncio

### 代码风格

- 类型注解: 所有公开方法必须有类型注解
- 异步: 涉及 LLM 调用的方法用 `async def`
- 文档字符串: 每个类和公开方法写 docstring
- 命名: snake_case（变量/函数），PascalCase（类）

### 文件创建规则

每个任务只创建规格书中列出的文件，不要修改以下文件：

- `core/` 下的任何文件
- `pyproject.toml`（如需新依赖，在 PR 描述中说明）
- 其他任务的文件

### 测试要求

- 每个模块必须有对应的 `tests/test_*.py`
- 使用 `pytest` 运行: `python -m pytest tests/test_xxx.py -v`
- LLM 调用必须 mock，不要依赖真实 API
- 测试覆盖: 正常路径 + 边界情况 + 错误处理

### 运行测试

```bash
# 激活虚拟环境
source .venv/bin/activate

# 运行单个测试文件
python -m pytest tests/test_rollback.py -v

# 运行所有测试
python -m pytest tests/ -v
```

## 各任务要点速查

### A1 - 种子规则（纯 Markdown，15 个文件）

无 Python 代码，直接创建 Markdown 文件：

- `config/defaults/` — 3 个默认配置文件
  - `task_strategies.md`, `interaction_patterns.md`, `error_patterns.md`
- `workspace/rules/constitution/` — 5 个宪法规则文件
  - `identity.md`, `safety_boundaries.md`, `approval_levels.md`, `meta_rules.md`, `core_orchestration.md`
- `workspace/rules/experience/` — 7 个经验规则文件
  - `task_strategies.md`, `interaction_patterns.md`, `error_patterns.md` (从 defaults 复制并扩展)
  - `reflection_templates.md`, `memory_strategies.md` (可执行模板骨架，有结构有占位)
  - `user_preferences.md`, `tool_usage_tips.md` (空模板，运行时由系统填充)

参考 `docs/design/v3-3-appendix-rules-templates.md` 获取模板。

**已确认的决策：**
- 不使用 YAML front matter（按 A1 规格书约束）
- reflection_templates.md / memory_strategies.md 做可执行骨架（有结构但内容待填充）
- user_preferences.md / tool_usage_tips.md 保持空模板

### A2 - 回滚系统

```python
# extensions/evolution/rollback.py
class RollbackManager:
    def backup(file_paths, proposal_id) -> str: ...
    def rollback(backup_id) -> dict: ...
    def list_backups(limit=10) -> list[dict]: ...
    def cleanup(retention_days=30): ...
    def auto_rollback_check(proposal_id, current_metrics, baseline_metrics, threshold=0.20) -> bool: ...
```

存储: `workspace/backups/{backup_id}/` + `metadata.json`

### A3 - 指标追踪

```python
# extensions/evolution/metrics.py
class MetricsTracker:
    def record_task(task_id, outcome, tokens, model, duration_ms, ...): ...
    def record_signal(signal_type, priority, source): ...
    def record_proposal(proposal_id, level, status, files_affected): ...
    def get_daily_summary(target_date) -> dict: ...
    def get_success_rate(days=7) -> float: ...
    def get_trend(metric, days=30) -> list[dict]: ...
    def should_trigger_repair() -> bool: ...
```

存储: `workspace/metrics/events.jsonl` (append-only) + `workspace/metrics/daily/{date}.yaml`

### A4 - 信号系统

```python
# extensions/signals/store.py
class SignalStore:
    def add(signal) -> None: ...
    def get_active(priority, signal_type) -> list[dict]: ...
    def mark_handled(signal_ids, handler) -> None: ...
    def count_recent(signal_type, priority, hours=24) -> int: ...

# extensions/signals/detector.py
class SignalDetector:
    def detect(reflection_output, task_context) -> list[dict]: ...
    def detect_patterns(lookback_hours=168) -> list[dict]: ...
```

8 种信号类型: user_correction, task_failure, repeated_error, performance_degradation, rule_unused, capability_gap, efficiency_opportunity, user_pattern, rule_validated

### A5 - 反思引擎

```python
# extensions/memory/reflection.py
class ReflectionEngine:
    async def lightweight_reflect(task_trace) -> dict: ...
    def write_reflection(reflection) -> None: ...
```

使用 gemini-flash 模型。输出分类: ERROR / PREFERENCE / NONE

### A6 - Compaction 引擎

```python
# extensions/context/compaction.py
class CompactionEngine:
    def should_compact(current_tokens, budget) -> bool: ...
    async def compact(conversation_history, keep_recent=5) -> dict: ...
    async def verify_compaction(original, compacted) -> dict: ...
```

触发条件: token 使用达 85%。压缩目标: 原始 10-20%。

### A7 - Observer 引擎

```python
# extensions/observer/engine.py
class ObserverEngine:
    async def lightweight_observe(task_trace, reflection_output) -> dict: ...
    async def deep_analyze(trigger='daily') -> dict: ...

# extensions/observer/scheduler.py
class ObserverScheduler:
    async def check_and_run() -> dict | None: ...
    def get_next_run_time() -> str: ...
```

轻量模式: 每个任务后 (gemini-flash)。深度模式: 每日 02:00 或紧急触发 (opus)。

## 模块间接口约定

模块间通过文件通信，以下是关键数据流：

```
A5 (反思) → reflection_output dict → A4 (信号检测)
A3 (指标) → events.jsonl → A4 (模式检测)
A4 (信号) → signals/active.jsonl → A7 (Observer 读取)
A7 (Observer) → deep_reports/*.md → [B5 Architect 读取，不在你的范围]
A3 (指标) → daily metrics → A2 (auto_rollback_check)
```

各模块读写各自的文件，不直接 import 其他 A 类模块（集成在 B 类中完成）。

## 提交规范

```
feat(A2): implement RollbackManager with backup/restore

- Add backup() with metadata.json generation
- Add rollback() with file restoration
- Add auto_rollback_check() with threshold comparison
- All tests passing
```

格式: `feat(A{n}): 简要描述`

## Git 状态

仓库已初始化，所有 feature branch 已从 `main` 创建。你直接在对应的 feature branch 上工作，完成后提 PR 到 `main`。

```
main (初始提交已完成)
├── feat/A1-seed-rules
├── feat/A2-rollback
├── feat/A3-metrics
├── feat/A4-signals
├── feat/A5-reflection
├── feat/A6-compaction
└── feat/A7-observer
```

## 已知文档冲突说明

以下是规格书间的已知不一致，以此文档为准：

| 冲突点 | mvp-module-plan 说法 | A1 规格书说法 | 决定 |
|--------|---------------------|--------------|------|
| 文件数量 | 12 个 | 15 个 | **15 个**（7 个 experience 文件，非 4 个） |
| YAML front matter | 未明确 | 不使用 | **不使用** |

## 注意事项

1. **不要修改** `core/`, `pyproject.toml`, 或其他任务的文件
2. **不要依赖** 真实 LLM API — 测试中全部 mock
3. **workspace/ 目录** 是运行时数据目录，代码中用相对路径引用
4. **workspace 路径** 通过 `core/workspace.py` 的 `WorkspaceManager` 获取，但你可以直接用 `pathlib.Path` 配合项目根目录
5. **JSONL 格式** 用于 append-only 日志（events, signals, reflections）
6. **YAML 格式** 用于每日汇总（daily metrics）
7. **Markdown 格式** 用于人可读的规则和报告
