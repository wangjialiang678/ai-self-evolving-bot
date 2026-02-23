# Self-Evolving Agent System: Architecture Design v2.1

> **Version**: v2.1  
> **Updated**: 2026-02-17  
> **Changes from v2.0**: 原则 6 拆分为"对世界保持好奇"和"人可以是执行者"两条独立原则  
> **Changes from v1.0**: Integrates EvoMaster reverse inspirations + independent critique feedback  
> **Companion docs**: [Implementation Roadmap](doc2_roadmap_v2.md) | [Research Topics](doc3_research_topics.md)

---

## 一、设计哲学（v2.0 更新）

### 1.1 核心洞察（不变）

当前 LLM 具备强大的单次推理能力，但有三个结构性缺陷：无状态、注意力受限、无元认知。本系统在 LLM 之上构建一层认知架构，使系统具备持续记忆、自我反思、主动学习、策略进化能力。

### 1.2 核心设计原则（v2.1：9 条）

**原则 1：上下文即灵魂（Context is the Soul）**
> 来源：Manus。系统核心工作是精心构造模型做决策时看到的信息。

**原则 2：拥抱模型的不完美（Design for Imperfection）**
> 来源：Manus。LLM 会遗忘、漂移、僵化、幻觉。系统设计补偿机制而非假设完美。

**原则 3：减法优于加法（Subtraction Over Addition）**
> 来源：Manus。系统复杂度最小化。每个 token 必须为下一个决策服务。

**原则 4：文件系统是认知的虚拟内存（Disk as Cognitive Virtual Memory）**
> 来源：OpenClaw。上下文窗口是"内存"，文件系统是"硬盘"，需要分页机制。

**原则 5：失败是学习的素材（Errors as Learning Material）**
> 来源：Manus + 进化引擎设计。错误轨迹被保留作为自我反思和策略改进的输入。

**原则 6：对世界保持好奇（Proactive Curiosity）** 🔄 v2.1 拆分重定义
> AI 在处理信息时主动发现值得探索的问题，自主调研和思考，不依赖人类指令驱动。好奇心是认知进化的内生动力——一个好的研究者读论文时会自然产生"这个方法用在另一个场景会怎样？"的想法，不是因为有人让它去想，而是信息本身激发了探索欲。当人类需求不清晰时，也会主动提问澄清。

**原则 7：人可以是执行者（Human-as-Executor）** 🆕 v2.1
> AI 不只是被动接受人类指令的工具。在任务需要时，AI 可以规划、决策、并驱动人类去执行 AI 无法完成的部分——物理行动、人际沟通、受限资源访问。人成为任务流中的执行节点，AI 负责协调全局。这是角色关系的根本重构：从"人思考、AI 执行"走向"AI 思考规划、人执行 AI 做不到的部分"。来源：rentahuman.ai 理念 + 对 AI 驱动管理趋势的洞察。

**原则 8：代码即交互语言（Code as Interaction Language）** 🆕
> 来源：EvoMaster / X-Master。不是所有能力都需要先注册为 Tool。Agent 可以直接生成代码与环境交互，反思引擎将高复用代码自动提炼为正式 Skill。这打通了"临时代码→验证有效→注册为工具"的自动进化路径。

**原则 9：尽早被现实检验（Validate with Reality, Not Just Logic）** 🆕
> 来源：EvoMaster 的 benchmark 验证实践。每个架构决策都应有可测量的验证标准。不是"我们觉得这个设计好"，而是"我们用数据证明这个设计好"。

---

## 二、系统全局架构（v2.1）

### 2.1 三层架构概览（结构不变，组件有更新）

```
┌─────────────────────────────────────────────────────────────┐
│                    第三层：进化层                              │
│                  (Evolution Layer)                            │
│                                                             │
│  ┌──────────┐  ┌──────────┐  ┌────────────┐  ┌──────────┐  │
│  │ 反思引擎  │  │ 进化引擎 │  │ 用户模型   │  │好奇心引擎│  │
│  │Reflection │  │Evolution │  │ User Model │  │Curiosity │  │
│  │ Engine    │  │ Engine   │  │            │  │ Engine   │  │
│  └──────────┘  └──────────┘  └────────────┘  └──────────┘  │
│                                                             │
│  职责：自我反思、策略进化、用户偏好学习、自主探索与提问        │
├─────────────────────────────────────────────────────────────┤
│                    第二层：认知层                              │
│                  (Cognition Layer)                            │
│                                                             │
│  ┌──────────┐  ┌──────────┐  ┌──────────────────────────┐  │
│  │上下文引擎 │  │ 记忆系统 │  │  研究模块                │  │
│  │ Context   │  │ Memory   │  │  Research Module         │  │
│  │ Engine    │  │ System   │  │                          │  │
│  └──────────┘  └──────────┘  └──────────────────────────┘  │
│                                                             │
│  职责：注意力管理、信息持久化与检索、自主信息获取              │
├─────────────────────────────────────────────────────────────┤
│                    第一层：执行层                              │
│                  (Execution Layer)                            │
│                                                             │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌────────────┐ │
│  │ 事件总线  │  │Agent编排器│  │工具注册表 │  │难度路由器  │ │
│  │ Event Bus │  │Orchestrat│  │ToolRegist│  │Difficulty  │ │
│  │           │  │          │  │          │  │ Router  🆕 │ │
│  └──────────┘  └──────────┘  └──────────┘  └────────────┘ │
│                                                             │
│  职责：事件路由、任务分解与执行、工具调用、难度评估            │
└─────────────────────────────────────────────────────────────┘
         │                              │
    ┌────┴─────┐                  ┌─────┴──────┐
    │ 大语言模型 │                  │ 外部世界    │
    │ LLM Pool  │                  │ (Web/API/  │
    │           │                  │  Human)    │
    └──────────┘                  └────────────┘
```

### 2.2 v2.1 架构变更摘要

| 变更 | 来源 | 说明 |
|------|------|------|
| 原则 6 拆分为好奇心 + Human-as-Executor | v2.1 | 好奇心面向世界而非面向人；人可以是执行节点 |
| 新增 CODER Agent 角色 | EvoMaster 启发 #1 | 代码即交互语言，自动代码→技能提炼 |
| 新增难度路由器 | EvoMaster 启发 #2 | 按任务难度选择串行/并行/Scattered-and-Stacked |
| 记忆系统升级为双向迁移 | EvoMaster 启发 #3 | Compaction 增加 recall 操作 + 认知层级转化 |
| 新增冷启动策略 | 独立建议 #8 | 种子记忆 + 引导式用户建模 + 保守期 |
| Compaction 增加质量保障 | 独立建议 #10 | 关键信息锁定 + 验证 + 归档 |
| 好奇心引擎重新定位 | v2.1 原则 6 重定义 | 从"问用户"转向"AI自主探索 + 意图池" |
| 新增 Human-as-Executor 模式 | v2.1 原则 7 | AI 驱动人执行，人成为任务流中的执行节点 |
| 偏好系统分快慢通道 | Michael 反馈 #11 | 显式偏好即时生效，推断偏好通知确认 |
| 新增验证基准体系 | EvoMaster 启发 #5 | 每个组件有可测量的验证标准 |
| 架构预留垂直领域适配层 | EvoMaster 启发 #7 | TODO: 通用架构之上可接入领域专用工具集 |

---

## 三、核心组件设计（v2.1：11 个组件）

### 3.1 事件总线（Event Bus）

与 v1.0 相同，不再重复。核心：所有输入统一为事件，支持可中断交互。

### 3.2 Agent 编排器（Agent Orchestrator）

**v2.0 变更：新增 CODER 角色 + 难度路由**

**Agent 类型定义（v2.1）**：

```
AgentRole:
  PLANNER       // 接收原始任务，分解为子任务列表
  EXECUTOR      // 执行具体子任务，调用工具
  CODER         // 🆕 直接生成 Python 代码与环境交互
  RESEARCHER    // 自主搜索和整理信息
  REFLECTOR     // 分析任务执行结果，生成反思
  EVOLVER       // 基于反思结果，生成策略改进
  USER_MODELER  // 分析用户行为，更新用户模型
  CRITIC        // 对其他 Agent 的输出进行质量检查
```

**CODER Agent 详细设计**：

```
CODER Agent:
  触发条件：
    - 现有工具不能满足需求
    - 任务涉及数据处理、计算、文件操作等可编程任务
    - PLANNER 评估为"写代码比调工具更直接"
    
  工作流程：
    1. 接收任务描述和上下文
    2. 生成 Python 代码
    3. 在沙盒环境中执行
    4. 如果成功 → 返回结果
    5. 如果失败 → 读取错误信息，修正代码重试（最多 3 次）
    6. 如果仍然失败 → 退回给 PLANNER 重新规划
    
  与进化引擎的集成：
    反思引擎分析执行轨迹时，如果发现某段代码被多次复用（≥3 次）：
    → 自动提炼为正式 Tool 并注册到工具注册表
    → 这是"代码→技能"的自动进化路径
```

**难度路由器（Difficulty Router）** 🆕：

```
任务进入 → 难度评估器（快速模型快速评估）
  ├── 简单任务（单步、明确、有现成技能）
  │   → 单 Agent 串行执行
  ├── 中等任务（多步、需要协调）
  │   → PLANNER + 2-3 个 Agent 协作
  └── 困难任务（开放性、高不确定性、需要创造性）
      → Scattered-and-Stacked 流程
         Step 1: 3-5 个 Agent 并行生成方案
         Step 2: CRITIC 诊断每个方案缺陷
         Step 3: 综合所有方案重新生成改进版
         Step 4: CRITIC 从中选出最优解

难度评估维度：
  - 任务步骤数估计
  - 是否有匹配的已有技能
  - 任务描述的开放程度
  - 历史类似任务的成功率

进化特性：
  难度评估器的阈值和分支策略本身是可进化的参数。
  记录每次路径选择和最终任务质量，逐步学习
  "什么样的任务该走哪条路"。
```

### 3.3 工具注册表（Tool Registry）

与 v1.0 基本相同，新增：

```
特殊工具：code_execute
  name: "code_execute"
  description: "在沙盒环境中执行任意 Python 代码"
  parameters:
    code: string        # Python 代码
    timeout: number     # 超时时间（秒）
    dependencies: list  # 需要的 pip 包
  category: "code"
  riskLevel: MEDIUM     # 沙盒内执行，风险可控
```

### 3.4 上下文引擎（Context Engine）

**v2.0 变更：增加双向迁移 + 认知层级转化**

核心设计不变（token 预算、KV-cache 友好、Compaction），新增以下机制：

**双向迁移（Recall 操作）** 🆕：

```
上下文组装时的 recall 逻辑：

在 assembleContext() 的"步骤 5：注入相关记忆"中：
  1. 对语义记忆做混合搜索（已有逻辑）
  2. 🆕 对检索结果中相关性 > 0.9 的条目，给予 2x 价值评分加权
     → 确保高度相关的长期知识优先进入上下文
  3. 🆕 如果某条语义记忆的原始情节记忆仍然可追溯，
     且当前任务需要细节，可以"召回"原始轨迹的关键片段
```

**Compaction 升级（认知层级转化 + 质量保障）** 🆕：

```
Compaction 流程（v2.0 升级为 7 步）：

步骤 1：Pre-Compaction Memory Flush（不变）
步骤 2：关键信息锁定 🆕
  用一个独立 LLM 调用识别当前上下文中的"关键信息点"：
  - 用户明确提出的需求和约束
  - 已确认的决策和承诺
  - 关键错误诊断
  这些信息在后续压缩中必须被保留。

步骤 3：生成压缩摘要（升级为认知层级转化）🆕
  输入：要被压缩的历史对话
  输出要求（不再是简单摘要，而是认知提炼）：
    1. 事实提取：这段对话产生了哪些可复用的事实？
    2. 规律提炼：这段经历揭示了什么通用规律？
    3. 策略建议：未来遇到类似情况，应该采用什么策略？
    4. 用户信号：用户表达了什么偏好或价值判断？
  
步骤 4：压缩验证 🆕
  用另一个 LLM 调用对比原始内容和摘要：
  - 被锁定的关键信息是否都保留了？
  - 是否有明显的信息丢失？
  如果检测到高风险丢失 → 回滚并重新 Compact

步骤 5：替换历史内容（不变）
步骤 6：原始内容归档（不变，但强调不删除）
步骤 7：索引更新（不变）
```

### 3.5 记忆系统（Memory System）

四种记忆类型不变，新增以下设计：

**冷启动策略** 🆕：

```
种子记忆（Seed Memory）：
  系统首次启动时，预载以下内容到 MEMORY.md：
  - 通用常识规则（如"竞品分析先查官方渠道"）
  - 领域基础知识（根据配置的目标领域）
  - 系统使用指南摘要

种子技能（Seed Skills）：
  预置 5-10 个通用技能到 skills/builtin/：
  - web_research.yaml        # 网页调研
  - document_writing.yaml    # 文档写作
  - data_analysis.yaml       # 数据分析
  - code_development.yaml    # 代码开发
  - competitive_analysis.yaml # 竞品分析
  
  种子技能 status: seed（区别于 learned 和 active）
  在系统学习到对应的更优策略后，种子技能可以被替换

保守期策略：
  前 20 次任务为保守期：
  - 进化引擎只做规则沉淀，不做基因突变
  - 反思引擎对每个任务都做完整反思（即使任务很小）
  - 好奇心引擎活跃（频繁向用户了解偏好）
  - 默认使用更多的"执行前确认"模式
```

**记忆衰减设计（预留接口）** 🆕：

```
# 在记忆条目中增加以下字段（为遗忘机制预留）
memory_entry:
  content: string
  created_at: datetime
  last_accessed_at: datetime    # 🆕 最后被检索使用的时间
  access_count: int             # 🆕 被检索使用的次数
  freshness_score: float        # 🆕 新鲜度评分（0-1）

# V2 阶段实现具体的衰减算法（见调研议题）
# 当前只做数据收集，不做自动遗忘
```

### 3.6 研究模块（Research Module）

与 v1.0 相同，不再重复。

### 3.7 反思引擎（Reflection Engine）

与 v1.0 基本相同（五维反思 + 四种触发条件），新增：

**竞争性评估接口预留** 🆕：

```
ReflectionEngine:
  reflect(taskReport: TaskReport) → ReflectionReport         # 原有
  comparativeReflect(                                         # 🆕 预留
    reportA: TaskReport,   # 原策略执行结果
    reportB: TaskReport,   # 突变策略执行结果
    criticModel: string    # 使用独立模型做评估
  ) → ComparativeReport

# 竞争性评估的具体实现见调研议题
# 当前版本使用简单的单策略反思
```

### 3.8 进化引擎（Evolution Engine）

三种机制不变（规则沉淀、基因突变、用户适应），新增：

**突变应用到工作流本身** 🆕：

```
可进化的工作流参数：
  - 难度路由器的阈值
  - Scattered-and-Stacked 的并行度（3/5/8）
  - 早停条件（方案一致性高时跳过 Rewriter）
  - 迭代深化触发条件（Selector 置信度低时触发第二轮）
  
这些参数和普通技能一样，经过 A/B 测试验证后保留或回滚。
```

### 3.9 用户模型（User Model）

四层模型不变，新增偏好分速机制：

**显式偏好 vs 推断偏好** 🆕：

```
偏好类型分类：

显式偏好（Explicit Preferences）：
  来源：用户直接声明（"我喜欢中文回答"、"不要太啰嗦"）
  生效速度：即时生效
  置信度：初始 0.9
  无需确认

推断偏好（Inferred Preferences）：
  来源：行为分析（选择、修改、追问等隐式信号）
  生效速度：积累到置信度 > 0.6 后生效
  通知机制：以非阻断方式通知用户
    "我注意到你似乎偏好 X 风格，已自动应用。如果不对请告诉我。"
  用户可以：
    - 确认 → 升级为显式偏好（置信度 → 0.95）
    - 否定 → 立即移除
    - 忽略 → 保持推断状态，继续观察
```

### 3.10 好奇心引擎（Curiosity Engine）

**v2.1 重大重新定位** 🔄

原则 6 重新定义：好奇心面向世界，而非面向人。AI 自主产生对事物的好奇心，主动探索和调研。

```
好奇心引擎 v2.1 设计：

核心理念（原则 6：对世界保持好奇）：
  好奇心不是"向人提问的机制"，而是"AI 的认知内驱力"。
  AI 在处理任务和信息的过程中，自然发现值得深入了解的问题，
  然后自主去探索——搜索、阅读、分析、思考。
  
  向人提问只是好奇心的一个副产品，而且仅限于：
  - 人类需求表述不清时，主动澄清
  - AI 确实无法自己获取的信息（如内部数据、主观判断）

意图池（Intention Pool）：
  统一管理 AI 的好奇心意图和人类的任务意图：
  
  IntentionPool:
    add(intention: Intention) → void
    getPending() → Intention[]
    resolve(intentionId, result) → void
  
  Intention:
    id: string
    source: AI_CURIOSITY | USER_TASK | SCHEDULED
    description: string          # 想了解/探索什么
    relevance_to_current: float  # 与当前任务的相关性
    priority: HIGH | MEDIUM | LOW
    can_self_resolve: boolean    # AI 能否自己去调研解决
    status: PENDING | IN_PROGRESS | RESOLVED | DEFERRED

AI 自主探索流程：
  1. AI 在处理信息时产生好奇心意图
     例："这篇论文提到的 X 方法，在教育场景下会有什么效果？"
  2. 评估 can_self_resolve
  3. 如果 can_self_resolve == true 且与当前任务相关：
     → 直接交给 RESEARCHER Agent 执行
  4. 如果 can_self_resolve == true 但与当前任务无关：
     → 放入意图池，后台空闲时执行
  5. 如果 can_self_resolve == false：
     → 放入意图池，等待合适时机向用户请求

探索结果呈现（V2 实现，V1 设计接口）：
  每日（可配置）生成一份"探索摘要"：
  - 今日发现了什么有价值的信息
  - 哪些探索解决了之前的知识缺口
  - 还有哪些意图未解决，需要用户输入
  
  呈现方式：非阻断通知（如 Telegram 消息）
  格式：简洁摘要 + "需要你关注的 N 个问题"
```

好奇心触发不再限定为三种条件，而是更自然的认知过程：AI 在阅读、分析、执行任何信息时，都可能产生"我想了解更多"的意图。

### 3.11 Human-as-Executor 模式 🆕 v2.1

**原则 7 的架构落地**：AI 可以驱动人类去执行。

```
Human-as-Executor 设计：

核心概念：
  在传统 Agent 系统中，人是决策者，AI 是执行者。
  Human-as-Executor 反转了这个关系的一部分：
  AI 做规划和决策，人去执行 AI 无法完成的行动。

适用场景：
  - 物理行动："请去会议室拍一下白板上的内容发给我"
  - 人际沟通："请和 X 确认一下这个需求的优先级"
  - 受限访问："请登录内部系统查一下 Y 数据"
  - 主观判断："这两个设计方案，你更喜欢哪个？"

实现方式：
  在 Agent 编排器中，人被视为一种特殊的"执行节点"：
  
  HumanExecutionRequest:
    task_description: string    # 清晰的任务描述
    context: string             # 为什么需要人做这件事
    expected_output: string     # 期望人返回什么
    deadline: datetime | null   # 截止时间
    fallback: string | null     # 人不响应时的替代方案
    priority: HIGH | MEDIUM | LOW
    
  关键设计决策：
  - AI 给人的指令必须清晰、具体、可执行
  - 不能假设人会立即响应——必须有 fallback
  - 不能频繁驱动人——每个任务最多 1-2 个人类执行请求
  - 人有权拒绝或修改 AI 的指令
  - AI 驱动人执行的记录进入情节记忆，
    反思引擎分析"哪些请求人执行了、哪些被拒绝了、效果如何"

与好奇心引擎的区别：
  好奇心引擎：AI 想了解某件事 → 自己去探索或问人
  Human-as-Executor：AI 需要某个行动被执行 → 分配给人去做
  
  好奇心是认知层面的（我想知道什么）
  Human-as-Executor 是执行层面的（我需要谁做什么）
```

---

## 四、系统状态与持久化设计（v2.1）

### 4.1 文件系统布局

```
workspace/
├── config/
│   ├── system.yaml              # 系统配置
│   ├── models.yaml              # 模型配置
│   └── tools.yaml               # 工具注册配置
│
├── memory/
│   ├── MEMORY.md                # 语义记忆
│   ├── daily/
│   │   ├── 2026-02-17.md        # 今日情节记忆
│   │   └── ...
│   ├── index/
│   │   ├── vectors.db           # 向量索引
│   │   └── fts.db               # 全文索引
│   ├── compaction/
│   │   ├── summaries.jsonl      # Compaction 摘要历史
│   │   └── archives/            # 🆕 原始内容归档（不删除）
│   └── seeds/                   # 🆕 种子记忆
│       └── seed_memory.md       # 预置的通用知识
│
├── skills/
│   ├── builtin/                 # 内置技能
│   ├── seeds/                   # 🆕 种子技能（可被学习到的更优技能替代）
│   ├── learned/                 # 从经验中学到的技能
│   └── mutations/               # 正在测试的突变技能
│
├── user_model/
│   ├── profile.yaml             # 用户模型
│   ├── explicit_prefs.yaml      # 🆕 显式偏好（即时生效）
│   ├── inferred_prefs.yaml      # 🆕 推断偏好（需确认）
│   ├── decisions.jsonl          # 用户决策历史
│   └── feedback.jsonl           # 用户反馈历史
│
├── intentions/                  # 🆕 意图池
│   ├── active.jsonl             # 活跃意图
│   ├── resolved.jsonl           # 已解决意图
│   └── exploration_log.jsonl    # 探索日志
│
├── reflections/
│   ├── reflection_001.yaml
│   └── ...
│
├── evolution/
│   ├── strategy_log.jsonl       # 策略变更日志
│   ├── mutation_tests.jsonl     # 突变测试结果
│   └── rules/
│       ├── active_rules.yaml
│       └── deprecated_rules.yaml
│
├── validation/                  # 🆕 验证数据
│   ├── benchmarks/              # 验证基准定义
│   ├── test_results/            # 测试结果
│   └── metrics.jsonl            # 系统指标时序数据
│
└── sessions/
    ├── session_001.jsonl
    └── ...
```

### 4.2 关键数据结构

TaskReport 和 StrategyDirective 与 v1.0 相同。

新增 Intention 数据结构：

```yaml
# intentions/active.jsonl 中的一条记录
intention_id: "int_20260217_001"
source: AI_CURIOSITY
description: "了解 Flutter FunASR 集成的最新最佳实践"
context: "用户正在开发 VoiceScribe，可能对此有用"
relevance_to_current: 0.7
priority: MEDIUM
can_self_resolve: true
status: PENDING
created_at: "2026-02-17T10:00:00Z"
resolved_at: null
resolution: null
```

---

## 五、多模型路由策略

与 v1.0 基本相同。补充说明：

```yaml
model_routing:
  # 架构支持接入任意模型供应商
  # 只需在 models.yaml 中配置不同 provider 的 API
  # 不同角色可以使用不同供应商的模型
  # 例如：
  #   CODER → Claude Sonnet (代码能力强)
  #   REFLECTOR → Claude Opus (深度推理)
  #   RESEARCHER → 任意带搜索能力的模型
  #   格式转换等简单任务 → 更便宜的模型
```

---

## 六、安全与控制

与 v1.0 相同。四级人类监督、进化安全边界、透明度保证。

---

## 七、验证基准体系 🆕

每个核心组件都有可测量的验证标准：

```yaml
validation_benchmarks:

  memory_effectiveness:
    method: "同类任务跑 20 次：前 10 次无记忆，后 10 次有记忆"
    metric: "后 10 次平均质量提升幅度"
    target: "> 15% 质量提升"

  reflection_value:
    method: "对比'有反思注入上下文' vs '无反思注入'"
    metric: "同类任务成功率差异"
    target: "> 10% 成功率提升"

  evolution_rate:
    method: "追踪第 1/10/30/50 次执行同类任务的表现"
    metric: "学习曲线斜率"
    target: "明显的性能递增趋势"

  compaction_quality:
    method: "Compaction 后让 LLM 基于摘要回答关于原始内容的问题"
    metric: "关键信息保留率"
    target: "> 90% 关键信息保留"

  user_model_accuracy:
    method: "系统预测用户偏好 vs 用户实际选择"
    metric: "一致性分数"
    target: "> 75% 一致性（30 天后）"

  context_engine_efficiency:
    method: "对比固定模板 vs 动态组装的上下文"
    metric: "任务质量差异 + KV-cache 命中率"
    target: "质量持平或更好，KV-cache > 60%"

  difficulty_router_accuracy:
    method: "记录路由决策 vs 最终任务复杂度"
    metric: "路由正确率（简单任务未走重路，复杂任务未走轻路）"
    target: "> 80% 路由正确"
```

---

## 八、垂直领域适配层（架构预留）🆕

```
通用认知架构（三层设计）
        │
  ┌─────┼─────┐
  ▼     ▼     ▼
教育领域  创业领域  音乐领域
适配层    适配层    适配层

每个适配层包含：
  - domain_tools/    # 该领域的专用工具集（MCP 接入）
  - domain_seeds/    # 该领域的种子知识
  - domain_skills/   # 该领域的初始策略规则
  - domain_persona/  # 该领域的用户画像模板

当前版本：仅预留目录结构和接口定义
后续版本：先在教育领域做深做透，验证后扩展
```

---

## 九、系统生命周期（v2.0 更新）

```
阶段 0：冷启动期（Day 0）🆕
  特征：
    - 加载种子记忆和种子技能
    - 引导式用户建模（主动问 5-10 个关键问题）
    - 所有操作默认"执行前确认"
    - 与裸 LLM 的关键区别：有种子知识 + 上下文工程

阶段 1：初生期（Day 1-3）
  特征：同 v1.0，但增加——
    - 显式偏好即时生效
    - 保守期策略（不做基因突变）
    
阶段 2：学习期（Day 3-30）
  特征：同 v1.0

阶段 3：稳定期（Day 30+）
  特征：同 v1.0，新增——
    - 好奇心引擎从"频繁提问"转向"自主探索"
    - 每日探索摘要呈现给用户

阶段 4：进化期
  特征：同 v1.0

阶段 5：专精期
  特征：同 v1.0
```

---

## 十、设计风格约束 🆕

```
语言与生态：Python 3.11+
  - 全部使用 Python 生态
  - 优先使用标准库
  - 外部依赖最小化

代码风格：极简优雅
  - 每个模块 < 300 行代码
  - 函数 < 30 行
  - 类 < 10 个方法
  - 命名即文档（减少注释需求）
  - 使用 dataclasses / pydantic 定义数据结构
  - 使用 typing 做类型标注

设计优先级：
  1. 正确性 > 优雅性 > 性能
  2. 可读性 > 可扩展性 > 可复用性
  3. 先跑通 > 再优化 > 最后抽象

暂不考虑：
  - 性能优化（先不做缓存、连接池等）
  - 并发（用 asyncio 但不追求高并发）
  - 鲁棒性（先不做重试、熔断等）
  - 分布式（单机运行）
```

---

> **下一份文档**：[Implementation Roadmap](doc2_roadmap_v2.md) — MVP 分层、迭代计划、测试框架、AI 自迭代闭环
