# 自进化智能体系统：顶层架构设计

> **文档版本**: v1.0  
> **文档性质**: 系统架构设计文档（概览层）  
> **目标读者**: AI 实现者 / 系统架构师 / 技术决策者  
> **配套文档**: [核心子系统设计](doc2) | [动态工作流与行为模式](doc3)

---

## 一、设计哲学：为什么需要这个系统

### 1.1 核心洞察

当前大模型（LLM）具备强大的单次推理能力，但存在三个结构性缺陷：

- **无状态**：每次推理都从上下文窗口重新开始，不具备跨会话的持续学习能力
- **注意力受限**：即使上下文窗口达到 1M token，当信息密度下降时模型性能也会显著退化（context rot）
- **无元认知**：模型不知道自己不知道什么，不能监控自己的推理过程是否正常

本系统的设计目标是：在大模型**之上**构建一层认知架构，使整体系统具备大模型本身不具备的能力——持续记忆、自我反思、主动学习、策略进化，并最终形成**两层智能的正反馈循环**。

### 1.2 核心设计原则

本系统的设计遵循以下六条原则，每条原则都直接来源于 Manus、OpenClaw 等系统的实战验证：

**原则 1：上下文即灵魂（Context is the Soul）**

来源：Manus 联合创始人 Peak Ji 的核心理念。系统的核心工作不是"告诉模型做什么"，而是"精心构造模型在做决策时看到的信息"。模型的行为质量 = 上下文的信息质量 × 模型的推理能力。

**原则 2：拥抱模型的不完美（Design for Imperfection）**

来源：Manus 的 5 次重构经验。LLM 会遗忘、会漂移、会模式僵化、会幻觉。系统不是消除这些缺陷，而是将它们视为已知的认知特征，设计补偿机制。就像操作系统不假设硬件永不出错，而是设计了纠错和恢复机制。

**原则 3：减法优于加法（Subtraction Over Addition）**

来源：Manus 经过 5 次重构后得出的结论。系统复杂度应当最小化。每个进入上下文窗口的 token 都必须对下一个决策有帮助。不使用复杂的多层编排图，而是用最简洁的结构达到目的。

**原则 4：文件系统是认知的虚拟内存（Disk as Cognitive Virtual Memory）**

来源：OpenClaw 架构师 Laurent Bindschaedler 的洞察。LLM 的上下文窗口是"内存"（有限、快速），外部文件系统是"硬盘"（无限、需要检索）。系统需要一个"分页机制"来决定什么留在内存、什么存到硬盘、什么时候换入换出。

**原则 5：失败是学习的素材，不是需要隐藏的 Bug（Errors as Learning Material）**

来源：Manus 的错误保留策略 + 本设计中的"进化引擎"。系统不删除错误轨迹，而是保留它们作为自我反思和策略改进的输入。

**原则 6：系统应当对人类保持好奇（Proactive Curiosity）**

来源：rentahuman.ai 的理念 + 本设计的独创设计。系统不只是被动等待指令，它应当在发现自身知识或能力不足时，主动向人类提问、请求更多上下文、甚至雇佣人类去获取它无法获取的信息。

### 1.3 与现有系统的关系

本设计综合借鉴了以下系统的核心优势：

| 来源系统 | 借鉴的核心设计 |
|----------|---------------|
| **Manus** | Context Engineering 六大策略、事件驱动 Agent Loop、KV-cache 友好的工具设计、错误保留策略、Agent-as-a-Tool 模式 |
| **OpenClaw** | Gateway 事件架构、Compaction + Pre-flush 记忆机制、Markdown 作为认知虚拟内存、混合搜索（BM25 + 向量）、动态 Skill 注入、Lane Queue 串行安全 |
| **OWL (CAMEL-AI)** | 双角色协作机制、POMDP 自适应决策、MCP 工具协议集成 |
| **OpenManus** | PlanningFlow 多 Agent 分工模式、AskHuman 工具的初步人机交互 |
| **Reflexion** | 失败后生成反思笔记并重试的机制 |
| **Voyager (Minecraft Agent)** | 技能库的自动生成和复用、好奇心驱动的探索 |

---

## 二、系统全局架构

### 2.1 三层架构概览

系统整体分为三层，每层解决不同层面的问题：

```
┌─────────────────────────────────────────────────────────┐
│                    第三层：进化层                          │
│                  (Evolution Layer)                        │
│                                                         │
│  ┌──────────┐  ┌──────────┐  ┌──────────────────────┐   │
│  │ 反思引擎  │  │ 进化引擎 │  │  用户模型 & 好奇心    │   │
│  │Reflection │  │Evolution │  │  User Model &        │   │
│  │ Engine    │  │ Engine   │  │  Curiosity Engine    │   │
│  └──────────┘  └──────────┘  └──────────────────────┘   │
│                                                         │
│  职责：自我反思、策略进化、用户偏好学习、主动提问          │
├─────────────────────────────────────────────────────────┤
│                    第二层：认知层                          │
│                  (Cognition Layer)                        │
│                                                         │
│  ┌──────────┐  ┌──────────┐  ┌──────────────────────┐   │
│  │上下文引擎 │  │ 记忆系统 │  │  研究模块            │   │
│  │ Context   │  │ Memory   │  │  Research            │   │
│  │ Engine    │  │ System   │  │  Module              │   │
│  └──────────┘  └──────────┘  └──────────────────────┘   │
│                                                         │
│  职责：注意力管理、信息持久化与检索、自主信息获取          │
├─────────────────────────────────────────────────────────┤
│                    第一层：执行层                          │
│                  (Execution Layer)                        │
│                                                         │
│  ┌──────────┐  ┌──────────┐  ┌──────────────────────┐   │
│  │ 事件总线  │  │Agent编排器│  │  工具注册表           │   │
│  │ Event Bus │  │Orchestrat│  │  Tool Registry       │   │
│  └──────────┘  └──────────┘  └──────────────────────┘   │
│                                                         │
│  职责：事件路由、任务分解与执行、工具调用                  │
└─────────────────────────────────────────────────────────┘
         │                              │
    ┌────┴─────┐                  ┌─────┴──────┐
    │ 大语言模型 │                  │ 外部世界    │
    │ LLM Pool  │                  │ (Web/API/  │
    │           │                  │  Human)    │
    └──────────┘                  └────────────┘
```

### 2.2 各层职责详解

**第一层：执行层（Execution Layer）** —— "手和脚"

这一层负责具体行动。它接收事件、将任务分解为子步骤、调用工具、与外部世界交互。它不做战略决策，只做战术执行。

关键特征：
- 事件驱动（不是请求-响应），支持异步和中断
- 工具能力动态加载（不是一次性全部注入）
- 多 Agent 可并行或串行编排
- 错误不被隐藏，而是作为事件向上层传递

**第二层：认知层（Cognition Layer）** —— "大脑"

这一层负责"思考的质量"。它管理模型在每次推理时看到什么信息（上下文引擎）、记住什么信息（记忆系统）、以及在缺乏信息时如何主动获取（研究模块）。

关键特征：
- 上下文窗口被视为稀缺资源，每个 token 都要论证其价值
- 记忆分层（工作记忆 / 情节记忆 / 语义记忆 / 程序性记忆）
- 支持主动的网页搜索、开源项目研究、API 探索

**第三层：进化层（Evolution Layer）** —— "元认知"

这一层负责"让系统越来越好"。它观察系统的行为，从成功和失败中提取规律，生成新策略，学习用户的偏好和判断模式，并在需要时主动向人类提问。

关键特征：
- 每次任务完成后触发自我反思
- 成功策略被提炼为可复用的"技能"
- 用户的选择和反馈被记录为品味模型
- 系统可以产生"基因突变"——在成功率高于阈值时尝试创新

### 2.3 跨层数据流

三层之间通过定义明确的数据结构通信：

```
进化层                      认知层                     执行层
  │                          │                         │
  │ ◄── 任务报告 ──────────  │ ◄── 执行轨迹 ────────  │
  │     (TaskReport)         │     (ExecutionTrace)    │
  │                          │                         │
  │ ── 策略指令 ──────────► │ ── 上下文包 ─────────► │
  │    (StrategyDirective)   │    (ContextPackage)     │
  │                          │                         │
  │ ── 好奇心请求 ────────► │                         │
  │    (CuriosityQuery)      │ ── 研究结果 ─────────► │
  │                          │    (ResearchResult)     │
  │                          │                         │
  │ ◄── 用户信号 ──────────  │                         │
  │    (UserSignal)          │                         │
```

---

## 三、十大核心组件

以下是系统的 10 个核心组件。每个组件的详细设计见《核心子系统设计》文档，这里只给出职责定义和接口规范。

### 3.1 事件总线（Event Bus）

**职责**：系统的中央神经系统。所有输入（用户消息、定时触发、webhook、内部状态变化、其他 Agent 的输出）都以"事件"的形式进入事件总线，由它路由到正确的处理者。

**为什么需要它**：这是实现"可中断交互"的基础。传统 chatbot 是请求-响应模式，用户必须等 AI 完成才能输入。事件驱动架构允许用户的新消息作为新事件注入，Agent 在下一个迭代周期就能看到。

**核心接口**：

```
EventBus:
  emit(event: Event) → void                    // 发射事件
  subscribe(eventType, handler) → Subscription  // 订阅事件
  getEventStream(sessionId) → Event[]           // 获取某会话的事件流

Event:
  id: string              // 唯一标识
  type: EventType         // USER_MESSAGE | TOOL_RESULT | TIMER_TICK |
                          // AGENT_OUTPUT | SYSTEM_ALERT | HUMAN_RESPONSE |
                          // REFLECTION_TRIGGER | EVOLUTION_SIGNAL
  sessionId: string       // 所属会话
  timestamp: DateTime     // 时间戳
  payload: any            // 事件数据
  priority: number        // 优先级（用户消息 > 定时任务 > 后台进程）
  source: string          // 来源标识
```

### 3.2 Agent 编排器（Agent Orchestrator）

**职责**：管理多个 Agent 的生命周期和协作。负责任务分解、Agent 选择、执行监控、结果汇总。

**核心设计决策**：

- 采用 Manus 的 "Agent-as-a-Tool" 模式，而非复杂的编排图。一个 Agent 可以将另一个 Agent 作为工具调用，传入精简的上下文，接收结构化的输出。
- 默认串行执行（OpenClaw 的 Lane Queue 设计），仅对明确标记为安全的任务允许并行。
- 每个 Agent 有独立的上下文窗口，避免共享上下文导致的信息过载。

**Agent 类型定义**：

```
AgentRole:
  PLANNER       // 接收原始任务，分解为子任务列表
  EXECUTOR      // 执行具体子任务，调用工具
  RESEARCHER    // 自主搜索和整理信息
  REFLECTOR     // 分析任务执行结果，生成反思
  EVOLVER       // 基于反思结果，生成策略改进
  USER_MODELER  // 分析用户行为，更新用户模型
  CRITIC        // 对其他 Agent 的输出进行质量检查
```

### 3.3 工具注册表（Tool Registry）

**职责**：管理系统可用的所有工具（包括外部 API、浏览器、代码执行、文件操作等），并在每次 Agent 推理时只注入相关工具的描述。

**核心设计决策**：

- 采用 Manus 的 RAG 驱动动态注入策略。不是把所有工具描述塞进 prompt，而是根据当前任务类型，用向量搜索找到最相关的 3-7 个工具注入。
- 工具名称使用前缀分类（`browser_`, `shell_`, `file_`, `search_`, `human_`），便于 logit masking 和状态机控制。
- 支持 MCP 协议，可动态发现和接入新工具。

**核心接口**：

```
ToolRegistry:
  register(tool: ToolDefinition) → void
  getRelevantTools(taskContext: string, maxCount: number) → ToolDefinition[]
  execute(toolName: string, params: object) → ToolResult
  getToolsByPrefix(prefix: string) → ToolDefinition[]

ToolDefinition:
  name: string            // 如 "browser_navigate", "shell_exec"
  description: string     // 自然语言描述（用于 RAG 匹配）
  parameters: JSONSchema  // 参数定义
  category: string        // 分类前缀
  riskLevel: LOW | MEDIUM | HIGH  // 风险等级（影响是否需要人类确认）
  embedding: vector       // 描述文本的向量表示（用于 RAG 检索）
```

### 3.4 上下文引擎（Context Engine）

**职责**：系统最核心的组件。负责在每次 Agent 推理前，精心组装最优的上下文窗口内容。

**核心设计决策**：

- 维护一个 token 预算（如上下文窗口的 80%），每个进入上下文的信息块都有一个"价值评分"，按评分从高到低装载。
- 支持 Manus 风格的 KV-cache 友好设计：系统 prompt 稳定不变（命中缓存），动态信息只追加在末尾。
- 实现 OpenClaw 的 Compaction 机制：当 token 用量超过阈值，触发压缩——先 flush 重要信息到持久化记忆，再对旧内容做摘要替换。
- 包含"注意力锚点"机制（类似 Manus 的 todo.md 复述）：在上下文中重复插入当前任务目标，防止模型注意力漂移。

**核心接口**：

```
ContextEngine:
  assembleContext(
    sessionId: string,
    currentTask: TaskDescription,
    availableTokenBudget: number
  ) → ContextPackage

  triggerCompaction(sessionId: string) → void
  estimateTokens(content: string) → number
  getKVCacheHitRate() → float

ContextPackage:
  systemPrompt: string          // 稳定部分（高 KV-cache 命中率）
  taskAnchor: string            // 当前任务描述（注意力锚点）
  relevantMemories: Memory[]    // 从记忆系统检索的相关信息
  recentHistory: Message[]      // 近期对话历史
  toolDescriptions: string[]    // 当前可用工具描述
  errorTraces: string[]         // 近期错误轨迹（如果有）
  strategyNotes: string[]       // 来自进化层的策略指令
  userPreferences: string       // 用户偏好摘要
  totalTokens: number           // 总 token 数
```

### 3.5 记忆系统（Memory System）

**职责**：管理系统的所有持久化信息。按照认知科学的分类，维护四种记忆类型。

**四种记忆类型**：

| 类型 | 对应人类认知 | 存储内容 | 存储形式 | 生命周期 |
|------|------------|---------|---------|---------|
| 工作记忆 | 当前注意力焦点 | 当前任务的上下文、中间结果 | 上下文窗口内 | 当次推理 |
| 情节记忆 | 个人经历 | 每次任务的完整执行轨迹 | JSONL 文件（按日期） | 可配置保留期 |
| 语义记忆 | 知识和事实 | 从经历中提炼的规律、用户偏好、领域知识 | MEMORY.md + 向量索引 | 持久 |
| 程序性记忆 | 技能和习惯 | 验证过的成功策略、代码模板、工作流程 | skills/ 目录下的结构化文件 | 持久（可进化） |

**核心设计决策**：

- 采用 OpenClaw 的"Markdown 作为 source of truth"设计。所有记忆最终存储为人类可读的文件。这既方便审查，也方便用标准文本工具检索。
- 混合搜索：向量搜索（语义匹配）+ BM25 关键词搜索（精确匹配），用 union 合并结果。
- 情节记忆 → 语义记忆的自动提炼（Compaction 时触发）。
- 程序性记忆的自动生成（成功完成任务后，反思引擎可以将关键步骤提炼为可复用的 skill）。

### 3.6 研究模块（Research Module）

**职责**：当系统发现自身信息不足以完成任务时，主动进行信息获取——搜索网页、阅读文档、探索开源项目、调用 API。

**核心设计决策**：

- 遵循 Manus 的数据源优先级：可靠 API > 官方文档 > 网页搜索 > 论坛/社区
- 研究过程本身也受上下文引擎管理——研究结果会被压缩和提炼后才进入工作记忆，而非原封不动地塞入上下文。
- 支持"深度研究"模式：对复杂问题，可以启动多个并行的研究线程，每个线程探索不同方向，最后汇总。

**核心接口**：

```
ResearchModule:
  search(query: string, sources: SourceType[]) → SearchResult[]
  deepResearch(topic: string, depth: SHALLOW | MEDIUM | DEEP) → ResearchReport
  exploreRepository(repoUrl: string, question: string) → RepoAnalysis
  readDocument(url: string, extractionGoal: string) → ExtractedContent

SourceType: WEB | ACADEMIC | GITHUB | API_DOCS | NEWS
```

### 3.7 反思引擎（Reflection Engine）

**职责**：在每次任务完成后（无论成功还是失败），分析执行过程，生成结构化的反思报告。

**反思的五个维度**：

1. **结果评估**：任务是否成功？输出质量如何？用户满意吗？
2. **过程分析**：哪些步骤是高效的？哪些步骤浪费了时间或 token？
3. **错误诊断**：如果有错误，根本原因是什么？是信息不足、策略不当、工具选择错误、还是模型能力限制？
4. **策略提取**：从这次经验中，能提炼出什么通用策略？
5. **能力边界识别**：这次任务暴露了系统在哪些方面的不足？

**核心接口**：

```
ReflectionEngine:
  reflect(taskReport: TaskReport) → ReflectionReport
  
ReflectionReport:
  taskId: string
  outcome: SUCCESS | PARTIAL | FAILURE
  qualityScore: float              // 0-1
  processAnalysis:
    efficientSteps: string[]       // 高效步骤列表
    wastedEffort: string[]         // 浪费的步骤列表
    totalToolCalls: number
    totalTokensUsed: number
  errorDiagnosis:
    errors: ErrorRecord[]
    rootCauses: string[]
    category: INFO_GAP | STRATEGY_WRONG | TOOL_MISUSE | MODEL_LIMIT
  extractedStrategies:
    newRules: string[]             // 新发现的规则
    refinedRules: string[]         // 对已有规则的修正
    obsoleteRules: string[]        // 应该废弃的旧规则
  capabilityGaps:
    knowledgeGaps: string[]        // 知识缺口
    toolGaps: string[]             // 缺少的工具
    skillGaps: string[]            // 缺少的技能
  userFeedbackIntegration:
    implicitSignals: string[]      // 用户的隐式反馈（如修改了输出、追问了某个点）
    explicitFeedback: string       // 用户的显式评价（如果有）
```

### 3.8 进化引擎（Evolution Engine）

**职责**：基于反思引擎的输出，持续改进系统的行为策略。这是系统"自我进化"的核心。

**进化的三种机制**：

**机制 A：规则沉淀（Crystallization）**

当一个策略在多次反思中被反复验证有效，它从"临时笔记"升级为"正式规则"，被写入程序性记忆（skills/目录），未来的 Agent 在执行类似任务时会自动加载它。

类比：一个初级员工逐渐把零散的经验整理成标准操作手册。

**机制 B：基因突变（Mutation）**

当系统在某类任务上的成功率持续高于设定阈值（如 85%）时，进化引擎会尝试"突变"——对现有策略进行微调或替换，看看能否做得更好。突变的方式包括：

- 对已有规则的参数进行微调（如"搜索结果取 top 5"改为"取 top 3"）
- 尝试不同的执行顺序（先搜索后规划 vs 先规划后搜索）
- 引入全新的策略（如"对长文档任务，先生成大纲再逐段填充"）

类比：基因突变 + 自然选择。只有当系统已经"稳定"时才尝试突变，避免在还没学会走路时就尝试跑步。突变后的策略需要经过验证才会被保留。

**机制 C：用户适应（User Adaptation）**

系统持续学习特定用户的偏好、品味和判断模式。这不是简单地记住"用户喜欢简洁的回答"，而是构建一个深层的用户模型（见 3.9 用户模型）。

**核心接口**：

```
EvolutionEngine:
  processReflection(report: ReflectionReport) → EvolutionAction[]
  attemptMutation(skillId: string) → MutationResult
  evaluateMutation(original: Skill, mutated: Skill, testResults: TestResult[]) → KEEP | DISCARD
  getEvolutionHistory() → EvolutionLog[]

EvolutionAction:
  type: CRYSTALLIZE | MUTATE | DEPRECATE | ADAPT
  target: string           // 目标技能或规则的 ID
  description: string      // 人类可读的变更描述
  confidence: float        // 置信度
  requiresHumanApproval: boolean  // 高风险变更需要人类确认
```

### 3.9 用户模型（User Model）

**职责**：构建和维护对当前用户的深层理解——不仅是表面偏好，还包括认知风格、决策模式、价值观和品味。

**用户模型的四个层次**：

| 层次 | 内容 | 示例 | 学习方式 |
|------|------|------|---------|
| 表面偏好 | 格式、语言、长度等 | "喜欢 Markdown 格式"、"偏好中文" | 显式声明 + 统计 |
| 工作模式 | 如何处理任务、决策习惯 | "先发散再收敛"、"喜欢看到多个方案对比" | 行为序列分析 |
| 品味和判断 | 在主观选择中的倾向 | "设计偏好极简风"、"文章倾向启发性而非说教性" | 选择历史分析 |
| 价值观和关切 | 深层关心的东西 | "重视安全性"、"关注用户体验"、"教育公平" | 长期交互推断 |

**核心设计决策**：

- 用户模型以结构化 YAML 文件存储，人类可以审查和修改。
- 每次用户做出选择（如在多个方案中选择了一个、修改了系统的输出、表达了满意或不满），都作为信号更新用户模型。
- 用户模型的更新需要达到一定置信度才会生效，避免单次行为导致的过度拟合。
- 提供"用户模型透明度"——用户可以随时查看系统对自己的理解，并纠正错误。

### 3.10 好奇心引擎（Curiosity Engine）

**职责**：使系统具备主动性——不只是被动执行任务，还能在合适的时机主动向人类提问、请求更多上下文、甚至雇佣人类帮助获取信息。

**好奇心的三种触发条件**：

**触发条件 A：知识缺口（Knowledge Gap）**

系统在执行任务时发现自己缺乏关键信息，且无法通过自主研究获取（如内部文件、个人偏好、尚未公开的信息）。此时，系统会生成一个精确的问题，通过用户的通讯渠道（如 Telegram/WhatsApp）主动提问。

**触发条件 B：决策不确定（Decision Uncertainty）**

系统面临一个重要决策点，有多个合理选项但无法确定用户会偏好哪个。此时，系统不是随机选择或停滞不前，而是将选项及其 trade-off 整理好，请用户做出判断。这同时也是学习用户品味的好机会。

**触发条件 C：能力边界（Capability Boundary）**

系统发现自己需要物理世界的信息或行动（如去某个地方确认情况、拍一张照片、打一个电话），它可以像 rentahuman.ai 那样，明确告诉用户"我需要你帮我做这件事"，并给出精确的指令。

**核心接口**：

```
CuriosityEngine:
  detectGap(currentTask: Task, currentContext: ContextPackage) → Gap | null
  formulateQuestion(gap: Gap) → HumanQuery
  processHumanResponse(query: HumanQuery, response: string) → void

HumanQuery:
  question: string            // 精确的问题
  context: string             // 为什么需要这个信息
  options: string[] | null    // 如果适用，提供选项
  urgency: LOW | MEDIUM | HIGH
  channel: string             // 通过哪个渠道发送
  waitTimeout: Duration       // 等待多久后继续执行
  fallbackStrategy: string    // 如果人类不回复，用什么替代方案
```

---

## 四、系统状态与持久化设计

### 4.1 文件系统布局

整个系统的状态以文件形式持久化在本地，遵循 OpenClaw 的"本地优先"原则：

```
workspace/
├── config/
│   ├── system.yaml              # 系统配置
│   ├── models.yaml              # 模型配置（多模型路由规则）
│   └── tools.yaml               # 工具注册配置
│
├── memory/
│   ├── MEMORY.md                # 语义记忆（持久化事实、规律、用户偏好）
│   ├── daily/
│   │   ├── 2026-02-14.md        # 今日情节记忆（日志）
│   │   ├── 2026-02-13.md        # 昨日情节记忆
│   │   └── ...
│   ├── index/
│   │   ├── vectors.db           # 向量索引（sqlite-vec）
│   │   └── fts.db               # 全文索引（FTS5）
│   └── compaction/
│       └── summaries.jsonl      # Compaction 摘要历史
│
├── skills/
│   ├── builtin/                 # 内置技能
│   │   ├── web_research.yaml
│   │   ├── code_review.yaml
│   │   └── ...
│   ├── learned/                 # 从经验中学到的技能
│   │   ├── skill_001.yaml
│   │   └── ...
│   └── mutations/               # 正在测试的突变技能
│       └── skill_001_v2.yaml
│
├── user_model/
│   ├── profile.yaml             # 用户模型（四个层次）
│   ├── decisions.jsonl           # 用户决策历史
│   └── feedback.jsonl            # 用户反馈历史
│
├── reflections/
│   ├── reflection_001.yaml      # 反思报告
│   └── ...
│
├── evolution/
│   ├── strategy_log.jsonl       # 策略变更日志
│   ├── mutation_tests.jsonl     # 突变测试结果
│   └── rules/
│       ├── active_rules.yaml    # 当前生效的策略规则
│       └── deprecated_rules.yaml # 已废弃的规则（保留供参考）
│
└── sessions/
    ├── session_001.jsonl         # 会话转录（完整轨迹）
    └── ...
```

### 4.2 关键数据结构定义

**TaskReport（任务报告）**——从执行层向上传递：

```yaml
task_id: "task_20260214_001"
original_request: "帮我分析竞品 X 的产品策略"
start_time: "2026-02-14T10:00:00Z"
end_time: "2026-02-14T10:15:00Z"
status: SUCCESS | PARTIAL | FAILURE
execution_trace:
  - step: 1
    agent: PLANNER
    action: "分解为3个子任务"
    tokens_used: 1200
    duration_ms: 3000
  - step: 2
    agent: RESEARCHER
    action: "搜索竞品 X 官网"
    tool_calls: ["browser_navigate", "browser_extract"]
    tokens_used: 2500
    duration_ms: 8000
    result: "获取到产品定价页面内容"
  - step: 3
    agent: RESEARCHER
    action: "搜索竞品 X 的用户评价"
    tool_calls: ["search_web"]
    tokens_used: 1800
    duration_ms: 5000
    error: "搜索结果中没有足够的用户评价"
    error_handled: true
    fallback: "改为搜索应用商店评分"
total_tokens: 15000
total_tool_calls: 12
user_interruptions: 1
user_modifications: 0
final_output_accepted: true
```

**StrategyDirective（策略指令）**——从进化层向下传递：

```yaml
directive_id: "dir_20260214_003"
applies_to: "competitive_analysis"  # 适用的任务类型
rules:
  - rule: "先查官方渠道，再查第三方评价"
    confidence: 0.92
    source: "reflection_042"
  - rule: "对价格信息，优先使用截图而非文字提取"
    confidence: 0.78
    source: "reflection_039"
  - rule: "用户偏好对比表格而非长段落叙述"
    confidence: 0.95
    source: "user_model_update_017"
warnings:
  - "此类任务的信息时效性敏感，注意验证信息日期"
mutation_flag: false  # 当前不尝试突变
```

---

## 五、多模型路由策略

系统不依赖单一模型，而是维护一个模型池，根据子任务类型路由到最适合的模型。

### 5.1 路由规则

```yaml
model_routing:
  # 主推理模型（需要最强能力的任务）
  primary:
    model: "claude-opus-4-5"
    use_for: ["planning", "complex_reasoning", "reflection", "evolution"]
    
  # 快速模型（简单任务、高吞吐）
  fast:
    model: "claude-haiku-4-5"
    use_for: ["tool_selection", "format_conversion", "memory_summarization"]
    
  # 代码模型（代码相关任务）
  code:
    model: "claude-sonnet-4-5"
    use_for: ["code_generation", "code_review", "technical_research"]
    
  # 用户模型更新（需要细腻理解但不需要强推理）
  user_modeling:
    model: "claude-sonnet-4-5"
    use_for: ["user_preference_analysis", "taste_modeling", "sentiment_analysis"]
    
  # 降级策略
  fallback:
    - if: "primary unavailable"
      use: "code"
    - if: "all unavailable"
      action: "queue_and_notify_user"
```

### 5.2 路由决策过程

路由不是硬编码的 if-else，而是上下文引擎的一部分：

1. Agent 编排器确定当前子任务的类型
2. 上下文引擎根据任务类型查找路由规则
3. 检查目标模型的可用性和负载
4. 如果目标模型不可用，按降级策略切换
5. 记录实际使用的模型和效果，供进化引擎优化路由规则

---

## 六、安全与控制

### 6.1 人类监督层级

不同操作有不同的自主权级别：

| 级别 | 含义 | 示例操作 | 
|------|------|---------|
| 0 - 完全自主 | 系统自行执行，不通知人类 | 内部推理、记忆管理、搜索 |
| 1 - 执行后通知 | 系统先执行，然后告知人类结果 | 文件创建、数据分析 |
| 2 - 执行前确认 | 系统准备好方案，等人类确认后执行 | 发送邮件、修改代码、金融操作 |
| 3 - 仅建议 | 系统只提供建议，完全由人类执行 | 重大决策、不可逆操作 |

每个工具在注册时标记其风险等级，系统据此自动确定监督层级。用户可以覆盖默认设置（提高或降低自主权）。

### 6.2 进化安全边界

进化引擎的"基因突变"功能需要明确的安全边界：

- 突变只能修改策略和参数，不能修改系统的安全规则和监督层级
- 每次突变都有明确的回滚机制——如果突变后的策略在 N 次测试中表现不如原策略，自动回滚
- 高置信度的突变（仅微调参数）可以自动执行；低置信度的突变（引入全新策略）需要人类批准
- 所有突变都留有完整的审计日志

### 6.3 透明度保证

- 所有记忆文件使用 Markdown 格式，人类可以直接阅读和编辑
- 用户模型以 YAML 格式存储，用户可以随时查看"系统怎么看我"
- 反思报告和进化日志完全公开
- 系统提供"解释模式"——对任何决策，可以追溯其依据链（从哪条记忆、哪条规则、哪次反思得出）

---

## 七、启动流程

系统的冷启动流程如下：

```
1. 加载配置文件 (config/*.yaml)
2. 初始化事件总线
3. 初始化工具注册表，加载所有工具定义
4. 初始化记忆系统
   a. 加载 MEMORY.md 到语义记忆
   b. 加载今日和昨日的日志到工作记忆
   c. 初始化/验证向量索引和全文索引
5. 初始化上下文引擎
6. 加载用户模型 (user_model/profile.yaml)
7. 加载进化规则 (evolution/rules/active_rules.yaml)
8. 加载已学习的技能 (skills/learned/*.yaml)
9. 初始化 Agent 编排器和各类 Agent
10. 初始化好奇心引擎
11. 启动事件总线监听
12. 发送"系统就绪"事件
```

热启动（从 Compaction 后恢复）时，步骤 4 会额外加载 compaction 摘要，确保不丢失压缩前的关键信息。

---

> **下一篇文档**：《核心子系统设计》——详细展开每个组件的内部设计、算法和实现规范。
