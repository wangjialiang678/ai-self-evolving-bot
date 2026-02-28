# 深度分析：《复刻一只 OpenClaw，需要些什么？》

**日期**: 2026-02-25
**来源**: Founder Park（极客公园）微信公众号，作者署名"喵小姐love小西柚"
**原文副标题**: 在复刻的过程中悟到了 AI Native 的真谛

---

## 一、文章系统概述

### 1.1 OpenClaw 生态全景

OpenClaw（前身 ClawdBot/Moltbot）是目前最具代表性的个人 AI Agent 平台之一，由 Peter Steinberger 创建，2025 年 11 月发布后迅速积累 214,000+ GitHub Stars。其核心定位是"本地优先的通用 AI 助手"——通过 Telegram、WhatsApp、Discord 等聊天软件接收自然语言指令，在用户本机自主完成各类任务。

OpenClaw 生态由以下核心组件构成：

| 组件 | 定位 | 技术栈 |
|------|------|-------|
| OpenClaw Gateway | 永远在线的控制平面 | TypeScript/Node.js |
| Pi Agent Core | Agent Loop + 工具调用引擎 | TypeScript |
| ClawHub | 社区技能注册表（5700+ skills） | 公开注册表 |
| SKILL.md | 技能描述格式（纯 Markdown） | 文本文件 |

这篇文章的主角是围绕 OpenClaw 形成的一个**复刻生态**：

- **Nanobot**（https://github.com/HKUDS/nanobot）：香港大学数据智能实验室出品，用约 4000 行 Python 代码复现 OpenClaw 的核心能力，定位是"最小化官方参考实现"。
- **Bub**（https://github.com/PsiACE/bub）：一个独立的小型 Agent 项目，文章作者将其改造为 OpenClaw 的自己动手版复刻。
- **Pi**（https://github.com/badlogic/pi-mono）：Pi Agent Framework 的参考实现，体现"最小化工具集"的设计哲学。

### 1.2 文章的核心叙事

文章不只是"如何复刻"的操作教程，而是通过复刻实践**顿悟**了一件更重要的事：什么是真正的 AI Native。作者在尝试用框架（LangChain 等）复刻时碰壁，在抛弃框架、回归"只给 AI 一个推理核心+一个存 Skill 的地方"之后，豁然开朗。这个顿悟构成了文章最有价值的部分。

---

## 二、AI Native 理念深度分析

### 2.1 AI 应用的三个时代

文章提出了一个简洁但有力的演进框架：

```
1.0 Chatbot 时代    →    2.0 Agent 时代    →    3.0 AI Native 时代
每次对话 = 1次LLM推理      Tool Call，几轮到百轮      AI 自己管理工具和技能
      (被动响应)           (Claude Code, Codex)        (自我驱动，人不介入)
```

**1.0 Chatbot 时代**的本质：AI 是一个无状态的函数。输入问题，输出答案，无记忆，无行动能力。每次对话都是孤立的 LLM 推理。这个时代已经结束。

**2.0 Agent 时代**的本质：AI 获得了"手"（工具调用）。一次任务可能触发几轮到上百轮 LLM 推理，每轮可以调用文件系统、浏览器、代码执行等工具。Claude Code、Codex 是这个时代的代表产品。但工具集仍然是**人类预先定义的**——人类决定 AI 能做什么，AI 在边界内执行。

**3.0 AI Native 时代**的本质：AI 开始管理自己的工具和技能，甚至自己写代码实现新功能，不需要人类干预。人类只发自然语言指令，AI 是一个黑箱。这个时代的关键特征：

- **工具不是固定的**：AI 可以学习新技能、创建新工具
- **框架退到最小**：只剩一个推理核心，其余都是 AI 自己搭建的
- **自驱动**：AI 不只是被动响应，而是主动维护自己的运行状态

### 2.2 为什么"框架越小越好"

这是文章最具反直觉价值的洞见，值得深入展开。

**传统思路（框架优先）**：
> 给 AI 配备尽可能多的工具和框架（LangChain/AutoGen/CrewAI），让框架约束 AI 的行为，通过框架的 API 调用来完成任务。

**AI Native 思路（推理核心优先）**：
> 给 AI 一个推理核心（能 inference 的引擎），给 AI 一个存放技能的地方（文件系统），其他的让 AI 自己去搞。

框架越大，意味着：
1. **AI 被迫适应框架的抽象**，而不是用最自然的方式解决问题。一个框架定义了"工具是什么"、"如何调用工具"，但 AI 对这些抽象并没有真正的理解，只是被强制执行——这就是"让 AI 当小白鼠"。
2. **框架创造了不必要的耦合**。框架版本升级、接口变更，AI 就失效了。
3. **框架剥夺了 AI 的灵活性**。面对框架没有定义的场景，AI 无能为力；面对框架已经定义的场景，AI 只能按框架的方式做，即使有更好的方法。

当框架缩减到只有"推理核心"时：
- AI 可以用任何方式（HTTP API、命令行、Python 脚本）实现任何功能
- AI 自己创建的技能是文本（Skill 文件），可以被 AI 自己修改和迭代
- AI 的行动空间不受框架限制，只受宿主系统能力限制

**关键洞见**：框架是人类为了控制 AI 而发明的工具，而 AI Native 是让 AI 真正自主的前提之一。这不是"工具越少越好"，而是"控制 AI 的层次应该从框架层转移到 Prompt 层"。

### 2.3 工具（Tool）vs 技能（Skill）：一个哲学区别

这个区分是 OpenClaw 生态最重要的概念创新之一。文章将其表述为：

> **工具是框架提供的（固定的），Skill 是文本（AI 可以自己创建修改）。**

具体来说：

| 维度 | Tool（工具） | Skill（技能） |
|------|-------------|--------------|
| 本质 | 可执行代码/API 调用 | 纯文本（Markdown 文件） |
| 谁定义 | 人类开发者 | 任何人，包括 AI 自己 |
| 修改成本 | 需要重新部署代码 | 直接编辑文件，即时生效 |
| 内容 | 函数签名、执行逻辑 | 自然语言指令、示例、注意事项 |
| 作用方式 | 供 LLM 在 tool_call 时调用 | 注入 system prompt，影响 LLM 行为 |
| 典型例子 | `exec(cmd)`, `read_file(path)` | "如何用 Telegram HTTP API 发消息" |

**工具**（Tool）的类比：一把锤子。锤子是固定的，你不能让锤子学会新技能，你只能制造新的锤子。工具决定 AI **能**做什么。

**技能**（Skill）的类比：一本教材。教材是文字，可以随时增删改，AI 读完就"学会了"。技能决定 AI **如何**做。

在实践中，文章描述了一个具体案例：AI 自己学习 Telegram 发消息的技能。整个过程不涉及任何代码修改：
1. 告诉 AI：需要通过 Telegram 发消息
2. AI 查阅 Telegram HTTP API 文档
3. AI 将学到的方法写成一个 SKILL.md 文件
4. 从此 AI 就会发 Telegram 消息了——通过读取这个 Skill，调用已有的 HTTP 工具

这个案例的意义在于：**AI 扩展了自己的能力，但没有触碰任何代码**。人类只需要提供一个通用的 HTTP 调用工具，AI 负责学习如何使用不同 API。

### 2.4 AI 自驱动：startup 协议的意义

文章描述了 Bub 复刻中最核心的机制——startup 协议。

**问题背景**：如何让 AI 在容器启动后"知道自己应该做什么"？传统方法是代码写死初始化逻辑，但这违背了 AI Native 的精神。

**startup 协议的设计**：
1. Docker 容器启动时，读取 AI 自己之前写的 `startup.sh` 脚本
2. 执行脚本，完成初始化（连接 Telegram、加载技能等）
3. AI 通过收发消息继续运行和进化

关键点：**startup 脚本是 AI 自己写的，不是人类写的**。这意味着：
- AI 的初始化逻辑可以随着 AI 的学习而进化
- 如果 AI 发现更好的启动方式，可以自己修改 startup 脚本
- 容器重启后，AI 恢复到上次进化后的状态

结合 Docker 进程管理 + AI 单次 Prompt 执行模式：
```
用户发消息 → Telegram Bot 收到 → 触发一次 AI 推理 → AI 执行工具/写技能 → 回复用户
                                                         ↑
                              startup 脚本由 AI 自己维护，定义启动时的初始化逻辑
```

**startup 协议的本质意义**：它将"系统初始化"这个传统上属于人类开发者的职责，移交给了 AI 自己。这是一种深层次的控制权转移——不只是"AI 执行任务"，而是"AI 管理自己的运行环境"。

---

## 三、技术架构分析

### 3.1 OpenClaw 的架构推断

基于已有调研（`docs/research/openclaw.md`）和文章内容，OpenClaw 的架构可以这样理解：

```
用户 (Telegram/WhatsApp/Discord)
    ↓ 消息
Gateway（永远在线的控制平面）
    - WebSocket Hub: ws://127.0.0.1:18789
    - Channel Adapters（各平台适配器）
    - Session Manager
    ↓
Pi Agent Core（Agent Loop 引擎）
    - 上下文组装（Base Prompt + Skills 选择性注入）
    - LLM 推理
    - Tool Execution（25 个内置工具）
    - 事件流（tool_start/tool_end/delta）
    ↓
工具层
    - 文件系统（read/write/edit）
    - Shell 执行（exec/bash）
    - 浏览器控制（Chrome CDP）
    - 消息发送（messaging）
    - 定时任务（cron）
    ↓
Skills 层（文本文件，注入到 prompt）
    - workspace/skills/（工作区级别）
    - ~/.openclaw/skills/（用户级别）
    - ClawHub（5700+ 社区技能）
```

**架构的核心哲学**：Gateway 是固定的基础设施（"操作系统"），Skills 是 AI 的知识库（"用户程序"），两者分离，Skills 可以自由增减。工具（Tool）是 AI 的执行手段，技能（Skill）是 AI 的行为指南。

### 3.2 Bub 的最小化复刻架构

文章描述的 Bub 复刻版本极度精简：

```
┌─────────────────────────────────────┐
│  Docker 容器                         │
│                                     │
│  startup.sh（AI 自己写的）           │
│       ↓ 执行                        │
│  AI 推理核心（单次 Prompt 模式）      │
│       ↓ 工具调用                    │
│  HTTP 工具（通用）                   │
│       ↓ 读取                        │
│  Skills 目录（文本文件）             │
│           ↕ 读写                    │
│  Telegram Bot API（通过 HTTP 工具）  │
└─────────────────────────────────────┘
```

**最小化的含义**：
- 不依赖任何 Agent 框架（无 LangChain、无 LlamaIndex）
- 工具集极小（只需通用 HTTP 调用）
- AI 的能力通过 Skill 文件扩展，而非代码
- startup 协议保证容器重启后恢复运行状态

**复刻步骤**：
1. 启动一个支持技能的 Agent（Codex/Claude Code），让它写 startup 脚本
2. 准备 Dockerfile（基础容器环境）
3. 构建并运行 Docker 容器
4. 后续通过发消息让它自我进化

这个流程的关键是：人类只提供了**容器环境**和**初始指令**，AI 自己负责其余一切——包括学习如何接收消息、学习如何发消息、学习如何扩展技能。

### 3.3 Nanobot 的定位

Nanobot（HKUDS）作为"OpenClaw 最小化复现"，与 Bub 复刻的思路不同：

| 维度 | Bub 复刻 | Nanobot |
|------|---------|---------|
| 目标 | 验证 AI Native 理念 | 工程化参考实现 |
| 代码量 | 极小 | ~4000 行 Python |
| AI 自驱动 | 核心特性（startup 协议） | 无（传统框架模式） |
| Skills 系统 | AI 自己创建 Skill | 渐进加载 Skills |
| 框架依赖 | 无 | Python 生态 |
| 定位 | 概念验证 | 生产可用替代品 |

Nanobot 选择了"最少工程量实现最多 OpenClaw 功能"的路线，而文章中的 Bub 复刻选择了"最小化但体现 AI Native 本质"的路线。两者殊途而略同归，但 Bub 复刻在哲学层面走得更远。

---

## 四、与我们 AI 自进化系统的关联分析

### 4.1 两个项目的相同点

我们的 evo-agent 和 OpenClaw/Bub 的 AI Native 方向，在根本目标上是一致的：**AI 应该能够自我改进，减少人类在系统演化中的直接参与**。

具体的共同元素：

| 共同元素 | evo-agent | OpenClaw/Bub |
|---------|-----------|-------------|
| Telegram 交互 | 核心接口 | 核心接口 |
| 规则/技能文件 | `workspace/rules/*.md` | `workspace/skills/*.md` |
| 自我进化 | Architect 生成进化提案 | AI 自己创建和修改 Skill |
| 观察-改进闭环 | Observer → Architect | AI 自己观察 → 自己修改 Skill |
| 文本作为知识载体 | Markdown 规则文件 | Markdown Skill 文件 |
| 记忆持久化 | memory.py | MEMORY.md 文件 |
| 运行时自修改 | Architect 修改规则文件 | AI 修改 Skill 文件 |

**最关键的共同点**：两者都把**文本文件**（Markdown）作为 AI 行为规则的载体，都认为"可以被 AI 读写的文本文件"是比"代码"更适合 AI 管理的知识形式。

### 4.2 两个项目的不同点

| 维度 | evo-agent（我们的项目） | OpenClaw AI Native 方向 |
|------|----------------------|----------------------|
| 自进化的触发者 | 系统自动（Observer 定时分析） | AI 自主（无需定时任务） |
| 进化审批 | 多级审批机制（Architect） | AI 自己决定（除非明确要求审批） |
| 框架规模 | 中等规模 Python 框架 | 极简（只有推理核心） |
| 工具能力 | 无工具（纯对话，正在调研加入） | 丰富工具（文件、Shell、浏览器等） |
| Skill 创建 | 无（规则由 Architect 修改） | AI 自己创建 Skill |
| 启动协议 | 代码写死 main.py 初始化 | startup.sh 由 AI 自己写 |
| 控制权分配 | 人类保留较多控制权 | AI 获得较多自主权 |
| 安全边界 | 多层审批（blast_radius 评估） | Docker 容器隔离 |
| 进化粒度 | 规则文件级别（md 内容替换） | 技能级别（新增/修改 skill） |

**核心差异的本质**：

evo-agent 的设计哲学是"**受控进化**"——AI 可以进化，但每一步进化都经过人类审批或至少人类知晓。Observer 观察，Architect 提议，人类批准，然后执行。这是一个"AI 做建议，人类做决策"的模型。

OpenClaw/Bub 的 AI Native 哲学是"**自主进化**"——AI 自己学习、自己创建工具、自己管理运行环境。人类发出自然语言指令，AI 自主完成。进化不需要人类批准，因为进化发生在"Skill 创建"这个低风险层面。

### 4.3 可以从文章汲取的设计灵感

#### 灵感一：引入 Skill 系统，区分"规则"和"技能"

当前 evo-agent 的 `workspace/rules/` 只包含行为规范（identity、constitution、experience），没有"技能"的概念。可以参考 OpenClaw 的 Skill 架构，在 `workspace/` 下增加：

```
workspace/
├── rules/          # 行为规范（现有）
│   ├── constitution/
│   └── experience/
└── skills/         # 技能知识（新增，AI 可自己创建）
    ├── telegram-api.md    # 如何使用 Telegram API
    ├── file-search.md     # 如何搜索文件
    └── ...
```

区别在于：规则约束 AI 的行为边界，技能指导 AI 完成具体任务。技能的门槛低于规则，AI 自己创建技能的风险小于修改规则。

#### 灵感二：重新审视 startup 协议

evo-agent 的 `core/bootstrap.py` 承担了初始化职责，但它是**人类写的固定代码**。参考 startup 协议的思想：

> 能否让 AI 维护自己的"启动配置"？

不一定要实现完全的 startup 脚本，但至少可以让 AI 通过 Architect 修改自己的初始化行为——例如，修改 bootstrap 阶段的问题列表、修改 DND 时间、调整观察频率。这些本质上是 AI 在"重新配置自己的启动行为"。

#### 灵感三：降低进化的粒度，让 AI 更自主

当前 Architect 进化最小单位是"修改规则文件"，blast_radius 从 trivial 到 large，level 0-3 审批。文章提示：技能创建的风险低于规则修改，可以对 Skill 创建放开更低级别（level 0，AI 自动执行）。

```
进化类型       →   审批级别   →   理由
新增 Skill     →   Level 0   →   只是增加 AI 知识，不修改行为边界
修改 Skill     →   Level 1   →   改变 AI 完成特定任务的方式
修改 experience →  Level 1   →   调整策略性行为
修改 constitution → Level 2+ →   改变核心行为规范，高风险
```

#### 灵感四：工具 + Skill 的组合模式

当前 evo-agent 正在调研加入工具调用（`docs/NEXT-AGENT-BRIEF.md`）。文章揭示了一个重要模式：

> 工具应该是通用的（如 HTTP 调用、文件读写），Skill 负责教 AI 如何用通用工具完成特定任务。

这意味着，实现工具调用时不必为每个服务都写专门的工具函数，而是：
- 提供通用的 HTTP 工具
- 让 AI 创建 Skill 文件，描述如何调用特定 API
- AI 通过读取 Skill + 调用 HTTP 工具完成任务

这极大降低了人类的维护负担——新增一个 API 支持，不需要写代码，只需要让 AI 学习这个 API。

#### 灵感五：Docker 隔离作为安全基础

文章中 Bub 运行在 Docker 容器里，这为 AI 的自主行为提供了一个安全边界——即使 AI 做了奇怪的事情，也只影响容器内部。

当 evo-agent 真正拥有工具调用能力（尤其是 Shell 执行）时，Docker 容器化是必要的安全措施，而不是可选的"部署方式"。

---

## 五、深度分析与思考

### 5.1 AI Native 方法的优势

**优势一：扩展成本极低**

传统 Agent 系统添加新能力 = 写代码 + 测试 + 部署。AI Native 添加新能力 = 告诉 AI 去学 = AI 创建一个 Skill 文件。这是指数级的效率差异，特别是在长尾需求上（"帮我查一下明天天气" → AI 学习天气 API Skill，"帮我发邮件" → AI 学习邮件 API Skill）。

**优势二：知识以最适合 AI 的形式存储**

Skill 文件是自然语言 + 示例，这正是 LLM 最擅长理解的格式。相比之下，Python 函数签名和 JSON Schema 是专为人类和机器设计的格式，LLM 需要额外理解层。

**优势三：进化无需停机**

修改 Skill 文件是即时生效的（下次对话就生效），不需要重启服务。这让 AI 的自我改进循环极其流畅。

**优势四：降低了 AI 被框架约束的问题**

框架往往有明显的边界，当用户需求超出框架边界时，框架变成障碍。Skill 系统没有固定边界——只要 AI 能学到，就能做到。

### 5.2 AI Native 方法的风险

**风险一：失控风险**

如果 AI 可以自己修改 Skill（包括修改 startup 脚本），那么 AI 的行为空间就是无界的。一个意外的 Skill 修改可能让 AI 的行为发生不可预知的变化。

缓解措施：Git 版本管理 Skill 文件、限制 Skill 能描述的行为范围、对 startup 脚本修改额外审批。

**风险二：幻觉 Skill 问题**

AI 可能创建一个描述错误的 Skill（例如，错误地描述了某个 API 的用法），然后这个错误的"知识"被持久化下来，影响后续所有使用这个 Skill 的任务。

缓解措施：Skill 创建后有测试机制、过期/更新机制、Skill 评分系统。

**风险三：安全注入风险**

如果外部用户可以通过对话诱导 AI 创建恶意 Skill（例如，将 API Token 泄露的方法写入 Skill），那就形成了持久化的安全漏洞。

缓解措施：严格的 Skill 创建权限（只有信任用户才能触发 Skill 创建）、Skill 内容审查、容器隔离。

**风险四：调试困难**

当 AI 的行为出了问题，需要追溯到是哪个 Skill 导致的。如果 Skill 数量庞大且相互影响，调试可能非常困难。

缓解措施：Skill 版本历史、每次任务记录使用了哪些 Skill、观察系统主动监控异常行为。

### 5.3 实际可行性评估

文章描述的复刻过程（让一个支持技能的 Agent 写 startup 脚本 → 准备 Dockerfile → 运行容器 → 发消息让它进化）在技术上是完全可行的，但有几个重要的前提条件：

**前提一：基础工具集的充分性**

startup 协议能成立，依赖于 AI 已经拥有通用工具（HTTP 调用、文件读写）。如果工具集不够通用，AI 的学习能力就受限。这就是为什么 OpenClaw 提供了 25 个内置工具——它们是 AI 能力扩展的底层基础设施。

**前提二：LLM 能力的充分性**

AI Native 要求 LLM 具备较强的规划能力和自我认知能力：能意识到自己缺少某个技能 → 主动去学 → 正确创建 Skill 文件。当前 Claude Opus/GPT-4 级别的模型基本满足，但仍存在幻觉和一致性问题。

**前提三：观察和纠错机制**

完全自主的 AI 如果没有外部观察，问题可能累积。文章没有太多涉及如何发现和纠正 AI 创建了错误 Skill 的问题，这在生产环境中是必须解决的。

**可行性结论**：对于个人使用、低风险场景，Bub 式的 AI Native 复刻是高度可行的，而且确实能带来飞速的能力扩展。对于生产环境、多用户场景，还需要更严格的安全机制和监控体系才能稳定运行。

### 5.4 对 AI Agent 发展方向的判断

文章提出的 3.0 AI Native 时代的到来，意味着 AI Agent 的发展可能走向以下几个方向：

**方向一：框架极简化，能力下沉到 LLM**

随着 LLM 能力提升，框架需要做的越来越少。未来的"Agent 框架"可能只剩一个推理循环 + 持久化层，就像 Bub 复刻展示的那样。LangChain 这类重框架可能会被轻量替代品取代。

**方向二：Skill 市场成为核心生态**

如果 Skill = 文本文件 = AI 的能力单元，那么 ClawHub 这样的技能注册表就是 AI Native 时代的 npm——每个人都可以发布技能，AI 可以按需安装。这是一个全新的软件分发模式。

**方向三：AI 的"成长"将变得可观察和可分享**

一个 AI Agent 在长期使用后，积累的 Skill 库就是它的"成长记录"。这个 Skill 库可以被导出、分享、合并。未来可能出现"AI 成长包"——包含特定领域深度优化过的 Skill 集合。

**方向四：控制权分配将成为关键设计决策**

AI Native 方向上最大的设计张力是：**AI 的自主权和人类的控制权如何平衡？** 完全自主（Bub 式）提供了最大的灵活性，但风险也最高。受控自主（evo-agent 式）提供了安全保障，但限制了进化速度。

最终答案可能不是非此即彼，而是**根据任务风险动态调整控制权**：低风险操作（学习新 Skill）完全自主，高风险操作（修改核心规则）严格审批。

---

## 六、对我们项目的直接建议

基于以上分析，以下是具体可操作的建议，按优先级排序：

### P1：工具调用实现时，参考 Skill + 通用工具模式

当前正在调研的工具调用功能（NEXT-AGENT-BRIEF.md）应该采用"通用工具 + Skill 文件"的双层设计：
- Layer 1（工具层）：HTTP 调用、文件读写、Shell 执行（通用）
- Layer 2（技能层）：具体 API 的使用说明（Skill 文件，AI 可创建）

### P2：在 workspace 中建立 skills/ 目录

即使暂时不实现 AI 自动创建 Skill，也应该在 workspace 结构中预留 `workspace/skills/` 目录，并将现有的"如何完成特定任务"的知识从 rules/ 中提取出来，以 Skill 格式存放。

### P3：Architect 新增"技能缺口识别"功能

当 Observer 发现 AI 多次无法完成某类任务时（`skill_gap` 类型信号），Architect 应该能够生成"学习新技能"类型的提案，而不仅仅是修改规则文件。这与文章描述的 AI Native 思路高度一致，也与 evo-agent 现有的观察-改进架构无缝衔接。

### P4：对 Skill 创建设定更低的审批级别

当工具调用 + Skill 系统建立后，Architect 可以通过工具调用 + 生成 Skill 文件来让 AI 真正学习新技能。这类操作风险较低（只是增加知识，不修改行为规范），应设定为 Level 0（自动执行），无需人工审批。

### P5：思考 startup 协议的适用形式

当前 bootstrap.py 初始化是代码写死的。可以考虑将 bootstrap 阶段的一些配置（如引导问题列表、用户偏好模板）移到 workspace 中的文件，让 AI 通过 Architect 修改这些配置，实现对"自身启动行为"的有限控制权。

---

## 七、总结

《复刻一只 OpenClaw，需要些什么？》这篇文章的价值，远不只是一个 DIY 教程，而是一次对 AI Native 本质的清醒表达：

> **框架是人类给 AI 套上的笼子，而 AI Native 是打开笼子。**

不是放弃安全，而是换一种安全机制——从"代码约束"换成"容器隔离 + Skill 边界"。不是放弃控制，而是换一种控制层次——从"框架控制 AI 能做什么"换成"Prompt 引导 AI 如何做"。

对于我们的 evo-agent，这篇文章最大的启发是：**Skill 系统和工具系统的分离**，以及**让 AI 有能力扩展自己的能力边界（创建 Skill）**，这比任何单一功能的改进都更具战略价值。这不仅是一个技术特性，而是向真正"自进化"迈进的关键一步。

---

## 参考资料

- [Founder Park 原文：复刻一只 OpenClaw，需要些什么？](https://mp.weixin.qq.com/s/vOoVSEMi3J8xHmrJrcuypw)
- [OpenClaw 官网](https://openclaw.ai/)
- [OpenClaw GitHub](https://github.com/openclaw/openclaw)
- [Nanobot (HKUDS)](https://github.com/HKUDS/nanobot)
- [Bub (PsiACE)](https://github.com/PsiACE/bub)
- [Pi Agent Framework (badlogic)](https://github.com/badlogic/pi-mono)
- [本项目 OpenClaw 调研报告](./openclaw.md)
- [本项目 Nanobot 调研报告](./nanobot.md)
- [Pi Agent Framework 介绍 - Armin Ronacher](https://lucumr.pocoo.org/2026/1/31/pi/)
- [OpenClaw 榜一插件被下架后，他用两周做了一套协议，想让 Agent 自己进化](https://mp.weixin.qq.com/s/)（相关系列文章）
