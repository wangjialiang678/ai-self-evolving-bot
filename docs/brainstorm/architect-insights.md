# 架构师视角：调研综合洞察与战略思考

> 日期：2026-02-25
> 输入：docs/research/ 全部 14 篇调研 + docs/brainstorm/ 已有分析 + docs/design/ 设计方案
> 定位：站在架构师视角，综合所有调研材料，回答"我们应该怎么做"

---

## 一、从全部文档中发现的六个关键洞察

### 洞察 1：我们的真正护城河只有一件事

读完全部 6 个开源项目（OpenClaw、Nanobot、Bub、Pi、Letta、Mem0）的深度调研，一个事实非常清楚：

**Agent Loop + Tool Use + Telegram + Memory + LLM Client 全都是已解决的问题。** Nanobot 用 4000 行 Python 实现了完整的工具调用 Agent；Letta 有最成熟的记忆管理；Mem0 有最智能的记忆决策；Bub 有最优雅的 Tape 系统。

**我们系统唯一独有的东西是：Observer → Signal → Architect → Council → Rollback 自进化闭环。** 没有任何一个调研项目有类似设计。Bub 的"自举里程碑"（修复自己的 mypy 错误）只是一个临时行为，不是系统化的机制。OpenClaw 的 Skill 创建是 AI 扩展能力的手段，但没有"观察自己表现→发现改进机会→生成提案→审议→执行→验证→回滚"这套完整链路。

**架构师结论**：把 80% 的精力花在基础设施（别人已解决的问题）上是战略性的浪费。应该把时间集中在核心差异化——进化闭环的打磨和验证上。

### 洞察 2：工程细节的复杂度被严重低估了

读 Nanobot 源码分析（`nanobot-agentloop-source.md`、`nanobot-tools-source.md`、`nanobot-telegram-config-source.md`）后，发现大量"看起来简单但实际很复杂"的工程细节：

| 看起来简单的需求 | 实际需要处理的边界情况 |
|---|---|
| "LLM 返回 tool_call" | `json_repair` 容错解析、`content` 字段必须保留（部分 provider 拒绝缺失）、`reasoning_content` 处理（DeepSeek/Kimi）、`<think>` 标签剥离 |
| "执行 Shell 命令" | 9 种 deny_patterns、路径穿越检测（`../`、绝对路径）、超时 kill + 5s wait、输出截断 10000 字符、工作目录限制 |
| "发 Telegram 消息" | Markdown→HTML 转换（12 步处理顺序）、代码块保护与恢复、4000 字符分段、HTML fallback、Typing 指示器每 4 秒刷新、媒体类型自动识别、语音转文字（Groq Whisper） |
| "记忆压缩" | 何时触发（未压缩消息数 ≥ 100）、保留多少（最近 50 条）、异步后台执行不阻塞、去重保护（防并发压缩）、强制 LLM 使用 save_memory 工具输出结构化结果 |
| "多 Provider 支持" | Prompt Caching（Anthropic 特有）、模型前缀自动匹配、API Key 前缀检测网关、空 content 净化、消息字段白名单过滤 |

**这些不是"有就好"的可选功能——是系统稳定运行的必要条件。** 从头写意味着要踩完全相同的坑，区别只是我们踩还是别人踩。

**架构师结论**：对于已被验证的工程细节（工具调用循环、Telegram 消息处理、Shell 安全守卫），复用比自研的 ROI 高一个数量级。这不是"偷懒"，是"把精力用在有价值的地方"。

### 洞察 3：三个哲学阵营，我们处在中间

调研的 6 个项目可以归为三个阵营：

```
← 受控保守                                           自主激进 →

  Letta/Mem0           Nanobot/Pi              Bub/OpenClaw
  (记忆层框架)          (工具化 Agent)          (AI Native 自驱动)

  - 框架控制记忆管理     - 人定义工具集          - AI 自己写 startup.sh
  - 结构化存储(DB)       - Skills 可热加载       - AI 自己创建 Skills
  - 工具规则约束行为     - 沙箱安全隔离          - Docker 容器即边界
  - 需要 Server 部署     - 单进程本地运行        - 完全自治模式
```

**我们的系统（AI 自进化系统）独特在于**：我们不属于以上任何阵营。我们试图在"受控"和"自主"之间找到一个动态平衡点——**审批级别 0-3 就是这个平衡的具体体现**。Level 0 = 完全自主，Level 3 = 完全受控，中间是渐变的谱系。

**这其实是最难的位置**，因为两边的极端都更容易实现。但从 V3.2 设计文档的愿景来看（"人类在这个循环中的角色：从执行者逐步转变为方向确认者和关键决策者"），这个动态平衡正是我们的核心竞争力。

### 洞察 4："Skill 系统"是所有项目的共同收敛

一个惊人的发现：6 个项目中有 4 个独立演化出了几乎相同的"Skill = Markdown 文件 + 渐进式加载"模式：

| 项目 | Skill 格式 | 加载机制 |
|---|---|---|
| OpenClaw | `SKILL.md` + YAML frontmatter | 选择性注入，运行时只加载相关 skill |
| Nanobot | `SKILL.md` + always/available 分级 | always skill 全载，available skill 只显示摘要 |
| Bub | `SKILL.md` + `$hint` 触发 | 三级加载：元数据→body→捆绑资源 |
| Pi | `SKILL.md` + agentskills.io 标准 | LLM 自主判断是否读取完整内容 |

**我们的 `workspace/rules/` 本质上就是一个早期的 Skill 系统**，但缺少：
- 标准化的 frontmatter（触发条件、描述、版本）
- 渐进式加载（当前全量注入上下文）
- AI 自主创建能力

这说明"Skill = 可被 AI 读写的文本知识单元"是一个**已被验证的设计模式**。我们应该在规则系统中引入这个模式，而不是从零发明。

### 洞察 5：V3.2 设计方案的基础设施层写了"NanoBot 框架"

回看 `v3-2-system-design.md` 第 3.1 节的架构图：

```
基础设施层 (Infrastructure)
  NanoBot 框架 | LLM 网关 | 通信通道 (Telegram/Web)
```

**设计文档本身已经预设了使用 Nanobot 作为基础设施。** 但当前实现（`core/agent_loop.py`、`core/llm_client.py`）是完全自研的，与设计方案存在偏差。

这说明两件事：
1. 设计者（你）在写设计方案时已经认为 Nanobot 是合适的基础设施
2. 实际开发走了自研路线，可能是出于"先跑起来"的务实考虑

**架构师结论**：现在回到设计方案的初衷——用 Nanobot 作为基础设施层——是合理的。不是"推翻重来"，而是"回到设计"。

### 洞察 6：双轨策略可能是最优解

你提到的第 4 点思路——"当前项目继续迭代，同时在已有框架上开始新项目"——不仅可行，而且可能是**唯一能同时验证两个假说的方法**：

**假说 A**：一个从零开始的简单系统，能通过自进化逐步把轮子造起来（当前项目验证）

**假说 B**：在成熟框架上嫁接自进化能力，能更快达到实用水平（新项目验证）

这两个假说不矛盾，甚至互补：
- 项目 A 验证"自进化的极限在哪里"——如果系统真的能自己造出工具调用，那就证明了进化机制的强大
- 项目 B 验证"自进化+实用工具=多大价值"——如果自进化 Agent 有了工具能力后变得极其有用，那就证明了方向正确

---

## 二、四种复用策略的深度分析

结合你提到的四个因素，逐一展开分析。

### 策略 1：参考原理，自研代码（当前路线）

**做对了什么**：
- 架构完全自主，"观察-进化"闭环是纯原创设计
- 代码风格统一（全异步、BaseLLMClient 抽象、JSONL 事件流）
- 无外部依赖风险，499 个测试全部 mock
- 验证了"从简单规则生长出复杂行为"的可能性

**代价是什么**：
- Agent Loop 没有 Tool Use（用户请求"帮我看文件"只能幻觉）
- Memory Store 是 append-only Markdown（无去重、无向量检索）
- 反思引擎的输入信息密度不够（system_response 截断 500 字符）
- L0 原始日志层缺失（Observer 看不到原始数据）
- 以上问题都是别人已经解决的，我们要重新解决一遍

**什么时候适合**：
- 核心差异化模块（Observer、Architect、Council、Signal）→ **必须自研**
- 简单到不值得引入外部依赖的模块（Config、Bootstrap）→ 保持自研

### 策略 2：在开源项目基础上修改（Fork 模式）

**实际操作会怎样**：

以 Nanobot 为例（最接近我们的架构）：

```
Fork HKUDS/nanobot
  └─ 保留：
     ├─ Agent Loop（loop.py, 460 行）→ 工具调用循环、迭代上限
     ├─ Tool System（tools/, 7 个内置工具 + Registry）
     ├─ Provider System（providers/, LiteLLM 多 Provider）
     ├─ Telegram Channel（channels/telegram.py, 完整实现）
     ├─ MessageBus（bus/, 事件解耦）
     ├─ Session Manager（session/, JSONL 持久化）
     ├─ Skill System（skills/, 渐进加载）
     └─ Config System（config/, Pydantic BaseSettings）
  └─ 替换/新增：
     ├─ memory.py → 替换为我们的 MemoryStore（4 层记忆）
     ├─ 新增 extensions/observer/
     ├─ 新增 extensions/signals/
     ├─ 新增 extensions/memory/reflection.py
     ├─ 新增 core/architect.py
     ├─ 新增 core/council.py
     ├─ 新增 extensions/evolution/rollback.py
     ├─ 新增 extensions/evolution/metrics.py
     ├─ 新增 extensions/context/compaction.py
     └─ context.py → 融合我们的 TokenBudget 机制
```

**优势**：
- **立即获得工具调用能力**（Agent Loop + Tool Registry + 7 个内置工具）
- 不用处理那些"看起来简单但实际很复杂"的工程边界情况
- Telegram 集成开箱即用（包括语音转文字、Markdown→HTML、Typing 指示器）
- 多 Provider 支持开箱即用（15+ 个 LLM 服务商）
- 已有 Skill 系统可以直接用于我们的规则/经验
- 可以直接对接 ClawHub 5700+ 社区技能

**挑战**：
- 需要深入理解 Nanobot 的代码才能安全修改
- 与上游 drift——Nanobot 更新后我们的修改可能冲突
- 需要把 Python 代码风格统一（Nanobot 用 loguru + Pydantic，我们用 logging + dataclass）
- 初始投入：2-3 天理解代码 + 3-5 天嫁接进化模块

**适合的模块**：Agent Loop、Tool System、Telegram、Provider、MessageBus、Session、Config、Skill

### 策略 3：拼接复用开源框架一部分代码

**实际操作会怎样**：

从多个项目中提取特定模块：

```
从 Nanobot 提取：
  ├─ tools/base.py → Tool 抽象基类 + validate_params
  ├─ tools/registry.py → ToolRegistry（注册/执行/schema 生成）
  ├─ tools/filesystem.py → _resolve_path 沙箱机制
  ├─ tools/shell.py → deny_patterns 安全守卫
  └─ providers/base.py → LLMResponse + ToolCallRequest 数据类

从 Letta 提取思路：
  ├─ Block 机制（有字符限制的记忆块）→ 改造我们的 MemoryStore
  ├─ ToolRules（TerminalToolRule、RequiresApprovalToolRule）→ 融入审批系统
  └─ Summarizer 部分驱逐策略 → 改造我们的 Compaction

从 Mem0 提取思路：
  ├─ ADD/UPDATE/DELETE/NONE 记忆决策 → 替代 append-only
  ├─ UUID 整数映射（防幻觉）
  └─ 历史审计表（SQLite history）

从 Bub 提取思路：
  ├─ Tape fork/merge 语义 → 隔离实验性操作
  └─ ProgressiveToolView → 渐进式工具详情展开
```

**优势**：
- 灵活性最高——每个模块选最好的实现
- 不受单一项目架构约束
- 保持我们自己的代码组织方式
- 可以逐步引入，不需要一次性大改

**挑战**：
- **集成成本高**：每个片段的隐含依赖不同（Nanobot 的 Tool 依赖 LiteLLM，Letta 的 Block 依赖 PostgreSQL）
- **测试负担重**：提取的代码需要在我们的环境重新验证
- **风格不一致**：不同项目的代码风格、错误处理、日志方式都不同
- **License 审查**：需要逐个确认许可证兼容性

**适合的场景**：
- 需要某个特定功能的算法/数据结构，但不需要整个框架
- 多个项目各有优点，没有一个完美匹配
- 代码片段是独立的、可移植的

### 策略 4：双轨并行（你提到的新思路）

**这个策略值得展开讨论，因为它可能是最优解。**

```
┌─────────────────────────────────────────────────────────────┐
│ 轨道 A：当前项目（evo-agent）                                  │
│                                                             │
│ 定位：进化机制的"纯净室"验证                                    │
│ 策略：继续自研，慢慢迭代                                        │
│ 目标：                                                       │
│   - 验证"自进化能从简单规则生长出来"                             │
│   - 验证"观察-信号-提案-审议-执行-回滚"闭环的有效性                │
│   - 作为进化模块的开发和测试平台                                 │
│   - 保持代码简洁，499 个测试全部通过                              │
│                                                             │
│ 不急于做的事：                                                 │
│   - Tool Use（继续纯对话模式也能验证进化机制）                    │
│   - 多 Provider 支持（当前 2 个够用）                           │
│   - 媒体消息处理、语音转文字                                     │
│                                                             │
│ 风险：缺乏实用性，只能作为研究原型                                │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│ 轨道 B：新项目（evo-nanobot 或类似名称）                         │
│                                                             │
│ 定位：在成熟基础设施上嫁接自进化能力                               │
│ 策略：Fork Nanobot，替换/新增核心进化模块                        │
│ 目标：                                                       │
│   - 2-3 周内获得"能用工具的自进化 Agent"                        │
│   - 验证"自进化 + 实用工具 = 多大价值"                          │
│   - 实际日常使用，积累真实的进化数据                              │
│   - 快速验证 V3.2 设计方案中的场景                               │
│                                                             │
│ 复用 Nanobot 的部分：                                          │
│   - Agent Loop（含 Tool Use 循环，max 40 轮）                  │
│   - Tool System（7 个内置工具 + ToolRegistry）                 │
│   - Provider System（LiteLLM，15+ Provider）                  │
│   - Telegram Channel（完整实现 + 语音转文字）                   │
│   - MessageBus + ChannelManager                              │
│   - Session Manager（JSONL 持久化）                           │
│   - Skill System（渐进加载）                                   │
│   - Config System（Pydantic BaseSettings）                    │
│                                                             │
│ 从轨道 A 移植的核心模块：                                       │
│   - Observer Engine（轻量 + 深度双模式）                        │
│   - Signal Detector + Store                                  │
│   - Reflection Engine                                        │
│   - Architect Engine + Council                               │
│   - Rollback Manager + Metrics Tracker                       │
│   - Context Engine（TokenBudget 机制）                        │
│   - Rules Interpreter                                        │
│                                                             │
│ 风险：与 Nanobot 上游 drift，需要持续维护                         │
└─────────────────────────────────────────────────────────────┘
```

**双轨策略的关键好处**：

1. **风险对冲**：如果自研路线太慢，fork 路线已经在跑；如果 fork 路线遇到兼容性问题，自研路线不受影响
2. **进化模块可共享**：Observer/Architect/Council 等核心模块在两个项目间通用，修改一次两边受益
3. **快速获得真实数据**：轨道 B 可以在日常使用中积累真实的进化数据（错误模式、用户纠正、性能指标），反哺轨道 A 的设计
4. **验证两个不同假说**：A 验证"从简单到复杂"，B 验证"在成熟基础上创新"

**双轨策略的成本**：
- 维护两个代码库的认知负担
- 进化模块的接口需要足够抽象，才能在两个项目间复用
- 需要明确哪个项目是"主线"，避免精力分散

---

## 三、为什么选 Nanobot 而不是 OpenClaw 或 Bub

### 候选项对比

| 维度 | Nanobot | OpenClaw | Bub |
|---|---|---|---|
| **语言** | Python | TypeScript | Python |
| **代码量** | ~4000 行 | 数万行（含 Pi 框架） | ~3000 行 |
| **架构匹配度** | 非常高（几乎 1:1） | 中等（双层架构更复杂） | 高（但 Tape 系统差异大） |
| **工具调用** | 完整（7 个内置 + MCP） | 完整（25 个内置） | 完整（bash/fs/web） |
| **Telegram** | python-telegram-bot（同款） | grammY（TypeScript） | python-telegram-bot（同款） |
| **记忆系统** | MEMORY.md + HISTORY.md | Session compaction | Tape（JSONL，fork/merge） |
| **Skill 系统** | 有（渐进加载） | 有（ClawHub 生态） | 有（三级加载） |
| **LLM 抽象** | LiteLLM（100+ Provider） | Pi-AI（15+ Provider） | republic 框架 |
| **改造难度** | 低（代码简洁，Python） | 高（跨语言，架构复杂） | 中（Tape 概念需适配） |
| **社区活跃度** | 高（17.8K stars） | 极高（214K stars） | 中等 |

### 结论：Nanobot 是最佳 Fork 基座

原因：
1. **Python 同栈**——直接复用，无需跨语言桥接
2. **架构几乎 1:1 匹配**——MessageBus、AgentLoop、ChannelManager、SessionManager，连命名都相似
3. **使用同一个 Telegram 库**（python-telegram-bot）——配置和消息处理逻辑可直接迁移
4. **代码量克制**（4000 行）——可以在 1-2 天内完全理解
5. **记忆系统最简单**（两个 Markdown 文件）——最容易被我们的 4 层记忆替换

OpenClaw 虽然功能最完整，但 TypeScript 跨语言是硬伤。Bub 的 Tape 系统虽然优雅，但与我们现有的 JSONL 存储模式差异大，改造成本高。

---

## 四、对你提出的四个因素的具体回应

### 因素 1："很多工程性问题有很多技术细节，复用会让我们少踩很多坑"

**完全同意。** 读完 Nanobot 的三篇源码分析后，我深刻意识到：

那些"看起来简单"的工程细节，恰恰是最消耗时间的部分：
- `json_repair` 解析 LLM 返回的不规范 JSON → 没有这个，某些模型的 tool_call 会直接崩溃
- `_sanitize_empty_content()` 处理空消息 → 没有这个，StepFun 等 Provider 会拒绝请求
- `difflib.SequenceMatcher` 在 EditTool 找不到精确匹配时提供模糊提示 → 没有这个，LLM 会反复尝试错误的 old_text
- `_markdown_to_telegram_html` 的 12 步处理 → 没有这个，Telegram 消息格式全乱
- Shell 的 deny_patterns + 路径穿越检测 → 没有这个，安全风险极大

这些都是**已验证的工程智慧**，不是"别人的代码"，是"别人踩过的坑的结晶"。复用这些是在站在巨人肩膀上。

### 因素 2："从头写好处是架构完全自主，但时间周期长"

**部分同意。** 从头写确实验证了一件重要的事：我们的"观察-进化"架构设计是对的——499 个测试通过、进化闭环可以工作。

但也要看到代价：
- 写了 ~3000 行核心代码 + ~2000 行测试代码
- 仍然没有 Tool Use
- 记忆系统仍然是 bigram 关键词搜索
- 反思引擎的输入信息密度不够
- L0 原始日志层缺失

**如果继续纯自研路线**，Tool Use 至少还需要 2-3 周（LLM Client 改造 + Agent Loop 改造 + Tool Registry + 内置工具 + 安全沙箱）。这 2-3 周做的事，Nanobot 已经做完了。

**架构自主性的真正价值不在基础设施层**，而在认知层和自治层。基础设施用别人的代码不影响我们的架构自主性——就像 Linux 用 Intel 的 CPU 不影响 Linux 的架构自主性。

### 因素 3："拼接复用开源框架一部分代码，好处和挑战是什么"

**好处**：
- 灵活度最高——"挑最好的零件"
- 不被单一项目绑定
- 可以逐步引入（先引入 ToolRegistry，再引入 Shell 安全守卫，再引入 Telegram HTML 转换……）

**挑战**（读完所有源码后的现实判断）：
- **隐含依赖链比想象中长**：Nanobot 的 `Tool.execute()` 返回 `str`，但 `ToolRegistry.execute()` 会追加 `_HINT` 错误引导，而 `_HINT` 的措辞与 Agent Loop 的重试逻辑紧密配合。提取 ToolRegistry 就意味着要一起提取 _HINT 机制，而 _HINT 又依赖 Agent Loop 的容错设计。
- **消息格式是全局约定**：`LLMResponse.tool_calls[].arguments` 是 `dict`（已解析），而 OpenAI 原始格式是 `str`（JSON 字符串）。提取 Provider 层就意味着要在 Agent Loop 中适配其消息格式。
- **风格不一致的认知负担**：一部分代码用 `loguru.logger`，一部分用 `logging.getLogger`；一部分用 `@dataclass`，一部分用 `Pydantic BaseModel`。混搭会让代码库变得"精神分裂"。

**我的判断**：拼接策略适合"概念级借鉴"（如 Letta 的 Block 机制、Mem0 的 ADD/UPDATE/DELETE 决策），不适合"代码级提取"（如直接复制 Nanobot 的 ToolRegistry 文件）。概念可以用自己的代码风格重新实现，代码级提取往往连带出一串依赖。

### 因素 4："继续迭代当前项目，同时在 Nanobot 基础上开新项目"

**这是我推荐的策略。** 理由在上文"双轨策略"一节已经详述。补充几点实操建议：

**关键设计约束——进化模块必须是可移植的**：

为了让 Observer/Architect/Council 等模块在两个项目间共享，它们的接口需要满足：

```python
# 进化模块的"可移植接口"约定

class EvolutionModule(ABC):
    """所有进化模块的共同接口"""

    async def initialize(self, config: dict, llm_client: Any) -> None:
        """初始化，只依赖 config dict 和一个能 complete() 的 LLM client"""

    # 不依赖具体的 AgentLoop、ContextEngine、MemoryStore 实现
    # 只依赖标准的数据格式（task_trace dict、signal dict 等）
```

**当前项目的进化模块已经基本满足这个约束**（它们通过 LLMClient ABC + 文件系统交互），只需要稍作调整就能移植到 Nanobot 架构上。

---

## 五、推荐行动方案

### 短期（1-2 周）

1. **Fork Nanobot，创建 evo-nanobot 项目**
   - 保留 Nanobot 的全部基础设施（Agent Loop、Tool System、Telegram、Provider、Bus）
   - 移植我们的核心进化模块（Observer、Signal、Architect、Council、Rollback、Metrics）
   - 在 Nanobot 的 `_process_message()` 后处理链中注入反思→信号→观察→指标
   - 保留 Nanobot 的 Skill 系统，将我们的 `workspace/rules/` 改造为 Skill 格式

2. **当前项目继续作为进化机制的测试平台**
   - 不再追加基础设施功能（Tool Use 等）
   - 专注打磨进化闭环的核心逻辑
   - 保持测试覆盖率

### 中期（3-6 周）

3. **在 evo-nanobot 上验证 V3.2 设计方案中的场景**
   - 场景 1（Bootstrap 引导）→ 复用 Nanobot 的 onboard 流程
   - 场景 5（首次自主进化）→ 用真实的工具调用数据触发 Observer
   - 场景 8（能力边界主动发现）→ AI 发现缺少某个 Skill → 自己创建

4. **Memory Store 升级**
   - 引入 Block 机制（参考 Letta，字符上限的记忆块）
   - 引入 ADD/UPDATE/DELETE 记忆决策（参考 Mem0）
   - 用 sqlite-vec 替代 bigram 关键词搜索

### 长期（2-3 月）

5. **根据两个项目的真实数据，决定哪个成为"主线"**
   - 如果 evo-nanobot 的进化效果明显更好（因为有工具调用产生更丰富的信号）→ 主线切到 B
   - 如果当前项目的纯净架构反而进化更优雅 → 主线留在 A
   - 也可能合并：将 A 的纯净进化模块 backport 到 B

---

## 六、一张图总结

```
                    我们的核心差异化
                         │
                    ┌────┴────┐
                    │ 进化闭环  │  Observer → Signal → Architect
                    │ (自研)   │  → Council → Rollback → Metrics
                    └────┬────┘
                         │
              ┌──────────┼──────────┐
              │                     │
        ┌─────┴─────┐        ┌─────┴─────┐
        │ 轨道 A     │        │ 轨道 B     │
        │ evo-agent  │        │ evo-nanobot│
        │ (纯自研)   │        │ (Fork)     │
        └─────┬─────┘        └─────┬─────┘
              │                     │
     验证"进化从简单        验证"进化+工具
      规则生长出来"          =多大价值"
              │                     │
       继续慢慢迭代           2-3 周可用
       保持代码简洁           Nanobot 基础设施
       作为研究原型           真实日常使用
```

---

## 七、最后的思考

读完全部文档后，我最大的感触是：**这个项目的真正价值不在代码，在思想。**

"双螺旋智能"、"规则即程序"、"爆炸半径优于权限控制"、"信号驱动而非时间驱动"——这些设计原则是独创的，在调研的 6 个开源项目中都没有对应物。代码可以被复制，但这套认知框架不能。

所以最终的策略应该是：**把思想保留在进化模块中（自研），把体力活交给成熟框架（复用）。** 这不是妥协，而是让正确的事情在正确的地方发生。
