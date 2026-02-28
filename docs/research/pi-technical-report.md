# 调研报告: Pi 编码 Agent 框架技术深度解析

**日期**: 2026-02-25
**任务**: 分析 Pi 项目（https://github.com/badlogic/pi-mono）的源代码与工作原理，为 AI 自进化系统提供架构参考

---

## 调研摘要

Pi 是一个极简主义的终端编码 Agent 框架，其核心设计哲学是"提供可靠基础，而非规定工作流"。Pi 由两个独立层组成：底层的通用 LLM 流式 API（`@mariozechner/pi-ai`）和上层的 Agent 运行时（`@mariozechner/pi-agent-core`），最终由编码 Agent CLI（`@mariozechner/pi-coding-agent`）将所有能力整合。其"最小工具集 + 无限扩展"的模式，以及树形会话结构、渐进式 Skill 披露机制，对我们的 AI 自进化系统有直接参考价值。

---

## 一、项目概述

### 定位与目标

| 维度 | 描述 |
|------|------|
| 项目名称 | Pi Monorepo（pi-mono） |
| 作者 | Mario Zechner（badlogic） |
| 官网 | shittycodingagent.ai / pi.dev |
| 定位 | "极简终端编码 Harness，让你适应自己的工作流，而非反过来" |
| 核心口号 | 没有子 Agent、没有 Plan Mode、没有权限弹窗、没有 MCP —— 一切均可通过扩展实现 |

### 技术栈

- **语言**: TypeScript（全栈）
- **运行时**: Node.js
- **构建**: Biome（lint/format）+ tsc
- **测试**: Vitest
- **包管理**: npm workspaces（monorepo）
- **Schema 验证**: Typebox（运行时类型安全）
- **TUI**: 自研 `@mariozechner/pi-tui`（差分渲染终端 UI）

### 包结构

```
pi-mono/
├── packages/
│   ├── ai/              # 统一多 Provider LLM API
│   ├── agent/           # Agent 运行时核心（工具调用 + 状态管理）
│   ├── coding-agent/    # 编码 Agent CLI（主产品）
│   ├── tui/             # 自研终端 UI 库
│   ├── web-ui/          # Web 组件（AI 聊天界面）
│   ├── mom/             # Slack Bot 集成
│   └── pods/            # vLLM GPU 部署管理
```

---

## 二、架构分析

### 2.1 分层架构

```
┌─────────────────────────────────────────────────────┐
│          Interactive / Print / RPC / SDK            │ ← 运行模式层
│         (coding-agent CLI & modes/)                 │
├─────────────────────────────────────────────────────┤
│              AgentSession（会话管理层）               │ ← 会话状态层
│  compaction / session-manager / extension-runner   │
├─────────────────────────────────────────────────────┤
│           @mariozechner/pi-agent-core               │ ← Agent 运行时层
│          Agent class + agentLoop() function         │
├─────────────────────────────────────────────────────┤
│              @mariozechner/pi-ai                    │ ← LLM 抽象层
│   Provider Registry + streamSimple() + types       │
└─────────────────────────────────────────────────────┘
```

### 2.2 核心数据流

```
用户输入
  │
  ▼
AgentSession.prompt()
  │
  ├─ 展开 Prompt Template（/templatename）
  ├─ 解析 Extension Command（/command）
  ├─ 解析 Skill Block（/skill:name）
  │
  ▼
Agent._runLoop()
  │
  ├─ 构建 AgentContext（systemPrompt + messages + tools）
  ├─ 创建 AbortController
  │
  ▼
agentLoop() ← 核心循环函数
  │
  ├─[外层循环] 处理 follow-up 队列消息
  │
  └─[内层循环] 处理 tool calls + steering 消息
      │
      ├─ streamAssistantResponse()
      │   ├─ transformContext()（压缩/剪枝）
      │   ├─ convertToLlm()（AgentMessage → Message）
      │   └─ streamSimple()→ Provider API
      │
      ├─ (无 tool call) → 检查 follow-up → 退出
      │
      └─ executeToolCalls()
          ├─ 并行执行（顺序执行，检查 steering 中断）
          ├─ validateToolArguments()
          ├─ tool.execute(toolCallId, args, signal, onUpdate)
          └─ 收集 ToolResultMessage[]
```

### 2.3 关键文件索引

| 文件 | 职责 |
|------|------|
| `packages/agent/src/agent-loop.ts` | Agent 核心循环，双层 while 结构 |
| `packages/agent/src/agent.ts` | Agent 类，状态管理 + 事件订阅 |
| `packages/agent/src/types.ts` | 核心类型定义（AgentMessage、AgentEvent 等） |
| `packages/ai/src/stream.ts` | streamSimple 入口，Provider 路由 |
| `packages/ai/src/api-registry.ts` | Provider 注册表（插件化 Provider） |
| `packages/ai/src/types.ts` | LLM 核心类型（Message、Tool、Model 等） |
| `packages/coding-agent/src/core/agent-session.ts` | AgentSession，整合所有能力 |
| `packages/coding-agent/src/core/system-prompt.ts` | 系统提示词构建 |
| `packages/coding-agent/src/core/skills.ts` | Skill 加载与格式化 |
| `packages/coding-agent/src/core/extensions/types.ts` | Extension API 类型定义 |
| `packages/coding-agent/src/core/compaction/` | 上下文压缩机制 |
| `packages/coding-agent/src/core/session-manager.ts` | 会话树形存储 |

---

## 三、工作原理深度解析

### 3.1 Agent Loop 详解

Agent Loop 是整个系统的核心，设计为**双层循环结构**：

```typescript
// 外层循环：处理 follow-up 消息（用户在 Agent 完成后排队的消息）
while (true) {
  // 内层循环：处理 tool calls 和 steering（中途打断）消息
  while (hasMoreToolCalls || pendingMessages.length > 0) {
    // 1. 注入 pending steering 消息
    // 2. 调用 LLM 获取 assistant 响应（流式）
    // 3. 检查是否有 tool calls
    // 4. 执行 tool calls（顺序执行，每次检查 steering 中断）
    // 5. 收集 ToolResultMessage，注入到 context
  }
  // 检查 follow-up 队列，若有则继续外层循环
}
```

**关键设计点：**
- **Steering 消息**：用户可在 Agent 执行工具期间发送"转向"消息，Agent 完成当前工具后立即注入，剩余工具被跳过（标记为 `Skipped due to queued user message`）
- **Follow-up 消息**：等待 Agent 完全停止后才注入，用于排队下一个任务
- **两种排队模式**：`one-at-a-time`（默认，逐个处理）和 `all`（一次性全部注入）

### 3.2 消息系统架构

Pi 使用三层消息类型系统：

```
LLM 消息（@pi-ai）：UserMessage | AssistantMessage | ToolResultMessage
    ↓ 扩展（@pi-agent-core）
AgentMessage = Message | CustomAgentMessages[keyof]
    ↓ 扩展（@pi-coding-agent）
完整 AgentMessage = UserMessage | AssistantMessage | ToolResultMessage
                  | BashExecutionMessage | CustomMessage
                  | BranchSummaryMessage | CompactionSummaryMessage
```

**核心设计**：`AgentMessage` 通过 TypeScript 声明合并（declaration merging）扩展，框架代码不需要知道具体的自定义消息类型。过滤器 `convertToLlm()` 负责在发给 LLM 前将 AgentMessage 转为标准 Message。

### 3.3 工具系统

默认内置工具集极其简洁（体现最小化哲学）：

| 工具 | 功能 |
|------|------|
| `read` | 读取文件（支持 offset/limit 分页，支持图片） |
| `write` | 创建/覆盖文件 |
| `edit` | 外科式精确编辑（老文本精确匹配后替换） |
| `bash` | 执行 bash 命令（流式输出，自动截断，尾部保留） |
| `grep` | 文件内容搜索（尊重 .gitignore） |
| `find` | 文件名模式匹配（尊重 .gitignore） |
| `ls` | 列出目录内容 |

**CLI 默认只加载 4 个工具**：`read, bash, edit, write`

工具实现的关键细节：
- **可插拔 Operations**：`bash` 和 `read` 工具的底层操作可被替换，支持 SSH 远程执行、沙箱环境等
- **SpawnHook**：`bash` 工具支持拦截和修改命令的 command/cwd/env
- **流式更新**：工具执行过程中通过 `onUpdate` 回调实时推送部分结果到 TUI

### 3.4 Skill 机制

Skill 是一种**渐进式披露**的能力扩展机制：

1. **启动时**：扫描所有 Skill 目录，只提取 `name` 和 `description`，以 XML 格式注入系统提示词
2. **匹配时**：LLM 自主判断当前任务是否匹配某 Skill，若匹配则用 `read` 工具读取完整 `SKILL.md`
3. **执行时**：按 SKILL.md 中的指令操作，相对路径解析为 Skill 目录的绝对路径

```xml
<!-- 注入系统提示词的 Skill 格式 -->
<available_skills>
  <skill>
    <name>brave-search</name>
    <description>Web search via Brave API. Use for searching docs, facts...</description>
    <location>/home/user/.pi/agent/skills/brave-search/SKILL.md</location>
  </skill>
</available_skills>
```

**Skill 遵循 agentskills.io 标准**，可跨 Agent 框架复用（Claude Code、Codex 的 Skill 均可被 Pi 加载）。

### 3.5 Extension 机制

Extension 是 Pi 最强大的扩展点，完整的 TypeScript API 覆盖：

```typescript
export default function (pi: ExtensionAPI) {
  // 注册自定义工具（LLM 可调用）
  pi.registerTool({ name: "deploy", description: "...", parameters: ..., execute: ... });

  // 注册斜杠命令
  pi.registerCommand("stats", { handler: async (args, ctx) => { ... } });

  // 订阅 Agent 生命周期事件
  pi.on("tool_call", async (event, ctx) => { ... });
  pi.on("session_before_compact", async (event) => { /* 自定义压缩逻辑 */ });

  // 用户交互 UI
  ctx.ui.confirm("确认删除？");
  ctx.ui.select("选择模型", options);
  ctx.ui.notify("操作完成");

  // 会话持久化
  pi.appendEntry("my-extension", { count: 42 });
}
```

**Extension 可实现的能力**（均有官方示例）：
- Plan Mode（只读探索 → 批准执行）
- Permission Gate（危险命令确认）
- Git Checkpoint（每次 turn 自动暂存）
- Custom Compaction（接管压缩逻辑）
- Sub-Agent 编排（spawning pi instances）
- SSH/沙箱执行（替换 bash operations）
- MCP 服务器集成
- 甚至 Doom 游戏（等待时可玩）

### 3.6 会话系统（树形 JSONL）

Pi 的会话存储设计非常独特：

**文件格式**：JSONL（JSON Lines），每行一个 `SessionEntry`
**结构**：树形（每个 entry 有 `id` + `parentId`），单文件内支持无限分支

```
[user msg] ── [assistant] ── [user msg] ── [assistant] ─┬─ [user msg] ← 当前叶节点
                                                         │
                                                         └─ [branch_summary] ── [user msg] ← 另一分支
```

**Entry 类型**：
- `message`：对话消息
- `compaction`：压缩摘要（含 `firstKeptEntryId`，指示从哪里开始保留原始消息）
- `branch_summary`：切换分支时生成的摘要
- `custom`：Extension 的持久化状态（不发给 LLM）
- `custom_message`：Extension 注入的消息（发给 LLM）
- `label`：用户书签
- `model_change` / `thinking_level_change`：设置变更记录

### 3.7 上下文压缩机制

**自动压缩触发条件**：
```
contextTokens > contextWindow - reserveTokens（默认 16384）
```

**压缩流程**：
1. 从最新消息往前扫，保留 `keepRecentTokens`（默认 20000）
2. 将被截掉的历史消息发给 LLM，生成结构化摘要
3. 在 JSONL 文件追加 `CompactionEntry`（包含摘要 + `firstKeptEntryId`）
4. 重新加载会话：LLM 看到 `[摘要] + [从 firstKeptEntryId 开始的原始消息]`

**摘要结构**（固定格式）：
```markdown
## Goal / ## Constraints & Preferences / ## Progress (Done/In Progress/Blocked)
## Key Decisions / ## Next Steps / ## Critical Context
<read-files>...</read-files>
<modified-files>...</modified-files>
```

**Extension 可完全接管压缩**：通过 `session_before_compact` 事件，可返回自定义摘要或取消压缩。

### 3.8 多 Provider LLM 抽象层

`@mariozechner/pi-ai` 提供统一的 LLM 接口：

```
Provider 注册表（api-registry.ts）
├── "anthropic-messages" → anthropic.ts（支持 Claude/GitHub Copilot Anthropic）
├── "openai-completions" → openai-completions.ts
├── "openai-responses" → openai-responses.ts
├── "google-generative-ai" → google.ts
├── "bedrock-converse-stream" → amazon-bedrock.ts
└── ... 15+ providers
```

**统一接口**：
```typescript
streamSimple(model: Model, context: Context, options?: SimpleStreamOptions): AssistantMessageEventStream
```

**关键设计**：Provider 可在运行时动态注册（`registerApiProvider()`），Extension 可注册自定义 Provider（支持 OAuth 流程、自定义 HTTP Headers 等）。

**"隐身模式"**（Stealth Mode）：Pi 刻意在 Anthropic provider 中模拟 Claude Code 2.1.2 的工具命名（`Read`、`Write`、`Edit`、`Bash` 等 Pascal Case），以触发 Anthropic 对 Claude Code 用户的特殊 prompt caching 优惠。

---

## 四、设计亮点与创新点

### 4.1 最小工具集哲学

Pi 默认只给模型 4 个工具（read/write/edit/bash），其核心理由：
- **减少模型混淆**：工具越少，模型选错工具的概率越低
- **bash 是万能的**：任何缺失工具都可用 bash 替代
- **按需扩展**：通过 Extension 或 `--tools` 添加，不强制所有人承担所有工具的 context 开销

博文原话："No built-in to-dos. They confuse models. Use a TODO.md file, or build your own with extensions."

### 4.2 Steering/Follow-up 双队列设计

这是工程实现上的亮点：用户不必等 Agent 完成才能发下一条消息。
- **Steering**：打断式插入，当前工具完成后立即注入，跳过剩余工具
- **Follow-up**：等待式排队，Agent 完全停止后再发送

这解决了长时间运行 Agent 的交互性问题，无需轮询或复杂的并发控制。

### 4.3 单文件树形会话

业界通常将分支存为多个文件，Pi 将所有分支存在**同一个 JSONL 文件**中，通过 `id`/`parentId` 形成树。好处：
- 一个文件包含完整历史，备份方便
- `/tree` 命令可在单个会话内任意回溯和切换分支
- 压缩（Compaction）也记录在树中，与原始历史并存

### 4.4 渐进式 Skill 披露

只将 Skill 的名称和描述放入上下文，完整内容由 LLM 自主决定是否读取。这大幅节省 token，同时保持能力的可发现性。与 MCP 的区别：Skill 是静态 Markdown 文件，不需要运行时进程，安全性更高。

### 4.5 可插拔 Operations 设计

工具（bash、read）的底层 IO 操作通过接口抽象（`BashOperations`、`ReadOperations`），可被替换为 SSH 操作、Docker 容器操作等，无需 Fork Pi 本身。这是扩展点设计的典范。

### 4.6 Extension 系统的"无 MCP"立场

Pi 明确拒绝 MCP，其理由（博文 [Why?](https://mariozechner.at/posts/2025-11-02-what-if-you-dont-need-mcp/)）：
- MCP 需要运行外部进程，增加复杂度
- 任何 MCP 工具都可以写成一个 CLI 脚本 + Skill，更简单、更可移植
- 如果真的需要 MCP，写一个 Extension 加载 MCP Server 即可

---

## 五、与其他 Agent 框架的对比

| 维度 | Pi | Claude Code | LangChain/LangGraph | AutoGen |
|------|----|----|-----|-----|
| 工具集 | 4 个默认，自由扩展 | 18+ 内置工具 | 按需组装 | 按需组装 |
| Sub-Agent | 无内置，Extension 实现 | 无内置（Task 工具） | 原生支持 | 原生支持 |
| Plan Mode | 无内置，Extension 实现 | 无内置 | 无 | 有 |
| 会话存储 | 树形 JSONL（单文件） | 多文件/内存 | 内存/自定义 | 内存 |
| 上下文压缩 | 内置自动 + 可自定义 | 内置 | 无 | 无 |
| Provider | 15+ 提供商 | Anthropic 主 | 200+ | OpenAI 主 |
| 扩展机制 | TypeScript Extension（全能） | CLAUDE.md + Skill | 链式组装 | Agent 组合 |
| Skill 系统 | 符合 agentskills.io 标准 | CLAUDE.md | 无 | 无 |
| MCP | 不内置（Extension 可加） | 内置 | 有 | 有 |
| 安装 | npm install -g | brew/npm | pip | pip |

---

## 六、对 AI 自进化系统的启发

### 6.1 Agent Loop 设计参考

Pi 的双层循环结构（steering + follow-up 双队列）直接可以借鉴：

**当前系统问题**：`core/agent_loop.py` 是线性的，用户无法在 Agent 运行中打断。

**建议**：
- 引入 steering 队列：允许在工具执行完毕后注入打断消息
- 引入 follow-up 队列：支持批量排队任务，实现"fire and forget"
- 将 `getSteeringMessages` 和 `getFollowUpMessages` 设计为可注入的回调

### 6.2 工具系统重新审视

Pi 的最小化工具集哲学很值得反思。对于自进化系统：

- 核心工具只需：`read`、`bash`、`write/edit`
- 元学习工具（反思、规则更新）通过 Skill 机制提供，而非硬编码
- 观察器（Observer）应作为 Extension 实现，而非核心模块

### 6.3 会话存储参考 JSONL 树形结构

我们当前用单文件 JSONL 记录对话，但没有分支支持。

**建议**：
- 引入 `id`/`parentId` 结构
- 支持会话分支（实验不同进化路径）
- 将 Compaction Entry 记录在会话树中，保留完整历史

### 6.4 Skill 机制是我们现在 Rules 系统的升级版

我们的 `workspace/rules/` 目录相当于一个早期的 Skill 系统，但没有：
- 渐进式披露（全量注入上下文）
- 标准化格式（没有 frontmatter）
- 自动发现机制

**建议**：将现有规则文件迁移到符合 agentskills.io 标准的 Skill 格式，只在系统提示中放描述，按需加载完整内容。

### 6.5 压缩机制应该是可拦截的

Pi 的 `session_before_compact` 事件允许 Extension 完全接管压缩逻辑。对于自进化系统，压缩时是提取"经验"的最佳时机：

```python
# 压缩时可以：
# 1. 提取新发现的 error patterns
# 2. 更新 rules/experience/error_patterns.md
# 3. 生成高质量摘要而非使用默认摘要
```

### 6.6 Extension 模式 vs 我们的 Observer 模式

Pi 的 Extension 监听事件（`tool_call`、`turn_end`、`agent_end`），这与我们的 Observer 设计思路相同。区别在于：

- Pi：Extension 可以**拦截**工具调用（返回修改后的参数或直接返回结果）
- 我们：Observer 目前是**只读**的

**建议**：为 Observer 添加拦截能力，允许在工具执行前后注入逻辑。

### 6.7 SDK 化的程序化接口

Pi 提供完整的 SDK（`createAgentSession`），可以在程序中直接操作 Agent：

```typescript
const { session } = await createAgentSession({ ... });
session.subscribe(event => { /* 监听所有事件 */ });
await session.prompt("...");
```

对应我们的系统，`AgentLoop` 应该被封装成类似的 API，让上层的进化机制可以程序化控制 Agent 行为。

### 6.8 "不规定工作流"原则

Pi 的 Philosophy："Pi is aggressively extensible so it doesn't have to dictate your workflow."

这对我们的自进化系统有深刻启示：**不要把进化策略硬编码进框架核心**。进化策略（何时反思、如何更新规则、是否需要 Plan Mode）应通过 Skill/Extension 机制来定义，框架只提供可靠的执行基础。

---

## 七、实施建议

### 关键步骤

1. **引入树形会话存储**：在现有 JSONL 基础上添加 `id`/`parentId` 字段，支持分支实验
2. **重构工具为可拦截接口**：将工具的底层操作提取为可替换的 Operations 接口
3. **Steering 队列**：在 `agent_loop.py` 中引入 steering 消息机制，支持运行时打断
4. **Skill 标准化**：将 `workspace/rules/` 重构为 agentskills.io 标准的 Skill 格式
5. **压缩事件钩子**：在压缩时触发经验提取逻辑

### 风险点

- **树形会话迁移** - 需要迁移现有会话格式，建议双写过渡 - 缓解：提供自动迁移脚本
- **Skill 格式迁移** - 现有规则文件需要添加 frontmatter - 缓解：批量脚本处理
- **Steering 机制的并发安全** - Python asyncio 需要仔细处理队列 - 缓解：参考 Pi 的 TypeScript 实现，用 asyncio.Queue

### 依赖项

- 无额外外部依赖
- Pi 的 agentskills.io 标准是开放标准，可直接遵循

---

## 八、参考资料

- [Pi Monorepo GitHub](https://github.com/badlogic/pi-mono)
- [Pi 博客文章（核心哲学）](https://mariozechner.at/posts/2025-11-30-pi-coding-agent/)
- [为什么不用 MCP](https://mariozechner.at/posts/2025-11-02-what-if-you-dont-need-mcp/)
- [agentskills.io 标准](https://agentskills.io/specification)
- [pi-agent-core README](https://github.com/badlogic/pi-mono/tree/main/packages/agent)
- [pi-ai README](https://github.com/badlogic/pi-mono/tree/main/packages/ai)
- [Extensions 文档](https://github.com/badlogic/pi-mono/tree/main/packages/coding-agent/docs/extensions.md)
- [Skills 文档](https://github.com/badlogic/pi-mono/tree/main/packages/coding-agent/docs/skills.md)
- [Session 格式文档](https://github.com/badlogic/pi-mono/tree/main/packages/coding-agent/docs/session.md)
- [Compaction 文档](https://github.com/badlogic/pi-mono/tree/main/packages/coding-agent/docs/compaction.md)
- [SDK 文档](https://github.com/badlogic/pi-mono/tree/main/packages/coding-agent/docs/sdk.md)
