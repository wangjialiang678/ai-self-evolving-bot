# AI 自进化系统 — 当前状态与下一步任务

> **文档用途**：为接手实施的 Agent 提供完整上下文。读完本文档即可理解系统现状，无需再读其他文档。
> **更新日期**：2026-02-24

---

## 一、系统是什么

一个**规则驱动的自进化 AI Agent**，核心设计是：

```
用户消息
  → 规则注入 prompt（RulesInterpreter）
  → 上下文组装（ContextEngine）
  → LLM 推理（Opus 主力 / Qwen 轻量）
  → 回复用户
  → 后处理链：反思 → 信号检测 → Observer 记录 → 指标追踪

每日定时：
  → Observer 深度分析（02:00）
  → Architect 读取观察 → 生成改进提案（03:00）
  → Telegram 推送提案 → 用户审批
  → 执行修改 → 自动回滚兜底
```

系统当前**正在运行**（PID 32510，已运行约 19 小时），Bootstrap 完成，今日已处理 7 次任务，Architect 已自动执行 2 个 Level 0 提案。

---

## 二、代码结构

```
AI自进化系统/
├── core/                    # B 类核心模块（主会话开发）
│   ├── llm_client.py        # LLM 抽象层（Anthropic + Qwen via NVIDIA）
│   ├── rules.py             # 规则解释器：读取/解析/相关性过滤
│   ├── context.py           # 上下文引擎：token 预算管理 + prompt 组装
│   ├── memory.py            # 记忆系统：对话历史 + 分类记忆检索
│   ├── agent_loop.py        # 主循环：调用链路 + 后处理链
│   ├── architect.py         # Architect 引擎：分析 → 提案 → 执行
│   ├── bootstrap.py         # 首次引导流程（3 阶段）
│   ├── telegram.py          # Telegram 出站通知（勿扰时段 + 审批 keyboard）
│   └── config.py            # EvoConfig 加载器
│
├── extensions/              # A 类扩展模块（Codex 并行开发）
│   ├── signals/
│   │   ├── detector.py      # 信号检测（8 种信号类型）
│   │   └── store.py         # 信号存储（active.jsonl / archive.jsonl）
│   ├── memory/
│   │   └── reflection.py    # 反思引擎（轻量 LLM 提取教训）
│   ├── context/
│   │   └── compaction.py    # 对话压缩（token > 85% 触发）
│   ├── observer/
│   │   ├── engine.py        # Observer（轻量/深度双模式）
│   │   └── scheduler.py     # 触发调度
│   └── evolution/
│       ├── metrics.py       # 指标追踪（events.jsonl + daily YAML）
│       └── rollback.py      # 回滚系统（备份 + 自动回滚检查）
│
├── workspace/               # 运行时数据（Agent 读写）
│   ├── rules/
│   │   ├── constitution/    # 宪法规则（5 个文件，始终注入）
│   │   └── experience/      # 经验规则（7 个文件，按相关性注入）
│   ├── memory/              # 分类记忆（projects/ + user/）
│   ├── observations/        # Observer 输出（light_logs/ + deep_reports/）
│   ├── signals/             # 信号队列（active.jsonl + archive.jsonl）
│   ├── architect/           # Architect 提案（proposals/prop_*.json）
│   ├── metrics/             # 指标数据
│   ├── backups/             # 修改备份
│   ├── telegram_queue/      # 待发送消息队列（pending.jsonl）
│   ├── USER.md              # 用户背景（Bootstrap 采集）
│   ├── SOUL.md              # Agent 人格定义
│   └── HEARTBEAT.md         # 心跳任务列表
│
├── config/
│   ├── evo_config.yaml      # 系统配置（模型、调度时间、频率限制等）
│   └── defaults/            # 默认最佳实践（3 个 MD 文件）
│
├── main.py                  # 入口：初始化所有模块 + run_scheduler
└── tests/                   # 测试（pytest，LLM 全 mock）
```

---

## 三、已完成内容（全部 A + B 模块）

### A 类（Codex 完成，已合并）

| 模块 | 状态 | 关键文件 |
|------|------|---------|
| A1 种子规则（15 个 MD 文件） | ✅ | `workspace/rules/` + `config/defaults/` |
| A2 回滚系统 | ✅ | `extensions/evolution/rollback.py` |
| A3 指标追踪 | ✅ | `extensions/evolution/metrics.py` |
| A4 信号系统 | ✅ | `extensions/signals/` |
| A5 反思引擎 | ✅ | `extensions/memory/reflection.py` |
| A6 Compaction | ✅ | `extensions/context/compaction.py` |
| A7 Observer | ✅ | `extensions/observer/` |

### B 类（主会话完成）

| 模块 | 状态 |
|------|------|
| B1 LLM 网关 | ✅ |
| B2 规则 + 上下文引擎 | ✅ |
| B3 记忆系统 | ✅ |
| B4 Telegram 通道 + 审批流 | ✅（出站） |
| B5 Architect + AgentLoop | ✅ |
| B6 Bootstrap | ✅ |
| B7 main.py + 调度器 | ✅ |

---

## 四、MVP 缺口（需要实现）

以下 3 项是 MVP 计划内、但尚未实现的内容。

---

### 缺口 1：双向 Telegram（当前只有出站）

**现状**：`core/telegram.py` 只能发通知（提案审批、每日简报、紧急告警），Bot 无法接收用户消息。用户只能在系统启动时通过 Bootstrap 流程与 Agent 交互，之后无法主动发消息给 Bot。

**目标**：Bot 能接收用户消息并转给 AgentLoop 处理，形成真正的双向对话。

**实现方案**：从 nanobot 借鉴 channel 架构，复制以下模块并适配（nanobot 已安装在 `.venv` 可参考源码）：

```
新建 core/channels/ 目录
├── bus.py        # 合并自 nanobot/bus/queue.py + events.py（124 行）
│                 # 改动：loguru → stdlib logging
├── base.py       # 来自 nanobot/channels/base.py（127 行）
│                 # 改动：loguru → stdlib logging，import 路径
├── telegram.py   # 来自 nanobot/channels/telegram.py（421 行）
│                 # 改动：loguru → logging，TelegramConfig → 简单 dataclass
└── manager.py    # 来自 nanobot/channels/manager.py（227 行）
                  # 改动：loguru → logging，nanobot.config.schema → 我们的 config
```

适配要点：
- `loguru` 全局替换为 `import logging; logger = logging.getLogger(__name__)`
- `TelegramConfig` 替换为简单 dataclass（字段：`token`, `allow_from`, `proxy`）
- 在 `main.py` 加 bus 桥接循环：`bus.consume_inbound() → agent_loop.process_message() → bus.publish_outbound()`
- 现有的 `core/telegram.py`（出站通知）**保留不动**，改为往 bus 写 `OutboundMessage`

nanobot 源码位置：`.venv/lib/python3.14/site-packages/nanobot/channels/`

---

### 缺口 2：Heartbeat/Cron 调度（当前是 while 轮询）

**现状**：`main.py` 里的 `run_scheduler()` 是一个 while 轮询，每分钟检查时间，手动触发 Observer 和 Architect。没有标准 cron 能力，无法配置任意定时任务，健壮性差。

**目标**：替换为 nanobot 的 HeartbeatService + CronService，支持 cron 表达式配置，并保持 HEARTBEAT.md 驱动机制。

**实现方案**：

```
新建（或加入 core/channels/）
├── heartbeat.py  # 来自 nanobot/heartbeat/service.py（130 行）
│                 # 改动：loguru → logging
└── cron.py       # 来自 nanobot/cron/service.py + cron/types.py（352+80 行）
                  # 改动：loguru → logging
                  # 新增依赖：croniter
```

pyproject.toml 新增依赖：
```toml
"croniter>=2.0",
```

集成方式：
- `HeartbeatService(workspace, on_heartbeat=agent_loop.process_message, interval_s=1800)`
- 替换 `main.py` 里的 `run_scheduler` 函数

---

### 缺口 3：Multi-Agent Council（审议会）

**现状**：代码里没有任何审议实现。

**设计定位**（来自 v3-2-system-design.md §6.3）：
- **不是自动流程**，是用户可选的辅助工具
- 用户主动请求时，或 Architect 在提案中建议时触发
- 不需要独立 Agent 进程——用不同 system prompt 前缀让同一个 LLM 依次扮演 4 种视角的"委员"

**4 种视角**：

| 委员 | 关注点 |
|------|--------|
| 安全委员 | 风险、回滚、边界 |
| 效率委员 | 成本、token、速度 |
| 用户体验委员 | 用户感受、交互质量 |
| 长期委员 | 架构演进、技术债 |

**输出格式**（追加到提案 JSON 的 `council_review` 字段）：
```json
{
  "council_review": {
    "triggered_by": "user_request | architect_suggestion",
    "reviews": [
      {"role": "安全委员", "concern": "...", "architect_response": "..."},
      ...
    ],
    "conclusion": "通过 | 修改后通过 | 否决"
  }
}
```

**建议实现位置**：`core/architect.py` 里增加 `run_council_review(proposal)` 方法，或新建 `core/council.py`。

---

## 五、完整设计中 MVP 之外的内容（供参考，暂不实现）

以下内容在完整设计文档（`docs/design/v3-2-system-design.md`）中有完整设计，**期望由系统运行后 Architect 自主提案推动**，或等需求明确后人工规划：

| 模块 | 设计标记 | 描述 |
|------|---------|------|
| 研究模块 | 🟡 重要 | 自主上网搜索填补知识缺口 |
| 好奇心引擎 + 意图池 | 🟡 重要 | 主动发现"我不知道但应该知道"的事 |
| Human-as-Executor | 🟡 重要 | AI 规划、驱动用户执行物理任务 |
| 用户模型（四层） | 🟡 重要 | 表面偏好→工作模式→品味→隐性知识 |
| 进化策略自适应 | 🟡 重要 | cautious/balanced/bold 自动切换 |
| 向量搜索记忆 | 🔵 方案 | 当关键词搜索不够用时 |
| 难度路由 | 🔵 方案 | 简单问题 Sonnet，复杂任务 Opus |
| CODER Agent | 🔵 方案 | 专门执行代码任务的子 Agent |
| Web Dashboard | 🔵 方案 | 系统状态可视化 |
| 多通道支持 | 🔵 方案 | 飞书/Slack/Discord（channel 架构建好后扩展成本低）|
| 多 Agent 专业分工 | 🔵 方案 | 同一系统扮演项目经理/研究员/开发主管 |
| 经验继承/文化基因 | 🔵 方案 | 把验证有效的规则打包供其他 Agent 实例继承 |

---

## 六、关键设计决策（背景）

### 为什么没有用 nanobot 作为底层框架

原始设计（v3-2-mvp-plan.md）计划用 nanobot 作为基座，但实际实现时放弃了，原因：

1. ContextBuilder 需要完全重写（规则注入、token 预算）
2. AgentLoop 执行模型不同（nanobot 是通用 ReAct；我们是固定后处理链）
3. Telegram 方向相反（nanobot 是接收消息；我们最初只需要出站通知）
4. nanobot 有 26 个依赖，项目只需要 4 个

**当前结论**：nanobot 的 channels/heartbeat/cron 模块值得借鉴，但以**复制代码**方式引入（而非安装 nanobot-ai 包），这样：
- 不引入额外依赖
- 代码完全自主可控（系统需要自我修改能力）
- 可自由适配接口

### Telegram 双向通信的架构

```
接收消息：nanobot TelegramChannel（long polling）→ MessageBus → AgentLoop
发送通知：core/telegram.py TelegramChannel → MessageBus outbound（或直接发送）
```

两个 Telegram 适配器可以共存：一个负责对话，一个负责审批通知。或者合并为一个双向适配器（整合现有通知模板到新的 channel 中）。

---

## 七、实施优先级建议

```
P0（先做，MVP 闭环依赖）：
  1. 双向 Telegram - 复制 nanobot channels 代码并适配
  2. Heartbeat/Cron - 复制 nanobot heartbeat/cron 代码并适配

P1（完善 MVP）：
  3. Multi-Agent Council - 在 core/architect.py 增加 run_council_review()

P2（MVP 后，按需推动）：
  4. 等 Architect 从运行数据中提案，或用户有明确需求时再规划
```

---

## 八、参考文档

| 文档 | 路径 | 用途 |
|------|------|------|
| 完整系统设计 | `docs/design/v3-2-system-design.md` | 所有模块的完整设计 |
| MVP 模块计划 | `docs/dev/mvp-module-plan.md` | A/B 类模块划分 |
| Codex 开发指南 | `codex/CODEX-GUIDE.md` | A 类模块规格索引 |
| nanobot 架构调研 | `.claude/memory-bank/research/nanobot-architecture-20260223.md` | nanobot 源码分析 |
| nanobot 源码 | `.venv/lib/python3.14/site-packages/nanobot/` | 直接参考复制 |
