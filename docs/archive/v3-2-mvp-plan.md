# MVP 实施方案与自我迭代蓝图

> **版本**: v3.1  
> **日期**: 2026-02-22  
> **前序文档**: [完整设计 v3.1](doc1_system_design_v3.1.md)  
> **本文档包含**:  
> 1. MVP 的定义、目标和范围  
> 2. 基于 NanoBot 的技术实施方案  
> 3. 分阶段实施路线  
> 4. MVP 完成后的自我迭代蓝图——如何让 Architect 接管系统进化  
> **配套文档**: [附录：规则模板与示例](doc3_appendix.md)

---

## 一、MVP 的核心定义

### 1.1 MVP 的目标（一句话）

**构建一个"从第一天就会自我观察、自我反思、并能提出自我改进建议"的最小闭环系统。**

这和传统 MVP 的区别：

```
传统 MVP 思路：
  "做一个功能够用的最小系统"
  → 功能丰富度是衡量标准
  → 后续迭代由人来推动

进化型 MVP 思路（我们的选择）：
  "做一个能自我改进的最小闭环"
  → 进化闭环的完整性是衡量标准
  → 后续迭代由系统参与推动（Architect 设计方案 + 人确认）
```

### 1.2 MVP 成功的衡量标准

```
标准 1：闭环完整性
  做了一个任务 → 产生了反思 → 反思被记住 → 
  下次同类任务的上下文中包含了之前的反思 → 
  第二次比第一次做得更好

  验证方法：连续给系统 5 个同类任务，观察第 5 次是否明显优于第 1 次

标准 2：Observer 有效性
  Observer 的观察笔记中包含"真正有价值的发现"
  而不只是"任务完成了"这种信息复述

  验证方法：人工阅读 20 条 Observer 笔记，
  判断其中有多少条包含可操作的洞察（目标 > 50%）

标准 3：Architect 可用性
  Architect 能基于 Observer 的发现，生成结构化的修改提案
  提案中包含：问题描述 + 修改方案 + 预期效果 + 影响范围评估

  验证方法：让 Architect 运行一周后查看其提案质量

标准 4：主动沟通能力
  系统能通过 Telegram 主动找用户沟通
  沟通内容有价值且频率合理

  验证方法：一周内收到的主动消息中，有用消息占比 > 70%

标准 5：规则活性
  运行一段时间后，有规则被 Observer 标记为
  "已验证有效" 或 "建议修改" 或 "可能冗余"

  验证方法：运行两周后检查是否有规则文件被标记过

标准 6：回滚可靠性
  任何修改都可以被回滚，且回滚后系统恢复正常

  验证方法：故意引入一个不好的规则修改，验证自动回滚是否生效
```

### 1.3 MVP 的范围界定

```
MVP 包含（闭环的最小完整集）：
  ✅ NanoBot 基座（Agent Loop + Message Bus + Telegram Channel）
  ✅ 规则解释器（读规则文件 → 组装 prompt → 调用 LLM）
  ✅ 基础规则集（~10 个规则文件，宪法级 + 经验级）
  ✅ 单 Agent 执行能力（能完成日常对话和简单任务）
  ✅ 文件系统记忆（MEMORY.md + 对话日志 + 每日摘要）
  ✅ 任务后轻量反思（Gemini，每次几百 token）
  ✅ 信号检测（基础版：失败、重复错误、用户纠正）
  ✅ Observer 智能体（观察 + 记录 + 信号提取）
  ✅ Architect 智能体（分析 + 设计提案 + 主动沟通）
  ✅ 爆炸半径控制 + 自动回滚
  ✅ 基础 Web Dashboard（系统状态 + 指标 + 日志查看）
  ✅ 双模型配置（Opus 主力 + Gemini 辅助）

MVP 不包含（留给 Architect 后续提案推动）：
  ❌ 多 Agent 并行协作
  ❌ 多智能体辩论
  ❌ AB 测试框架
  ❌ 行业知识库
  ❌ 自主任务发现（用户不在时主动找活干）
  ❌ 向量搜索记忆
  ❌ 难度路由
  ❌ 复杂的上下文压缩（Compaction）
  ❌ MCP 工具集成
  ❌ 多通道支持（先只做 Telegram）
```

---

## 二、基于 NanoBot 的技术方案

### 2.1 NanoBot 架构映射

NanoBot 的现有架构与我们需求的对应关系：

```
NanoBot 现有模块          我们的用途                         扩展方式
─────────────────────────────────────────────────────────────────
Agent Loop               核心推理循环                       覆写 ContextBuilder
  (agent/loop.py)        保留其 bounded iteration 设计      注入规则解释逻辑

ContextBuilder           上下文组装                         完全重写
  (agent/context.py)     原版太简单                         实现规则注入 + 记忆注入

MemoryStore              记忆系统                           大幅扩展
  (agent/memory.py)      原版只有基本的记忆整合              添加分类记忆 + 信号记录

SubagentManager          Observer / Architect 运行           扩展
  (agent/subagent.py)    原版支持子 Agent 并行执行           用于运行独立的观察和设计

MessageBus               消息路由                           保留
  (bus/bus.py)           核心路由功能已经够用                添加内部消息类型

SessionManager           会话管理                           保留 + 扩展
  (session/manager.py)   添加对话轨迹的结构化存储

ChannelManager           通信通道                           保留
  (channels/manager.py)  先用 Telegram，后续扩展

Provider Registry        LLM 提供者                         配置
  (providers/registry.py) 添加 Anthropic + Google 配置       无需改代码
```

### 2.2 我们在 NanoBot 上新增的模块

```
新增模块                   文件位置                  职责
────────────────────────────────────────────────────────────────
规则解释器                 extensions/rules/         读取规则文件
  RuleInterpreter          interpreter.py           解析规则
                           loader.py                注入到 prompt

信号系统                   extensions/signals/       信号提取
  SignalDetector           detector.py              信号存储
  SignalStore              store.py                 信号处理

Observer 引擎              extensions/observer/      轻量观察
  ObserverEngine           engine.py                深度分析
  ObserverScheduler        scheduler.py             触发管理

Architect 引擎             extensions/architect/     提案生成
  ArchitectEngine          engine.py                沟通管理
  ProposalManager          proposals.py             修改执行
  ModificationExecutor     executor.py              回滚管理
  RollbackManager          rollback.py

Web Dashboard              extensions/dashboard/     状态展示
  DashboardServer          server.py                API 接口
  StaticAssets             templates/               页面模板

进化日志                   extensions/evolution/     完整记录
  EvolutionLogger          logger.py                指标追踪
  MetricsTracker           metrics.py
```

### 2.3 系统目录结构

```
evo-agent/                          # 项目根目录
├── nanobot/                        # NanoBot 源码（git submodule 或 pip 安装）
│
├── extensions/                     # 我们的扩展代码
│   ├── __init__.py
│   ├── rules/
│   │   ├── interpreter.py          # 规则解释器
│   │   └── loader.py               # 规则文件加载器
│   ├── signals/
│   │   ├── detector.py             # 信号检测器
│   │   └── store.py                # 信号存储
│   ├── observer/
│   │   ├── engine.py               # Observer 核心逻辑
│   │   └── scheduler.py            # Observer 触发调度
│   ├── architect/
│   │   ├── engine.py               # Architect 核心逻辑
│   │   ├── proposals.py            # 提案管理
│   │   ├── executor.py             # 修改执行器
│   │   └── rollback.py             # 回滚管理器
│   ├── memory/
│   │   ├── enhanced_memory.py      # 增强记忆系统
│   │   └── reflection.py           # 反思引擎
│   ├── context/
│   │   └── enhanced_context.py     # 增强上下文构建器
│   ├── dashboard/
│   │   ├── server.py               # Dashboard Web 服务
│   │   ├── api.py                  # API 接口
│   │   └── templates/              # HTML 模板
│   └── evolution/
│       ├── logger.py               # 进化日志
│       └── metrics.py              # 指标追踪
│
├── workspace/                      # 系统运行时数据（类比 ~/.nanobot/）
│   ├── rules/                      # 规则文件
│   │   ├── constitution/           # 宪法级规则
│   │   │   ├── safety_boundaries.md
│   │   │   ├── approval_levels.md
│   │   │   ├── meta_rules.md
│   │   │   ├── core_orchestration.md
│   │   │   └── identity.md
│   │   └── experience/             # 经验级规则
│   │       ├── task_strategies.md
│   │       ├── reflection_templates.md
│   │       ├── memory_strategies.md
│   │       ├── interaction_patterns.md
│   │       └── user_preferences.md
│   │
│   ├── memory/                     # 记忆存储
│   │   ├── MEMORY.md               # 核心记忆
│   │   ├── conversations/          # 对话记录
│   │   ├── observations/           # Observer 记录
│   │   └── signals/                # 信号记录
│   │
│   ├── architect/                  # Architect 工作区
│   │   ├── proposals/              # 修改提案
│   │   ├── modifications/          # 修改记录
│   │   ├── architect_memory.md     # Architect 长期记忆
│   │   └── big_picture/            # 系统设计文档（Big Picture）
│   │       ├── design_v3.1.md      # 当前完整设计
│   │       └── mvp_plan.md         # MVP 计划
│   │
│   ├── backups/                    # 备份目录
│   ├── metrics/                    # 指标数据
│   └── logs/                       # 系统日志
│
├── config/
│   ├── nanobot_config.json         # NanoBot 配置（LLM、通道等）
│   └── evo_config.yaml             # 进化系统配置
│
├── docs/                           # 文档（人类可读的项目文档）
│   ├── design/                     # 设计文档
│   └── decisions/                  # 决策日志
│
├── tests/                          # 测试
│   ├── test_rules.py
│   ├── test_observer.py
│   ├── test_architect.py
│   └── test_rollback.py
│
├── requirements.txt
└── README.md
```

### 2.4 配置文件设计

**NanoBot 配置**（`config/nanobot_config.json`）：

```json
{
  "providers": {
    "anthropic": {
      "apiKey": "sk-ant-xxx"
    },
    "google": {
      "apiKey": "xxx"
    }
  },
  "agents": {
    "defaults": {
      "model": "anthropic/claude-opus-4-5"
    },
    "observer": {
      "model": "google/gemini-2.5-flash"
    },
    "architect": {
      "model": "anthropic/claude-opus-4-5"
    },
    "reflection": {
      "model": "google/gemini-2.5-flash"
    }
  },
  "channels": {
    "telegram": {
      "enabled": true,
      "token": "BOT_TOKEN",
      "allowFrom": ["MICHAEL_USER_ID"]
    }
  }
}
```

**进化系统配置**（`config/evo_config.yaml`）：

```yaml
# 进化系统配置
evolution:
  # 当前进化策略（由 Architect 管理，初始为 cautious）
  current_strategy: cautious
  
  # Observer 配置
  observer:
    lightweight_after_every_task: true
    deep_analysis_triggers:
      consecutive_failures: 3
      daily_minimum: 1              # 每天至少一次深度分析
      signal_threshold: 5           # 累积 5 个 medium+ 信号触发
    
  # Architect 配置
  architect:
    daily_run_time: "02:00"         # 每天凌晨 2 点定时运行
    signal_triggered: true           # 信号触发也可唤醒
    max_daily_messages: 3            # 每天最多主动发 3 条消息
    do_not_disturb:                  # 勿扰时段
      start: "23:00"
      end: "08:00"
    
  # 回滚配置
  rollback:
    backup_before_every_modification: true
    backup_retention_days: 30
    auto_rollback_on_degradation: true
    degradation_threshold: 0.2       # 指标下降 20% 触发自动回滚

  # 爆炸半径配置
  blast_radius:
    level_0_max_files: 1
    level_1_max_files: 3
    validation_period_days:
      level_0: 3
      level_1: 5
      level_2: 7
```

---

## 三、分阶段实施路线

### Phase 0：环境搭建（1-2 天）

```
目标：NanoBot 跑起来，能通过 Telegram 对话

步骤：
  1. 在 Mac 上安装 NanoBot
  2. 配置 Anthropic + Google 的 API Key
  3. 创建 Telegram Bot，配置连接
  4. 验证：能通过 Telegram 和 NanoBot 对话
  5. 通读 NanoBot 源码（~4000 行），标记扩展点

交付物：
  · 可运行的 NanoBot 实例
  · 对 NanoBot 架构的理解笔记
  · 确认的扩展点列表
```

### Phase 1：规则系统 + 增强上下文（3-5 天）

```
目标：系统行为由规则文件驱动，而非硬编码

步骤：
  1. 创建 workspace/rules/ 目录结构
  2. 编写初始规则文件集（参见附录中的模板）
  3. 实现 RuleInterpreter：
     - 读取规则文件
     - 根据当前任务类型选择相关规则
     - 将规则注入到 system prompt
  4. 覆写 NanoBot 的 ContextBuilder：
     - 在原有基础上增加规则注入
     - 增加记忆注入位置
  5. 验证：修改规则文件后，系统行为发生相应变化
  
交付物：
  · 规则解释器模块
  · 初始规则文件集（~10 个文件）
  · 增强的上下文构建器
  
验证方法：
  · 修改 task_strategies.md 中的一条策略
  · 观察系统在相关任务上的行为是否改变
  · 如果改变了 → 规则系统生效
```

### Phase 2：记忆系统 + 反思引擎（3-5 天）

```
目标：系统能记住过去的经验，并在任务后自动反思

步骤：
  1. 扩展 NanoBot 的 MemoryStore：
     - 对话记录自动保存到 conversations/ 目录
     - 实现 MEMORY.md 的结构化读写
     - 实现每日摘要生成（Gemini）
  2. 实现反思引擎：
     - 每次任务后调用 Gemini 做轻量反思
     - 反思结果写入 MEMORY.md 的对应区域
  3. 将记忆注入上下文：
     - 每次 Agent 推理前，从 MEMORY.md 中提取相关条目
     - 加入近期对话摘要
  4. 验证：第二次做同类任务时，上下文中包含第一次的反思
  
交付物：
  · 增强记忆系统
  · 反思引擎
  · 每日摘要生成器
  
验证方法：
  · 第一次让系统写一份报告，故意给负面反馈
  · 第二次让系统写类似报告
  · 检查第二次的上下文中是否包含第一次的教训
  · 检查第二次的输出是否避免了第一次的问题
```

### Phase 3：信号系统 + Observer（3-5 天）

```
目标：Observer 持续运行，从系统活动中提取信号

步骤：
  1. 实现信号检测器：
     - 扫描任务执行轨迹，提取错误信号
     - 检测用户纠正行为（用户说"不对"/"重新来"等）
     - 检测重复模式（同类错误出现 3+ 次）
  2. 实现信号存储：
     - active.jsonl 存储未处理信号
     - archive.jsonl 存储已处理信号
     - 信号去重逻辑
  3. 实现 Observer 引擎：
     - 轻量模式：每次任务后运行（Gemini）
     - 深度模式：信号触发时运行（Opus）
     - 输出格式化的观察日志和报告
  4. 实现 Observer 调度器：
     - 管理触发条件和频率
     - 确保每天至少一次深度分析
  5. 验证：Observer 能在运行日志中产生有价值的观察笔记

交付物：
  · 信号检测器和存储
  · Observer 引擎和调度器
  · 观察日志目录结构
  
验证方法：
  · 连续使用系统 3 天
  · 检查 observations/ 目录中的日志
  · 人工评估日志中是否有可操作的发现
```

### Phase 4：Architect + 审批 + 回滚（4-6 天）

```
目标：Architect 能基于 Observer 数据提出修改提案，并通过 Telegram 沟通

步骤：
  1. 实现 Architect 引擎：
     - 读取 Observer 的观察报告和信号
     - 读取系统 Big Picture 文档
     - 分析问题并生成修改提案
  2. 实现提案管理：
     - 提案的创建、存储、状态追踪
     - 提案模板（问题 + 方案 + 影响 + 审批级别）
  3. 实现主动沟通：
     - 通过 NanoBot 的 Telegram 通道发送提案
     - 解析用户回复（同意/拒绝/稍后/需要讨论）
  4. 实现修改执行器：
     - 执行已批准的修改（修改规则文件等）
     - 修改前自动备份
  5. 实现回滚管理器：
     - 备份存储和管理
     - 一键回滚到指定备份点
     - 自动回滚（当指标恶化时）
  6. 验证：Architect 能生成有价值的提案并通过 Telegram 发送

交付物：
  · Architect 引擎
  · 提案管理系统
  · 回滚管理器
  · Telegram 主动沟通能力
  
验证方法：
  · 运行系统一周，制造一些问题（如故意给不好的反馈）
  · 检查 Architect 是否发现问题并生成提案
  · 测试提案审批流程（通过 Telegram 确认）
  · 测试回滚（故意引入坏修改，验证回滚）
```

### Phase 5：Web Dashboard（2-3 天）

```
目标：Web 界面展示系统状态和关键数据

步骤：
  1. 实现 Dashboard Web 服务（Flask / FastAPI）
  2. 首页：系统健康度 + 进化策略 + 今日概览
  3. Observer 页：观察日志列表 + 信号列表
  4. Architect 页：提案列表 + 修改历史
  5. 规则页：规则文件浏览
  6. 指标页：趋势图表（任务成功率、token 消耗等）
  7. 配置基本认证（防止未授权访问）

交付物：
  · 可访问的 Web Dashboard
  · 5 个核心页面
  
技术选择：
  · 后端：FastAPI（轻量，Python 原生）
  · 前端：简单 HTML + Tailwind CSS + Chart.js
  · 不做 SPA，服务端渲染就够
  · 数据直接读取 workspace/ 下的文件
```

### Phase 总览

```
Phase 0 (1-2天)   ──── NanoBot 环境搭建
Phase 1 (3-5天)   ──── 规则系统 + 增强上下文
Phase 2 (3-5天)   ──── 记忆系统 + 反思引擎
Phase 3 (3-5天)   ──── 信号系统 + Observer
Phase 4 (4-6天)   ──── Architect + 审批 + 回滚
Phase 5 (2-3天)   ──── Web Dashboard
────────────────────────────────────────────
总计：16-26 天（约 3-5 周）

注意：各 Phase 之间有一定并行可能，
但建议按顺序执行，因为后面的 Phase 依赖前面的基础设施。
```

---

## 四、MVP 完成后的自我迭代蓝图

这一节定义了 MVP 完成后，系统如何"由 Architect 驱动进化"。这是本项目最核心的差异化价值。

### 4.1 自我迭代的整体框架

```
MVP 交付后，系统进入"协作进化"模式：
  
  Architect 是进化的推动者
  Michael 是进化的审批者和方向指引者
  Observer 是进化的数据来源
  系统运行本身是进化的实验场

  ┌─────────────────────────────────────────────────────────┐
  │                                                         │
  │  系统运行                                                │
  │    ↓                                                    │
  │  Observer 持续观察                                       │
  │    ↓                                                    │
  │  信号累积到阈值                                          │
  │    ↓                                                    │
  │  Architect 被唤醒                                        │
  │    ↓                                                    │
  │  Architect 分析问题 + 参照 Big Picture                    │
  │    ↓                                                    │
  │  Architect 生成修改提案                                   │
  │    ├── Level 0/1 → 自主执行 + 记录                       │
  │    └── Level 2/3 → 发送给 Michael 审批                   │
  │    ↓                                                    │
  │  修改执行                                                │
  │    ↓                                                    │
  │  进入验证期                                              │
  │    ↓                                                    │
  │  Observer 收集效果数据                                    │
  │    ↓                                                    │
  │  Architect 评估效果                                       │
  │    ├── 有效 → 标记为已验证，更新 Big Picture               │
  │    ├── 无效 → 回滚 + 记录教训                             │
  │    └── 不确定 → 延长验证 或 设计更精确的测试               │
  │    ↓                                                    │
  │  进化经验沉淀到 Architect 记忆                             │
  │    ↓                                                    │
  │  回到系统运行，等待下一轮信号                              │
  │                                                         │
  └─────────────────────────────────────────────────────────┘
```

### 4.2 Architect 的进化路线图

Architect 推动系统进化的优先级和大致路线：

```
第一阶段：规则调优期（MVP 后 1-4 周）
  
  Architect 主要做什么：
  · 观察初始规则集的实际效果
  · 发现哪些规则有效、哪些无效、哪些缺失
  · 提出规则的微调和补充
  · 学习 Michael 的偏好，更新 user_preferences.md
  · 逐步从 cautious 策略切换到 balanced 策略

  预期进化成果：
  · 规则文件从 ~10 个增长到 ~15 个
  · 经验级规则中积累了 20+ 条经过验证的策略
  · 系统对 Michael 的偏好有了基本理解

  Architect 运行频率：每天 1 次定时 + 信号触发
  审批频率：大部分为 Level 0/1（自主），偶尔 Level 2

───────────────────────────────────────────────────

第二阶段：能力扩展期（MVP 后 4-8 周）

  Architect 主要做什么：
  · 基于积累的数据，提出系统能力扩展的提案
  · 可能的提案方向（取决于实际数据，以下仅为示例）：
    - "建议引入向量搜索记忆——因为当前关键词搜索
       在过去两周有 12 次检索失败"
    - "建议引入难度路由——因为简单问题使用 Opus 
       浪费了 40% 的 token 预算"
    - "建议新增一条反思维度——因为当前反思经常
       忽略对用户情绪的分析"
  · 提案都会包含：数据支撑 + 具体方案 + 影响评估
  · 这些提案由 Michael 审批后执行

  预期进化成果：
  · 2-3 个重要的能力升级
  · 系统性能指标有明显提升
  · 积累了足够的进化经验，知道什么样的改动有效

  Architect 运行频率：每天 1 次 + 信号触发
  审批频率：出现更多 Level 2 提案

───────────────────────────────────────────────────

第三阶段：自主进化期（MVP 后 8-16 周）

  Architect 主要做什么：
  · 基于前两阶段积累的进化经验，
    Architect 对"什么样的修改有效"有了更好的判断
  · 逐步获得更多 Level 0/1 权限
    （如果前两阶段的自主修改效果好，
     Michael 可以把更多类型的修改降级为 Level 0/1）
  · 开始提出更大胆的系统改进方案
  · 可能提出修改硬核层代码的建议（Level 3）

  可能的提案方向：
  · "建议引入多 Agent 协作——Observer 数据表明，
     30% 的任务如果有独立的 Researcher Agent 
     效率可以提升 2 倍"
  · "建议引入自主任务发现——过去一个月 Michael 
     有 15 次在早上给出的任务，系统前一天晚上
     就可以预判并准备"
  · "建议重构上下文引擎——当前的 token 使用效率
     只有 62%，有明确的优化空间"

  预期进化成果：
  · 系统从"能用的助手"进化为"真正有用的同事"
  · Architect 的提案质量稳定，大部分被采纳
  · 形成了成熟的进化流程和评估方法

───────────────────────────────────────────────────

第四阶段：专精深化期（MVP 后 16+ 周）

  Architect 主要做什么：
  · 提出领域专精方案（如 AI 教育领域的专用工具和知识库）
  · 提出更新 Big Picture 设计文档的建议
  · 评估是否需要架构层面的调整
  · 可能提出引入更多 Agent 角色
  · 探索跨系统经验共享（文化基因概念）

  这个阶段的特征：
  · 系统已经比 MVP 复杂得多，但每一步复杂度
    都有 Observer 数据支撑、Architect 提案论证、
    Michael 审批确认
  · 不是"一开始就设计复杂"，而是"从简单开始，
    在实践中发现哪些复杂度是真正需要的"
```

### 4.3 Architect 如何更新 Big Picture

这是一个关键机制——确保系统的局部进化不偏离整体方向：

```
Big Picture 文档存放在 workspace/architect/big_picture/ 中

Architect 更新 Big Picture 的场景：

场景 1：重要修改完成后
  Architect 执行了一个 Level 2 的修改
  → 修改成功验证后
  → Architect 更新 Big Picture 中的相关章节
  → 更新内容标记为 [Architect 更新, 日期]
  → 通知 Michael："Big Picture 已更新，以反映最近的修改"

场景 2：发现 Big Picture 与实际不符
  Observer 发现系统实际运行方式与 Big Picture 描述不一致
  → Architect 分析原因
  → 如果是实际更好 → 建议更新 Big Picture 以反映实际
  → 如果是实际偏离了 → 建议修正系统回到 Big Picture 方向
  → 两种情况都需要 Level 2 审批

场景 3：定期审视
  每月一次，Architect 完整审视 Big Picture
  → 标记哪些部分已经实现
  → 标记哪些部分需要修改
  → 标记哪些部分的优先级需要调整
  → 生成 Big Picture 审视报告给 Michael
```

### 4.4 进化策略的动态调整

```
系统启动时：cautious
  ↓ （运行 7 天 + Observer 未发现严重问题）
自动切换：balanced
  ↓ （连续 14 天无显著改进）
Architect 建议切换：growth
  ↓ （某次修改导致指标下降）
自动切换：repair
  ↓ （问题修复 + 指标恢复）
自动切换：balanced

策略切换的判断依据（Observer 收集）：
  · 任务成功率趋势
  · 用户满意度趋势（通过反馈和纠正频率间接衡量）
  · 进化提案的采纳率
  · 修改后的回滚率
  · token 消耗效率趋势
```

### 4.5 防止进化失控的安全网

```
安全网 1：爆炸半径限制
  每次修改的影响范围有硬上限
  超过限制 → 必须拆分为多次小修改

安全网 2：自动回滚
  修改后指标恶化 → 自动回滚
  不需要等人介入

安全网 3：审批机制
  重要修改需要 Michael 确认
  Architect 不确定时默认需要审批（保守原则）

安全网 4：进化速率限制
  每天最多执行 N 次自主修改（防止连续快速修改导致不稳定）
  两次修改之间有最短间隔（给验证期留足时间）

安全网 5：不可修改的底线
  安全边界规则永远不能被 Architect 自主修改
  审批分级规则的修改永远需要 Michael 确认
  Architect 自身的触发频率限制不能被自己修改

安全网 6：人类随时干预
  Michael 可以随时：
  · 否决任何修改并回滚
  · 暂停 Architect（进入纯 Observer 模式）
  · 手动切换进化策略
  · 修改任何规则文件
```

---

## 五、关键设计决策的思考过程

记录重要设计决策的"为什么"，为 Architect 未来的决策提供参考。

### 5.1 为什么选 Observer + Architect 双智能体，而非单一进化者

```
考虑过的方案：
  A. 单一 Evolver 智能体（同时观察和修改）
  B. Observer + Architect 分离
  C. Observer + Architect + 独立的 Executor

选择 B 的理由：
  · 观察需要客观性——如果同一个智能体既观察又修改，
    它可能倾向于把自己的修改效果评估得更好（确认偏误）
  · 频率差异大——Observer 每个任务都运行（轻量），
    Architect 每天或信号触发才运行（重量），混在一起浪费资源
  · 成本优化——Observer 用便宜的 Gemini，Architect 用 Opus
  · 可审计性——Observer 的原始观察不受 Architect 的修改倾向影响

没选 C 的理由：
  · 三个角色在 MVP 阶段太复杂
  · Architect 自己执行修改（在安全边界内）比再拆一个角色简单
```

### 5.2 为什么不用 Claude Code 作为基座

```
考虑过的方案：
  A. 直接在 Claude Code + CLAUDE.md 上构建
  B. 基于 OpenClaw 构建
  C. 基于 NanoBot 构建
  D. 完全从零构建

选择 C 的理由：
  · Claude Code 是交互式命令行工具，不适合 24 小时后台运行
  · Claude Code 没有内置的消息通道（Telegram 等），
    不支持"AI 主动发消息给人"
  · OpenClaw 太重（43 万行），难以理解和修改
  · 从零构建太慢，NanoBot 提供了很好的起点
  · NanoBot 4000 行代码可以在几小时内通读理解
  · NanoBot 已有多通道支持、多 LLM 提供者、记忆基础设施
  
  未来可以：
  · 让 Agent 调用 Claude Code 来执行编码任务
  · 参考 Claude Code 的 CLAUDE.md 模式设计规则文件
  · 参考 Claude Code 的 Plan Mode 设计任务规划
```

### 5.3 为什么审批边界不按"能不能改"划线

```
旧思路（v3.0）：
  把系统分为"可修改区"和"不可修改区"
  · 硬核层：不可修改
  · 规则层：可修改
  · 安全规则：不可修改

新思路（v3.1）：
  一切都可以被提议修改，区别在于审批流程
  · 普通经验规则 → Level 0（自主修改）
  · 重要经验规则 → Level 1（先做后报）
  · 宪法规则 → Level 2（先报后做）
  · 架构和硬核层 → Level 3（深入讨论）

为什么这样更好：
  · 不会错过有价值的改进——如果硬核层代码有 bug，
    Architect 应该能指出来并建议修改
  · 安全通过审批流程保障，而非通过"禁止触碰"保障
  · 随着信任积累，审批级别可以动态调整
    （某类修改被证明安全后，可以降级审批要求）
  · 这更像真实团队的运作方式——
    新人的 PR 需要 review，老手的小修改可以 self-merge
```

### 5.4 为什么 MVP 就要包含 Observer 和 Architect

```
反方观点：
  "MVP 应该尽量简单，Observer 和 Architect 可以后面再加"

我们的判断：
  · 如果 MVP 不包含 Observer，就没有人在收集数据
    → 后续加 Observer 时没有历史数据可用
    → 失去了最宝贵的早期数据（系统刚启动时的问题最多）
  
  · 如果 MVP 不包含 Architect，后续迭代完全靠人
    → 人就是瓶颈
    → 和"没有 Architect 的普通 Agent"相比没有差异化

  · Observer 和 Architect 在 MVP 中可以很简单：
    Observer = "每次任务后写一条日志 + 每天一次总结"
    Architect = "每天看一下 Observer 的总结，有想法就写个提案"
    这不是多复杂的东西，但有了它，系统从第一天就在积累进化数据

  · 这是本项目的核心信念：
    "一个会自我改进的简单系统 > 一个不会改进的复杂系统"
    如果 MVP 不包含自我改进能力，就违背了这个信念
```

---

## 六、风险与缓解

| 风险 | 严重性 | 缓解策略 |
|------|--------|---------|
| Architect 提案质量差 | 中 | MVP 阶段全部 Level 2 审批；积累信任后逐步放权 |
| Observer 信息过载 | 低 | 信号去重 + 频率控制 + 只在阈值时触发 Architect |
| 进化方向偏离 | 中 | Big Picture 作为锚点 + Architect 定期审视 + 人类抽查 |
| API 成本过高 | 中 | Observer 用 Gemini（便宜）；Architect 每天只跑一次 |
| NanoBot 上游破坏性更新 | 低 | 锁定版本 + 定期评估是否更新 |
| 规则文件互相矛盾 | 中 | Architect 在修改前检查一致性 + Observer 监测矛盾行为 |
| 回滚不完整 | 高 | 每次修改前完整快照 + 定期测试回滚功能 |

---

> **下一份文档**: [附录：规则模板与示例](doc3_appendix.md)
