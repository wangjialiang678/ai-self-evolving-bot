# OpenClaw 源码深度分析合集

> 本文档合并了 OpenClaw 项目的三份深度源码分析报告。

## 目录
- [Part 1: Agent Loop (Pi Embedded Runner)](#part-1-agent-loop)
- [Part 2: 工具系统](#part-2-工具系统)
- [Part 3: Telegram 集成与配置系统](#part-3-telegram-集成与配置系统)

---

# Part 1: Agent Loop (Pi Embedded Runner)

**日期**: 2026-02-25
**来源**: `/tmp/openclaw/src/agents/`

---

## 调研摘要

OpenClaw 的 Agent Loop 是一个以 `@mariozechner/pi-coding-agent`（Pi SDK）为底层的多层封装体系。核心入口是 `runEmbeddedPiAgent`（`run.ts`），它管理重试循环、鉴权轮换、Compaction；单次执行由 `runEmbeddedAttempt`（`run/attempt.ts`）完成，负责会话初始化、工具注册、事件订阅、超时控制，最终将 prompt 提交给 `session.prompt()`。工具调用循环完全由 Pi SDK 内部处理（`pi-coding-agent`），OpenClaw 通过事件订阅（`subscribeEmbeddedPiSession`）观测结果，不显式控制 tool_use → tool_result 的循环。

---

## 完整执行流程

### 1. 入口：`runEmbeddedPiAgent` (run.ts, line 192)

```
runEmbeddedPiAgent(params)
├── 队列化到 sessionLane + globalLane（串行化，防并发）
├── 解析 workspace 路径、模型、Provider
├── 鉴权：resolveModel() + 多 AuthProfile 候选列表
├── 确定最大迭代次数 MAX_RUN_LOOP_ITERATIONS（最少32，最多160）
└── while(true) 主重试循环
    ├── runEmbeddedAttempt() —— 实际执行一次
    ├── 分析结果：context overflow? auth error? rate limit? thinking error?
    ├── 若 context overflow → compactEmbeddedPiSessionDirect() 后 continue
    ├── 若 auth/rate limit → advanceAuthProfile() 轮换到下一个 profile 后 continue
    ├── 若 thinking level unsupported → fallback to lower level 后 continue
    └── 否则返回最终 EmbeddedPiRunResult
```

### 2. 单次执行：`runEmbeddedAttempt` (run/attempt.ts, line 306)

```
runEmbeddedAttempt(params)
├── 创建 AbortController（用于超时中断）
├── 解析 sandbox / effectiveWorkspace
├── 加载 Skills（SKILL.md 环境变量注入）
├── 加载 bootstrap 上下文文件（CLAUDE.md 等）
├── 注册工具：createOpenClawCodingTools() → sanitizeToolsForGoogle()
├── 构建 System Prompt：buildEmbeddedSystemPrompt()
├── 获取会话锁：acquireSessionWriteLock()
├── 打开 SessionManager（JSONL 文件）
├── createAgentSession()（Pi SDK）
│   ├── 注入 builtInTools（SDK 内置工具）
│   └── 注入 customTools（OpenClaw 工具定义）
├── applySystemPromptOverrideToSession()：session.agent.setSystemPrompt()
├── 包装 streamFn：
│   ├── dropThinkingBlocks（Copilot 等不支持 thinking blocks 的 provider）
│   ├── sanitizeToolCallIds（Mistral 等格式约束）
│   ├── cacheTrace（调试追踪）
│   └── anthropicPayloadLogger（payload 日志）
├── 历史消息清理：sanitizeSessionHistory() → limitHistoryTurns()
│   ├── 修复 tool_use/tool_result 配对
│   ├── 校验 Gemini / Anthropic 轮次顺序
│   └── 超出历史上限截断（DM 会话单独限制）
├── 事件订阅：subscribeEmbeddedPiSession()
├── 设置超时定时器 setTimeout(abortRun, timeoutMs)
├── 注册 AbortSignal 监听（外部取消）
├── 构建 prompt 钩子（before_prompt_build / before_agent_start）
├── 修复孤立的 user message（防止连续 user 轮）
├── 检测并注入图片（detectAndLoadPromptImages）
├── 提交 prompt：await abortable(activeSession.prompt(effectivePrompt))
│   └── ← Pi SDK 内部处理整个 tool call 循环
├── 等待 compaction 完成：await abortable(waitForCompactionRetry())
├── 执行后清理（cache-ttl 时间戳记录）
└── 返回 EmbeddedRunAttemptResult
```

---

## 工具调用循环实现

### OpenClaw 侧（"黑盒"模式）

**OpenClaw 本身不控制工具调用循环**。整个 tool_use → execute → tool_result → next LLM call 的循环由 `@mariozechner/pi-coding-agent` 的 `AgentSession` 内部处理。

OpenClaw 只通过**事件订阅**观测工具调用过程：

```typescript
// run/attempt.ts line 920
const subscription = subscribeEmbeddedPiSession({
  session: activeSession,
  ...
});
```

订阅的事件类型（`pi-embedded-subscribe.handlers.ts`）：
- `message_start` / `message_update` / `message_end` — assistant 消息流
- `tool_execution_start` / `tool_execution_update` / `tool_execution_end` — 工具执行
- `agent_start` / `agent_end` — 整体 agent 生命周期
- `auto_compaction_start` / `auto_compaction_end` — SDK 内部自动 compaction

### 工具注册方式

工具被分为两类（`tool-split.ts`）：
1. **builtInTools**：Pi SDK 可原生执行的工具
2. **customTools**：OpenClaw 扩展工具，以 `clientToolDefs` 形式注册

```typescript
// run/attempt.ts line 660-699
const { builtInTools, customTools } = splitSdkTools({ tools, sandboxEnabled });
const { session } = await createAgentSession({
  tools: builtInTools,
  customTools: allCustomTools,  // [customTools + clientToolDefs]
  ...
});
```

### 工具执行结果处理（subscribe.handlers.tools.ts）

```
tool_execution_start → 记录 toolName、args、开始时间；发出 typing 指示器
tool_execution_end   → 提取 tool result
                     → 判断是否为 messaging tool（sendMessage 等）
                     → 更新 toolMetas / lastToolError
                     → 触发 after_tool_call 插件钩子（fire-and-forget）
```

---

## 多轮工具调用的消息格式

消息格式由 Pi SDK（`@mariozechner/pi-coding-agent`）管理，存储在 JSONL session 文件中。OpenClaw 通过 `SessionManager` 读写。

**消息角色类型**（从代码推断）：
- `user` — 用户消息
- `assistant` — 助手消息（包含 text + tool_use blocks）
- `toolResult` — 工具结果（对应 assistant 中的 tool_use）

**历史清理逻辑**（run/attempt.ts, line 826-858）：
```typescript
const prior = await sanitizeSessionHistory({ messages, ... });
const validated = validateAnthropicTurns(validateGeminiTurns(prior));
const truncated = limitHistoryTurns(validated, dmHistoryLimit);
const limited = sanitizeToolUseResultPairing(truncated);
activeSession.agent.replaceMessages(limited);
```

**tool_use / tool_result 修复**：`sanitizeToolUseResultPairing()` 检测并修复孤立的配对（如截断导致的 tool_use 无对应 tool_result）。

---

## LLM 调用方式

### streamFn 抽象

LLM 调用通过 `agent.streamFn` 抽象，默认为 `streamSimple`（来自 `@mariozechner/pi-ai`）：

```typescript
// run/attempt.ts line 748-750
activeSession.agent.streamFn = streamSimple;  // 标准 provider

// Ollama 特殊处理（line 746）
activeSession.agent.streamFn = createOllamaStreamFn(ollamaBaseUrl);
```

### streamFn 包装链

每个 streamFn 包装器都是**洋葱模型**，依次叠加：

```
原始 streamSimple
  → dropThinkingBlocks（按需，Copilot 等）
  → sanitizeToolCallIds（按需，Mistral 等）
  → cacheTrace.wrapStreamFn（调试）
  → anthropicPayloadLogger.wrapStreamFn（日志）
```

### Extra Params（applyExtraParamsToAgent）

```typescript
applyExtraParamsToAgent(
  activeSession.agent,
  config,       // OpenClaw 配置
  provider,     // "anthropic" | "openai" | ...
  modelId,      // "claude-opus-4-6"
  streamParams, // 用户自定义参数（temperature 等）
  thinkLevel,   // "off" | "minimal" | "low" | "medium" | "high" | "xhigh"
  agentId,
);
```

### Tools 传递

工具参数由 Pi SDK 在构建 API 请求时自动注入。OpenClaw 仅负责将工具定义传入 `createAgentSession()`，SDK 负责将其转换为各 provider 的 tools/functions 格式（Anthropic/OpenAI/Google 不同格式）。

---

## 超时和迭代限制

### 迭代上限（run.ts）

```typescript
const BASE_RUN_RETRY_ITERATIONS = 24;
const RUN_RETRY_ITERATIONS_PER_PROFILE = 8;
const MIN_RUN_RETRY_ITERATIONS = 32;
const MAX_RUN_RETRY_ITERATIONS = 160;

// 公式：min(160, max(32, 24 + profileCount * 8))
// 例：1个profile → max(32, 24+8) = 32
// 例：10个profiles → min(160, 24+80) = 104
```

### 执行超时（run/attempt.ts）

```typescript
// 外部 timeout（由调用方 params.timeoutMs 决定）
const abortTimer = setTimeout(() => {
  abortRun(true);  // 设置 timedOut=true，中断 session
}, Math.max(1, params.timeoutMs));
```

超时触发时：
1. `runAbortController.abort()` → 中断 `abortable()` 包装的 Promise
2. `activeSession.abort()` → 通知 Pi SDK 停止流
3. 若 compaction 正在进行 → 标记 `timedOutDuringCompaction=true`

### Compaction 超时

```typescript
// compaction-safety-timeout.ts
export const EMBEDDED_COMPACTION_TIMEOUT_MS = 300_000; // 5分钟
```

Compaction 有独立的 5 分钟安全超时，防止 LLM 生成摘要时卡住。

### Overflow Compaction 上限

```typescript
const MAX_OVERFLOW_COMPACTION_ATTEMPTS = 3;
```

context overflow 触发的自动 compaction，最多尝试 3 次。

---

## Compaction 触发条件和执行方式

### 两种 Compaction 路径

**路径 1：Pi SDK 自动 Compaction（in-attempt）**

由 Pi SDK 内部检测 context 接近上限时自动触发。OpenClaw 通过 `auto_compaction_start` / `auto_compaction_end` 事件感知：

```typescript
// pi-embedded-subscribe.handlers.compaction.ts
handleAutoCompactionStart(ctx):
  ctx.state.compactionInFlight = true;
  ctx.ensureCompactionPromise();

handleAutoCompactionEnd(ctx, evt):
  ctx.state.compactionInFlight = false;
  if (evt.willRetry) {
    ctx.noteCompactionRetry();       // 累计 pending 计数
    ctx.resetForCompactionRetry();   // 清空 assistantTexts / toolMetas
  } else {
    ctx.maybeResolveCompactionWait();
  }
```

`run/attempt.ts` 在 prompt 完成后等待 compaction 结束：
```typescript
await abortable(waitForCompactionRetry());  // line 1203
```

**路径 2：Overflow Compaction（run.ts 外部触发）**

当 `runEmbeddedAttempt` 返回后检测到 context overflow 错误时：

```typescript
// run.ts line 730
const compactResult = await compactEmbeddedPiSessionDirect({
  trigger: "overflow",
  ...
});
if (compactResult.compacted) {
  continue;  // 重试 prompt
}
```

**Compaction 执行核心**（compact.ts, line 664）：
```typescript
const result = await compactWithSafetyTimeout(() =>
  session.compact(params.customInstructions)
);
```
— `session.compact()` 是 Pi SDK 提供的方法，发起一次 LLM 调用生成摘要，替换历史消息。

### 触发顺序（Overflow 时）

1. SDK 自动 compaction（in-attempt）失败或不足 → 返回
2. 外层检测 `isLikelyContextOverflowError(assistantErrorText)` → 触发 overflow compaction
3. 若 compaction 成功 → `continue` 重试
4. 若失败或工具结果过大 → 尝试 `truncateOversizedToolResultsInSession()`
5. 若全部失败 → 返回 context_overflow 错误给用户

---

## System Prompt 组装逻辑

### 组装入口（run/attempt.ts, line 530）

```typescript
const appendPrompt = buildEmbeddedSystemPrompt({
  workspaceDir,
  defaultThinkLevel,
  reasoningLevel,
  extraSystemPrompt,      // 用户自定义追加
  ownerNumbers,           // 授权发送者 ID
  reasoningTagHint,       // 是否为 reasoning tag provider
  heartbeatPrompt,        // 心跳提示（主 agent 专属）
  skillsPrompt,           // 工作区 Skills 摘要
  docsPath,               // 文档路径
  runtimeInfo: { host, os, arch, node, model, shell, channel },
  sandboxInfo,            // sandbox 状态
  tools,                  // 工具列表（用于生成工具摘要）
  contextFiles,           // 注入的上下文文件（CLAUDE.md 等）
  promptMode,             // "full" | "minimal"（subagent 用 minimal）
  ...
});
```

### Prompt 模式

- **full**：主 agent 完整 system prompt，包含所有章节
- **minimal**：subagent 精简模式，只保留 Tooling / Workspace / Runtime 章节

### 章节组成（buildAgentSystemPrompt, system-prompt.ts）

```
系统提示结构：
1. Identity 行（OpenClaw agent 身份声明）
2. ## Current Date & Time（时区信息）
3. ## Authorized Senders（owner 号码，hash 或明文）
4. ## Skills (mandatory)（工作区技能索引）
5. ## Memory Recall（memory 工具提示）
6. ## Tooling（工具名称 + 摘要列表）
7. ## Workspace（工作区路径 + 注释）
8. ## Runtime（主机/OS/模型/shell/channel 信息）
9. ## Messaging（消息工具使用指南）
10. ## Voice (TTS)（语音提示，如有）
11. ## Reply Tags（消息引用标签语法）
12. ## Documentation（文档路径 + 链接）
13. [extraSystemPrompt]（用户追加内容）
14. [contextFiles]（CLAUDE.md 等文件内容内联）
```

### 应用到 Session

```typescript
applySystemPromptOverrideToSession(session, systemPromptText);
// → session.agent.setSystemPrompt(prompt)
// → session._baseSystemPrompt = prompt  （阻止 Pi SDK 重写）
// → session._rebuildSystemPrompt = () => prompt
```

---

## 关键数据结构

### EmbeddedRunAttemptResult

```typescript
{
  aborted: boolean;
  timedOut: boolean;
  timedOutDuringCompaction: boolean;
  promptError: unknown;
  sessionIdUsed: string;
  systemPromptReport: SessionSystemPromptReport;
  messagesSnapshot: AgentMessage[];    // 执行后的消息快照
  assistantTexts: string[];            // 收集的助手回复文本
  toolMetas: { toolName: string; meta?: string }[];
  lastAssistant: AgentMessage | undefined;
  lastToolError: LastToolError | undefined;
  didSendViaMessagingTool: boolean;
  attemptUsage: UsageLike | undefined; // token 用量
  compactionCount: number;
  clientToolCall?: { name: string; params: Record<string, unknown> };
}
```

### EmbeddedPiRunResult（最终返回）

```typescript
{
  payloads?: Array<{ text?, mediaUrl?, mediaUrls?, isError? }>;
  meta: {
    durationMs: number;
    agentMeta: { sessionId, provider, model, usage, lastCallUsage, promptTokens };
    aborted?: boolean;
    error?: { kind, message };
    stopReason?: string;             // "tool_calls" 表示 client tool
    pendingToolCalls?: Array<...>;   // 待 client 执行的工具
  };
  didSendViaMessagingTool?: boolean;
  successfulCronAdds?: number;
}
```

---

## Token 用量计算

```typescript
// UsageAccumulator 跨 tool-call 轮次累计
const usageAccumulator = createUsageAccumulator();

// 但上下文大小显示用"最后一次 API 调用"的值，避免累计导致虚高
const lastCallUsage = normalizeUsage(lastAssistant?.usage);
// 因为每次 tool-call round-trip 都会 report cacheRead ≈ 当前 context 大小
// 累计多次会使 context 显示为 N × context_size，超过 contextWindow 被截断
```

---

## 并发控制（Lane 队列）

```typescript
// 两级队列，防止同一 session 并发
return enqueueSession(() =>      // session 级别串行
  enqueueGlobal(async () => {   // 全局级别串行
    ...
  })
);
```

- `sessionLane`：按 sessionKey/sessionId 区分，同一 session 串行
- `globalLane`：全局资源（如 auth profile 切换）串行

---

## 事件流（pi-embedded-subscribe.ts）

```
session.subscribe(handler)
  ↓ 事件到达
createEmbeddedPiSessionEventHandler(ctx)
  ↓ 分发
message_start    → handleMessageStart  （重置 buffer、记录状态）
message_update   → handleMessageUpdate （streaming delta，处理 thinking/final 标签）
message_end      → handleMessageEnd    （finalize 文本，触发 onBlockReply）
tool_exec_start  → handleToolExecutionStart（记录开始时间，发送 typing 指示）
tool_exec_update → handleToolExecutionUpdate（实时进度）
tool_exec_end    → handleToolExecutionEnd  （收集结果，触发 onToolResult，记录 meta）
auto_compact_start → handleAutoCompactionStart（标记 compaction 进行中）
auto_compact_end   → handleAutoCompactionEnd（注意 willRetry 标志）
agent_end        → handleAgentEnd（flush buffer，触发 lifecycle 事件）
```

---

## 关键依赖关系

```
OpenClaw 代码
  └── @mariozechner/pi-coding-agent
        ├── createAgentSession()    ← 创建 session、tools、settings
        ├── SessionManager          ← JSONL 文件持久化
        ├── SettingsManager         ← compaction 配置
        ├── session.prompt()        ← 触发完整 agent loop（含工具调用循环）
        ├── session.compact()       ← 发起 compaction LLM 调用
        ├── session.subscribe()     ← 事件订阅
        └── estimateTokens()        ← token 估算
  └── @mariozechner/pi-ai
        ├── streamSimple            ← 标准 streaming LLM 调用
        └── type AssistantMessage   ← 消息类型
  └── @mariozechner/pi-agent-core
        └── type AgentMessage       ← 基础消息类型
```

---

## 参考文件

- `/tmp/openclaw/src/agents/pi-embedded-runner/run.ts` — 主重试循环（`runEmbeddedPiAgent`）
- `/tmp/openclaw/src/agents/pi-embedded-runner/run/attempt.ts` — 单次执行（`runEmbeddedAttempt`）
- `/tmp/openclaw/src/agents/pi-embedded-runner/compact.ts` — Compaction 实现
- `/tmp/openclaw/src/agents/pi-embedded-subscribe.ts` — 事件订阅系统
- `/tmp/openclaw/src/agents/pi-embedded-subscribe.handlers.ts` — 事件分发器
- `/tmp/openclaw/src/agents/pi-embedded-subscribe.handlers.tools.ts` — 工具事件处理
- `/tmp/openclaw/src/agents/pi-embedded-subscribe.handlers.compaction.ts` — Compaction 事件
- `/tmp/openclaw/src/agents/pi-embedded-runner/types.ts` — 核心类型定义
- `/tmp/openclaw/src/agents/pi-embedded-runner/runs.ts` — 活跃 run 注册表
- `/tmp/openclaw/src/agents/system-prompt.ts` — System prompt 组装
- `/tmp/openclaw/src/agents/pi-embedded-runner/system-prompt.ts` — embedded system prompt 入口
- `/tmp/openclaw/src/agents/model-auth.ts` — 模型鉴权
- `/tmp/openclaw/src/agents/model-selection.ts` — 模型选择和 Provider 别名
- `/tmp/openclaw/src/agents/model-catalog.ts` — 模型目录
- `/tmp/openclaw/src/agents/pi-embedded-runner/compaction-safety-timeout.ts` — Compaction 5分钟超时

---

# Part 2: 工具系统

**日期**: 2026-02-25
**任务**: 深入阅读 OpenClaw 源码中的工具系统，分析工具定义、注册、schema 生成、权限策略链、执行前后 hook 机制和 Bash 工具安全控制

---

## 调研摘要

OpenClaw 的工具系统构建在 `@mariozechner/pi-agent-core` 提供的 `AgentTool<Params, Details>` 接口之上，通过工厂函数（`createXxxTool`）创建工具实例，以多层策略管道（Pipeline）过滤工具集，并使用装饰器模式（Wrapper）为每个工具注入 before-hook、abort 信号等横切关注点。整套系统没有全局注册表，而是在运行时按会话上下文动态组装工具列表，再经策略流水线裁剪后交给 LLM。

---

## 现有代码分析

### 相关文件

- `/tmp/openclaw/src/agents/pi-tools.types.ts` — `AnyAgentTool` 类型定义（上游 `AgentTool<any, unknown>` 的别名）
- `/tmp/openclaw/src/agents/tools/common.ts` — 扩展版 `AnyAgentTool`（含 `ownerOnly` 字段）、工具辅助函数、错误类
- `/tmp/openclaw/src/agents/pi-tools.ts` — 顶层工具组装函数 `createOpenClawCodingTools`（核心入口）
- `/tmp/openclaw/src/agents/openclaw-tools.ts` — OpenClaw 专有工具集组装（`createOpenClawTools`）
- `/tmp/openclaw/src/agents/tool-catalog.ts` — 工具目录（ID、标签、Profile 映射、分组）
- `/tmp/openclaw/src/agents/pi-tools.policy.ts` — 策略解析：effective/group/subagent policy
- `/tmp/openclaw/src/agents/tool-policy.ts` — 策略执行：ownerOnly、allowlist、plugin 分组展开
- `/tmp/openclaw/src/agents/tool-policy-pipeline.ts` — 策略管道：有序多步过滤
- `/tmp/openclaw/src/agents/tool-policy-shared.ts` — 工具名规范化、组展开、Profile 策略
- `/tmp/openclaw/src/agents/tool-fs-policy.ts` — 文件系统策略（workspaceOnly 约束）
- `/tmp/openclaw/src/agents/bash-tools.ts` — exec/process 工具的重出口
- `/tmp/openclaw/src/agents/bash-tools.exec.ts` — exec 工具完整实现
- `/tmp/openclaw/src/agents/pi-tools.schema.ts` — JSON Schema 标准化（跨 provider 兼容）
- `/tmp/openclaw/src/agents/pi-tools.read.ts` — read/write/edit 工具包装层（参数规范化、sandbox 版本）
- `/tmp/openclaw/src/agents/pi-tools.before-tool-call.ts` — before_tool_call hook + 循环检测
- `/tmp/openclaw/src/agents/pi-tools.abort.ts` — AbortSignal 包装器

### 现有模式

1. **工厂模式**：所有工具都由 `createXxxTool(options)` 工厂函数创建，返回 `AnyAgentTool` 对象，无 class 继承。
2. **装饰器/Wrapper 链**：工具创建后经多个 wrapper 包裹（参数规范化 → workspaceRoot guard → policy 过滤 → before-hook → abort signal），最终交给 LLM。
3. **策略管道（Pipeline）**：工具列表经多个 `{ policy, label }` 步骤顺序过滤，每步独立应用 allow/deny 规则，失败时输出警告而非 throw。
4. **配置分层**：全局 config → agent 级 config → provider 级 config → 群组 policy → sandbox policy → subagent policy，后者覆盖前者。
5. **Provider 适配**：schema 在交给 LLM 前按 `modelProvider` 做 Gemini/OpenAI/Anthropic 特定清理。

### 可复用组件

- `normalizeToolParameters(tool, { modelProvider })` — schema 标准化，可独立使用
- `wrapToolWithBeforeToolCallHook(tool, ctx)` — 通用 before-hook 装饰器
- `wrapToolWithAbortSignal(tool, signal)` — 通用 abort 装饰器
- `applyToolPolicyPipeline({ tools, steps, toolMeta, warn })` — 策略管道，可接任意步骤集合
- `normalizeToolParams(params)` — Claude Code ↔ pi-coding-agent 参数名互换（`file_path` ↔ `path` 等）
- `readStringParam / readNumberParam / readStringArrayParam` — 工具参数读取辅助函数

---

## 工具 TypeScript 接口定义

### 上游核心类型（`@mariozechner/pi-agent-core`）

```typescript
// 上游接口（推断，未直接读到源码）
interface AgentTool<Params, Details> {
  name: string;
  label?: string;
  description: string;
  parameters: Record<string, unknown>;  // JSON Schema
  execute: (
    toolCallId: string,
    params: Params,
    signal?: AbortSignal,
    onUpdate?: (update: unknown) => void
  ) => Promise<AgentToolResult<Details>>;
}

interface AgentToolResult<Details> {
  content: Array<
    | { type: "text"; text: string }
    | { type: "image"; data: string; mimeType: string }
  >;
  details?: Details;
}
```

### OpenClaw 扩展类型（`tools/common.ts`）

```typescript
// AnyAgentTool = AgentTool<any, unknown> + ownerOnly flag
type AnyAgentTool = AgentTool<any, unknown> & {
  ownerOnly?: boolean;   // 如果为 true，只有 owner 发送者才能调用
};

// 工具错误类
class ToolInputError extends Error { status = 400; }
class ToolAuthorizationError extends ToolInputError { status = 403; }
```

---

## 工具注册和发现机制

OpenClaw **没有全局注册表**。工具发现和注册通过以下方式实现：

### 1. 静态工具目录（`tool-catalog.ts`）

`CORE_TOOL_DEFINITIONS` 数组定义所有核心工具的元数据：
- `id` / `label` — 工具唯一名称
- `sectionId` — 所属分组（`fs`, `runtime`, `web`, `sessions`, `ui`, `messaging` 等）
- `profiles` — 所属的 Profile 集合（`minimal`, `coding`, `messaging`, `full`）
- `includeInOpenClawGroup` — 是否属于 `group:openclaw` 逻辑组

Profile 到工具集映射：
| Profile | 工具集 |
|---------|--------|
| `minimal` | `session_status` |
| `coding` | `read, write, edit, apply_patch, exec, process, memory_search, memory_get, sessions_list, sessions_history, sessions_send, sessions_spawn, subagents, session_status, image` |
| `messaging` | `sessions_list, sessions_history, sessions_send, session_status, message` |
| `full` | 所有工具（无 allow 限制） |

### 2. 运行时动态组装（`pi-tools.ts: createOpenClawCodingTools`）

每次会话启动时，`createOpenClawCodingTools(options)` 执行以下流程：

```
codingTools (上游)  →  替换/过滤  →  base[]
                                      ↓
createExecTool / createProcessTool    ↓
createApplyPatchTool (条件性)         ↓
createOpenClawTools (OpenClaw专有工具) ↓
listChannelAgentTools (频道工具)      ↓
                              tools[] (合并)
                                      ↓
                     applyOwnerOnlyToolPolicy
                                      ↓
                     applyToolPolicyPipeline (策略过滤)
                                      ↓
                     normalizeToolParameters (schema清理)
                                      ↓
                     wrapToolWithBeforeToolCallHook
                                      ↓
                     wrapToolWithAbortSignal
                                      ↓
                              最终工具列表 → LLM
```

### 3. 插件工具（`plugins/tools.ts`）

`resolvePluginTools({ context, existingToolNames, toolAllowlist })` 加载插件注册的工具，注入到核心工具列表之后。插件工具通过 `pluginToolAllowlist` 控制。

---

## 工具 Schema 如何生成（给 LLM 的 JSON Schema）

Schema 生成在 `pi-tools.schema.ts: normalizeToolParameters` 完成，逻辑如下：

### Provider 适配策略

```
inputSchema (工具定义时写死)
        ↓
normalizeToolParameters(tool, { modelProvider })
        ↓
┌─────────────────────────────────────────────┐
│  case 1: 已有 type + properties，无 anyOf   │
│    → Gemini: cleanSchemaForGemini           │
│    → 其他: 原样返回                          │
├─────────────────────────────────────────────┤
│  case 2: 缺少 type 但有 properties/required │
│    → 注入 type: "object"                    │
│    → Gemini: cleanSchemaForGemini           │
├─────────────────────────────────────────────┤
│  case 3: 顶层 anyOf/oneOf（union schema）   │
│    → 合并所有 variant 的 properties         │
│    → 推导 required（所有 variant 都有的字段）│
│    → 展平为单一 { type: "object", ... }     │
│    → Gemini: cleanSchemaForGemini           │
└─────────────────────────────────────────────┘
```

**关键约束**：
- Gemini 不接受 `anyOf/oneOf`，不接受 `minimum/maximum` 等 constraint 关键字
- OpenAI 要求顶层必须有 `type: "object"`
- Anthropic 接受完整 JSON Schema Draft 2020-12

### Claude Code 参数别名兼容（`pi-tools.read.ts`）

`patchToolSchemaForClaudeCompatibility` 为 schema 添加别名属性，使 Claude Code 格式的参数名也能被接受：
- `file_path` 作为 `path` 的别名
- `old_string` 作为 `oldText` 的别名
- `new_string` 作为 `newText` 的别名

同时去掉原始字段的 `required` 标记（以便别名也可满足要求）。

---

## 权限策略链的具体实现逻辑

### 策略数据结构

```typescript
type SandboxToolPolicy = {
  allow?: string[];    // 允许的工具名列表（空 = 允许全部）
  deny?: string[];     // 拒绝的工具名列表
};
```

工具名支持：
- 精确名称（`exec`, `read`）
- 别名（`bash` → `exec`, `apply-patch` → `apply_patch`）
- 逻辑组（`group:fs`, `group:runtime`, `group:openclaw`, `group:plugins`）
- Glob 通配符（`web_*`）

### 策略解析层次（`pi-tools.policy.ts: resolveEffectiveToolPolicy`）

```
globalTools (config.tools)
    ├── profile (→ CORE_TOOL_PROFILES 预设)
    ├── allow / deny
    └── byProvider.<provider> { allow, deny, profile }

agentTools (config.agents[agentId].tools)
    ├── profile (覆盖 global)
    ├── allow / deny / alsoAllow
    └── byProvider.<provider> { ... }

groupPolicy (来自 channel dock 或 resolveChannelGroupToolsPolicy)

subagentPolicy (深度 ≥ 1 的子 agent 强制禁用部分工具)
```

### 策略执行管道（`tool-policy-pipeline.ts`）

`buildDefaultToolPolicyPipelineSteps` 构建有序步骤：

| 顺序 | 步骤标签 | 说明 |
|------|----------|------|
| 1 | `tools.profile` | Profile 预设（coding/messaging/minimal/full）|
| 2 | `tools.byProvider.profile` | Provider 特定 Profile |
| 3 | `tools.allow` | 全局 allow/deny |
| 4 | `tools.byProvider.allow` | Provider 特定 allow/deny |
| 5 | `agents.<id>.tools.allow` | Agent 级别 allow/deny |
| 6 | `agents.<id>.tools.byProvider.allow` | Agent 级别 Provider allow/deny |
| 7 | `group tools.allow` | 频道/群组 allow/deny |
| 8 | `sandbox tools.allow` | Sandbox 策略 |
| 9 | `subagent tools.allow` | 子 agent 深度策略 |

每步执行：
1. `stripPluginOnlyAllowlist`：若 allowlist 只含插件工具（无核心工具），忽略该 allowlist 以防止误禁核心工具
2. `expandPolicyWithPluginGroups`：展开 `group:plugins` / 插件 ID 为具体工具名
3. `filterToolsByPolicy`：根据 deny/allow 过滤工具列表

### 单工具 allow/deny 判断（`makeToolPolicyMatcher`）

```
判断顺序：
1. 如果工具名匹配 deny glob → 拒绝
2. 如果 allow 为空 → 允许（默认开放）
3. 如果工具名匹配 allow glob → 允许
4. 如果工具名是 apply_patch 且 allow 含 exec → 允许（special case）
5. 否则 → 拒绝
```

### owner-only 工具

三个工具默认 owner-only（`whatsapp_login`, `cron`, `gateway`），或工具对象上 `ownerOnly: true`。
- 非 owner 发送者：工具从列表中移除
- Owner 发送者：工具正常包含，execute 不被替换

### 子 agent 工具限制

子 agent 总是禁用：`gateway, agents_list, whatsapp_login, session_status, cron, memory_search, memory_get, sessions_send`

叶子子 agent（深度 ≥ maxSpawnDepth）额外禁用：`sessions_list, sessions_history, sessions_spawn`

---

## 工具执行前后的 Hook 机制

### before-tool-call hook（`pi-tools.before-tool-call.ts`）

`wrapToolWithBeforeToolCallHook(tool, ctx)` 装饰工具，在 `execute` 前执行：

**执行流程**：
```
tool.execute(toolCallId, params, signal, onUpdate)
        ↓ (wrapped)
runBeforeToolCallHook({ toolName, params, toolCallId, ctx })
        ↓
1. 工具调用循环检测（loop detection）
   - detectToolCallLoop：分析会话状态，判断是否卡死
   - critical loop → blocked=true → throw Error（阻止执行）
   - warning loop → 记录日志，继续执行
   - recordToolCall：记录本次调用到会话状态
        ↓
2. 插件 before_tool_call hook
   - hookRunner.runBeforeToolCall({ toolName, params }, context)
   - hookResult.block=true → blocked=true → throw Error
   - hookResult.params → 用新 params 替换原 params（参数改写）
        ↓
返回 HookOutcome: { blocked: false, params } 或 { blocked: true, reason }
        ↓
如果 blocked → throw Error(reason)
如果 params 被改写 → 存入 adjustedParamsByToolCallId Map
        ↓
调用原始 execute(toolCallId, outcome.params, signal, onUpdate)
        ↓
recordLoopOutcome（记录执行结果，供下次循环检测使用）
```

**循环检测特性**：
- 使用 `SessionState` 追踪每个会话的工具调用历史
- 支持可配置的 `ToolLoopDetectionConfig`（detectors 字段）
- 警告以 `LOOP_WARNING_BUCKET_SIZE=10` 为单位分桶，避免日志泛滥
- 最多追踪 `MAX_TRACKED_ADJUSTED_PARAMS=1024` 个调用的参数改写

**after-tool-call**：当前实现**没有独立的 after hook**，但 `recordLoopOutcome` 在 execute 完成（成功或失败）后被调用，可视为轻量级 after-hook。

### abort hook（`pi-tools.abort.ts`）

`wrapToolWithAbortSignal(tool, abortSignal)` 合并外部 AbortSignal 与工具调用自带的 signal，使父级取消可以传播到工具执行。

---

## Bash 工具（exec）的安全控制

### 执行主机类型（`ExecHost`）

| host | 说明 |
|------|------|
| `gateway` | 在宿主机上本地执行（默认） |
| `sandbox` | 在 Docker sandbox 容器内执行 |
| `node` | 在远程 node 服务上执行 |

默认安全策略：`sandbox → deny`（沙箱拒绝高危命令），`gateway/node → allowlist`。

### 安全控制层次

**1. host 限制**
- 请求的 host 必须等于配置的 host（除 elevated 模式外）
- 否则抛出 `exec host not allowed` 错误

**2. security 级别**（`allowlist` / `deny` / `full`）
- 取配置值与请求值的"最小安全值"（`minSecurity`）
- elevated full 模式会强制 `security=full`

**3. ask 审批模式**（`off` / `on-miss` / `on` / `always`）
- 取配置值与请求值的"最大审批值"（`maxAsk`）
- gateway host + `security=allowlist` → `processGatewayAllowlist` 处理命令白名单和审批

**4. safeBins allowlist**
- `resolveExecSafeBinRuntimePolicy` 解析 `safeBins` 和 `safeBinProfiles` 配置
- unprofiled safeBins 条目会被忽略并记录警告
- interpreter 类（node/python）的 safeBin 需要显式 hardened profile

**5. elevated（提权）控制**
- 需要 `tools.elevated.enabled = true` + `tools.elevated.allowFrom.<provider>` 配置
- elevated full → 跳过审批（`ask=off`），security 升为 `full`
- elevated ask → 强制走审批流程

**6. 环境变量校验**
- sandbox 以外的 host：`validateHostEnv(params.env)` 校验 env 合法性，防止注入

**7. 脚本文件预检（preflight）**
- `validateScriptFileForShellBleed`：Python/Node.js 脚本启动前检查是否含有 shell 变量语法（`$VAR_NAME` 风格）
- 防止模型生成的 shell 语法污染 Python/JS 文件（常见 LLM 失败模式）
- 仅对 `python file.py` / `node file.js` 形式的命令生效
- 文件超过 512KB 跳过检查

**8. background 执行控制**
- `allowBackground` 由策略决定（process 工具是否被 allow）
- 超时由 `yieldMs`/`backgroundMs`/`timeoutSec` 三级控制
- background 执行不受 abort signal 影响（`onAbortSignal` 检查 `yielded || backgrounded`）

---

## 技术方案对比

### 方案 A: 直接移植 OpenClaw 工具模式到 AI 自进化系统

**描述**: 将 `AgentTool` 接口 + 工厂函数 + 策略管道的组合移植到 Python 系统（用 dataclass/TypedDict 替代 TypeScript interface）

**优点**:
- 设计经过验证，安全性高
- 策略管道可扩展性强
- before/after hook 点清晰

**缺点**:
- TypeScript → Python 类型系统语义有差异
- 需重新实现 safeBins/allowlist 审批机制

**实现复杂度**: 高

### 方案 B: 借鉴设计模式，在现有架构上演进

**描述**: 从 OpenClaw 借鉴以下关键设计：(1) 工具通过 `ownerOnly` 字段标记权限级别，(2) 多层策略管道，(3) before-hook 用于循环检测

**优点**:
- 低风险，增量改进
- 不需要大规模重构

**缺点**:
- 无法获得 OpenClaw 完整的安全保障

**实现复杂度**: 低

---

## 推荐方案

**推荐**: 方案 B（借鉴设计模式）

**理由**:
1. OpenClaw 的核心价值在于设计模式，而非具体实现
2. 最关键的可借鉴点：工具名标准化 + 策略管道 + before-hook 循环检测
3. AI 自进化系统已有 Python 工具框架，增量改进风险最低

---

## 实施建议

### 关键步骤

1. 在工具基类中添加 `owner_only: bool` 字段，用于区分受限工具
2. 实现 `normalize_tool_name`（支持别名映射：`bash → exec`）和工具分组
3. 实现策略管道：`allow/deny` 列表 + glob 匹配，支持分组展开
4. 为工具执行添加 before-hook 接入点，实现循环检测
5. 在 exec/bash 工具中添加脚本预检（shell 变量注入检测）

### 风险点

- **循环检测过激** — 缓解措施: 先只实现 warning 级别，不做 block
- **策略过于复杂** — 缓解措施: 从 allow/deny 基础功能开始，不急于实现 profile/byProvider

### 依赖项

- `minimatch` 或等价 glob 库（工具名 glob 匹配）
- 会话状态存储（循环检测需要 per-session 调用历史）

---

## 参考资料

- `/tmp/openclaw/src/agents/pi-tools.ts` — 顶层工具组装入口
- `/tmp/openclaw/src/agents/tool-catalog.ts` — 工具目录和 Profile 定义
- `/tmp/openclaw/src/agents/pi-tools.policy.ts` — 策略解析
- `/tmp/openclaw/src/agents/tool-policy-pipeline.ts` — 策略管道
- `/tmp/openclaw/src/agents/pi-tools.before-tool-call.ts` — before-hook + 循环检测
- `/tmp/openclaw/src/agents/bash-tools.exec.ts` — exec 工具完整实现
- `/tmp/openclaw/src/agents/pi-tools.schema.ts` — JSON Schema 标准化
- `/tmp/openclaw/src/agents/pi-tools.read.ts` — 参数规范化 + 工作区保护

---

# Part 3: Telegram 集成与配置系统

**日期**: 2026-02-25
**任务**: 深入阅读 OpenClaw 源码中的 Telegram 集成与配置系统，分析消息路由、访问控制、配置结构、Skills 机制和 Gateway 启动流程

---

## 调研摘要

OpenClaw 使用 grammY 库作为 Telegram Bot 框架，通过多层中间件处理消息，最终路由到 Agent 执行。配置系统极为完整，支持多账户、群组策略、访问控制等。Skills 系统通过扫描多个目录加载 SKILL.md 文件，注入为 Agent 的系统提示片段。Gateway 启动时依次初始化配置、侧链服务、频道插件，最后通过 ChannelManager 管理每个频道的生命周期。

---

## 一、Telegram Bot 消息接收与路由

### 核心文件
- `/tmp/openclaw/src/telegram/bot.ts` — Bot 创建入口
- `/tmp/openclaw/src/telegram/bot-message.ts` — 消息处理器工厂
- `/tmp/openclaw/src/telegram/bot-message-context.ts` — 上下文构建（访问控制 + 路由）
- `/tmp/openclaw/src/telegram/bot-message-dispatch.ts` — 消息分发到 Agent
- `/tmp/openclaw/src/telegram/bot-handlers.ts` — 注册所有 Update 处理器
- `/tmp/openclaw/src/telegram/send.ts` — 消息发送（文本、媒体、贴纸、投票等）

### 消息接收流程（Bot 中间件管道）

```
grammY Bot.use() 中间件管道:
  1. 更新追踪中间件 (pendingUpdateIds, watermark 持久化)
  2. sequentialize(getTelegramSequentialKey) — 按 chat/topic 串行化
  3. 原始更新日志中间件 (verbose 模式)
  4. registerTelegramNativeCommands() — /start, /commands 等原生命令
  5. registerTelegramHandlers() — 注册所有消息类型处理器
```

### 顺序化键（Sequentialization Key）

```typescript
// 每个 chat + topic 组合有独立的串行队列
// 中止请求用特殊 :control 后缀
`telegram:${chatId}`                    // 普通 DM/群组
`telegram:${chatId}:topic:${threadId}`  // Forum topic
`telegram:${chatId}:control`            // 中止请求（abort）
```

### 消息路由到 Agent

`bot-message-context.ts` 中 `buildTelegramMessageContext()` 执行：

1. 记录渠道活动 (`recordChannelActivity`)
2. 构建 `peerId`（群组含 threadId）
3. 调用 `resolveAgentRoute()` — 按 channel + accountId + peer 路由到 agentId + sessionKey
4. DM 访问控制（见下文访问控制章节）
5. 群组访问控制（`evaluateTelegramGroupBaseAccess`）
6. mention 检测（`matchesMentionWithExplicit`）
7. 拼装 `ctxPayload`（`MsgContext`），包含 Body, From, SessionKey, 媒体路径等
8. 调用 `recordInboundSession()` 更新会话存储

路由后通过 `dispatchReplyWithBufferedBlockDispatcher()` 调用 Agent 获取响应。

---

## 二、消息发送实现（send.ts）

### 文本发送逻辑

```typescript
sendMessageTelegram(to, text, opts) {
  // 1. 解析并持久化 chatId（支持 @username → 数字 ID 解析）
  // 2. 构建 threadParams（forum topic / reply_to）
  // 3. 转换 Markdown → HTML（renderTelegramHtmlText）
  // 4. 发送 HTML，失败时降级到纯文本（withTelegramHtmlParseFallback）
  // 5. thread_not_found 时自动重试去掉 message_thread_id
}
```

### 媒体发送
- 支持类型：image（sendPhoto）、video（sendVideo）、video_note（sendVideoNote）、audio（sendAudio/sendVoice）、GIF（sendAnimation）、document（sendDocument）
- Caption 超长（> Telegram 限制）时自动拆分为媒体 + 后续文本消息
- `splitTelegramCaption()` 处理 caption/followUpText 分割

### HTML 格式化（format.ts）
- Markdown → MarkdownIR → HTML
- 自动转义 `&`, `<`, `>`
- 文件扩展名（如 README.md）若被 linkify 误识别为域名，用 `<code>` 包裹防止链接预览
- `tableMode` 支持 markdown 表格渲染

### 长文本分段（Streaming Lanes）
- `draftMaxChars = min(textLimit, 4096)` — 单条消息最大字符数
- 两个"Lane"：`answer`（答案）和 `reasoning`（推理过程）
- 流式预览：通过 `createTelegramDraftStream` 持续编辑同一条消息
- `streaming` 模式：`off` / `partial`（单条消息实时编辑）/ `block` / `progress`
- 答案到达 final 后，删除所有 archived preview 消息，发送最终版本

### 其他发送能力
- `sendStickerTelegram` — 发送贴纸（file_id）
- `sendPollTelegram` — 发送投票（支持多选、计时）
- `createForumTopicTelegram` — 创建 Forum Topic
- `reactMessageTelegram` — 发送 emoji 反应
- `deleteMessageTelegram` — 删除消息
- `editMessageTelegram` — 编辑消息（HTML 降级 + 忽略 MESSAGE_NOT_MODIFIED）

---

## 三、访问控制实现

### DM 访问控制（bot-message-context.ts）

`dmPolicy` 字段控制 DM 处理策略：

| 策略 | 行为 |
|------|------|
| `"pairing"`（默认）| 未知用户收到配对码，等待 owner 批准 |
| `"allowlist"` | 只允许 `allowFrom` 列表中的用户 |
| `"open"` | 允许所有 DM（allowFrom 包含 `"*"`）|
| `"disabled"` | 忽略所有 DM |

配对流程（pairing）：
1. `upsertChannelPairingRequest()` — 在 pairing store 创建/复用请求
2. `buildPairingReply()` — 发送含配对码的欢迎消息
3. 每次新请求都记录日志（chatId, userId, username）

### 群组访问控制（group-access.ts）

两层检查：

**第一层：基础访问** (`evaluateTelegramGroupBaseAccess`)
- `groupConfig.enabled === false` → 禁用整个群组
- `topicConfig.enabled === false` → 禁用指定 topic
- `groupAllowOverride` 存在时强制检查发送者 ID

**第二层：群组策略** (`evaluateTelegramGroupPolicyAccess`)
- `groupPolicy: "open"` — 所有人可发（默认）
- `groupPolicy: "disabled"` — 拒绝所有群组消息
- `groupPolicy: "allowlist"` — 只允许 `groupAllowFrom` 列表中的用户

### AllowFrom 规范化（bot-access.ts）

- allowFrom 条目必须是**数字型 Telegram 用户 ID**（字符串或数字）
- `"*"` 表示通配符
- 前缀 `telegram:` / `tg:` 自动剥除
- 非数字条目发出警告（onboarding 时应已解析 @username → ID）
- 支持从会话 store（pairing store）合并已批准的用户 ID

### Mention 门控

群组中 `requireMention` 为 true 时：
- 检查显式 `@bot_username` mention
- 检查 mention regex（自定义 mention 词）
- 检查 reply-chain（回复 bot 消息 = 隐式 mention）
- 语音消息：preflight 转录后检测是否含 mention
- 命令（`/command`）可绕过 mention 门控（`commandAuthorized`）

### ACK 反应（状态反应）

- `ackReaction`：收到消息后立即发 emoji 反应（如 👀）
- `statusReactions.enabled` 时升级为状态机：queued → thinking → tool → done/error
- Telegram 反应原子替换（无需先删除）

---

## 四、配置系统完整结构

### 顶层 OpenClawConfig

```typescript
type OpenClawConfig = {
  meta?           // 版本元数据
  auth?           // 认证配置（profiles, order）
  env?            // 环境变量注入（vars, shellEnv）
  wizard?         // 向导运行记录
  diagnostics?    // 诊断标志
  logging?        // 日志配置
  update?         // 更新策略
  browser?        // 浏览器控制
  ui?             // UI 外观（seamColor, assistant）
  skills?         // Skills 配置
  plugins?        // 插件配置
  models?         // 模型目录
  nodeHost?       // Node 宿主配置
  agents?         // Agent 列表和默认值
  tools?          // 工具配置
  bindings?       // Agent 路由绑定
  broadcast?      // 广播配置
  audio?          // 音频配置
  messages?       // 消息配置（prefix, reactions, history）
  commands?       // 命令配置（native, nativeSkills）
  approvals?      // 审批配置
  session?        // 会话存储配置
  web?            // Web 配置
  channels?       // 频道配置（telegram, discord, etc.）
  cron?           // 定时任务
  hooks?          // Webhooks/Gmail/内部钩子
  discovery?      // 节点发现
  canvasHost?     // Canvas 宿主
  talk?           // Talk API
  gateway?        // Gateway 配置
  memory?         // 记忆后端
}
```

### Telegram 账户配置（TelegramAccountConfig）完整字段

```typescript
type TelegramAccountConfig = {
  name?                  // 账户显示名
  capabilities?          // 能力标签（用于 Agent 指导）
  markdown?              // Markdown 格式化（表格模式等）
  commands?              // 原生命令注册（native, nativeSkills）
  customCommands?        // 自定义 Telegram 命令菜单项
  configWrites?          // 允许频道触发配置写入（default: true）
  dmPolicy?              // DM 策略: "pairing"(默认)/"allowlist"/"open"/"disabled"
  enabled?               // 是否启用此账户（default: true）
  botToken?              // Bot Token（明文）
  tokenFile?             // Token 文件路径（agenix 等密钥管理器）
  replyToMode?           // 回复线程模式: "off"/"first"/"all"
  groups?                // 每个群组的配置（key: chatId）
  allowFrom?             // DM 白名单（数字 Telegram 用户 ID）
  defaultTo?             // CLI --deliver 默认目标
  groupAllowFrom?        // 群组发送者白名单
  groupPolicy?           // 群组策略: "open"/"disabled"/"allowlist"
  historyLimit?          // 群组消息历史上限（default: DEFAULT_GROUP_HISTORY_LIMIT）
  dmHistoryLimit?        // DM 历史上限
  dms?                   // 每个用户 ID 的 DM 配置
  textChunkLimit?        // 出站文本分块大小（default: 4000）
  chunkMode?             // 分块模式: "length"/"newline"
  streaming?             // 流式预览模式: "off"/"partial"/"block"/"progress"
  blockStreaming?         // 禁用 block streaming
  draftChunk?            // （deprecated）block streaming 分块配置
  blockStreamingCoalesce? // 合并流式 block 回复
  streamMode?            // （deprecated）迁移到 streaming
  mediaMaxMb?            // 媒体大小上限（MB，default: 5）
  timeoutSeconds?        // API 超时（grammY ApiClientOptions）
  retry?                 // 出站 API 重试策略
  network?               // 网络传输（autoSelectFamily, dnsResultOrder）
  proxy?                 // 代理 URL
  webhookUrl?            // Webhook URL
  webhookSecret?         // Webhook Secret
  webhookPath?           // Webhook 路径
  webhookHost?           // Webhook 监听 host（default: 127.0.0.1）
  webhookPort?           // Webhook 监听端口（default: 8787）
  actions?               // 动作开关: reactions, sendMessage, deleteMessage, editMessage, sticker, createForumTopic
  reactionNotifications? // 反应通知: "off"(默认)/"own"/"all"
  reactionLevel?         // 反应能力: "off"/"ack"(默认)/"minimal"/"extensive"
  heartbeat?             // 心跳可见性（showOk, showAlerts, useIndicator）
  linkPreview?           // 链接预览（default: true）
  responsePrefix?        // 出站回复前缀（覆盖全局）
  ackReaction?           // 确认 emoji（Telegram 用 unicode，如 "👀"）
}
```

### TelegramGroupConfig 字段

```typescript
type TelegramGroupConfig = {
  requireMention?    // 是否需要 @mention 才响应
  groupPolicy?       // 群组策略覆盖
  tools?             // 工具策略覆盖
  toolsBySender?     // 按发送者的工具策略
  skills?            // 此群组可用的 skills 列表（omit=全部，空=无）
  topics?            // 每个 Forum Topic 的配置（key: messageThreadId）
  enabled?           // 是否启用（default: true）
  allowFrom?         // 群组发送者白名单覆盖
  systemPrompt?      // 群组系统提示片段
}
```

### TelegramTopicConfig 字段

```typescript
type TelegramTopicConfig = {
  requireMention?  // @mention 门控
  groupPolicy?     // 策略覆盖
  skills?          // 可用 skills（omit=继承群组，空=无）
  enabled?         // 是否启用
  allowFrom?       // 白名单覆盖
  systemPrompt?    // Topic 系统提示片段
}
```

### Skills 配置（SkillsConfig）

```typescript
type SkillsConfig = {
  allowBundled?  // bundled skill 白名单（只影响 bundled）
  load?: {
    extraDirs?          // 额外 skills 扫描目录（最低优先级）
    watch?              // 监听 skills 目录变化
    watchDebounceMs?    // 监听防抖（ms）
  }
  install?: {
    preferBrew?   // 偏好 Homebrew 安装（default: true）
    nodeManager?  // Node 包管理器: "npm"/"pnpm"/"yarn"/"bun"（default: "npm"）
  }
  limits?: {
    maxCandidatesPerRoot?     // 每个根目录最大子目录数（default: 300）
    maxSkillsLoadedPerSource? // 每个 source 最大加载数（default: 200）
    maxSkillsInPrompt?        // 提示词中最大 skills 数（default: 150）
    maxSkillsPromptChars?     // 提示词字符上限（default: 30000）
    maxSkillFileBytes?        // SKILL.md 大小上限（default: 256000 bytes）
  }
  entries?: Record<string, {
    enabled?  // 是否启用此 skill
    apiKey?   // Skill API key
    env?      // Skill 环境变量
    config?   // Skill 配置对象
  }>
}
```

### AgentsConfig 与 AgentConfig

```typescript
type AgentConfig = {
  id: string
  default?: boolean   // 是否为默认 agent
  name?: string
  workspace?: string
  agentDir?: string
  model?: AgentModelConfig
  skills?: string[]   // agent 可用的 skills 白名单
  memorySearch?: ...
  humanDelay?: ...
  heartbeat?: ...
  identity?: IdentityConfig  // 名字、persona、ack reaction
  groupChat?: GroupChatConfig
  subagents?: { allowAgents?, model? }
  sandbox?: AgentSandboxConfig
  params?: Record<string, unknown>  // stream params（temperature 等）
  tools?: AgentToolsConfig
}

type AgentBinding = {
  agentId: string
  match: {
    channel: string
    accountId?: string
    peer?: { kind: "direct"|"group"; id: string }
    guildId?: string
    teamId?: string
    roles?: string[]  // Discord role IDs
  }
}
```

---

## 五、Skills 加载和注入机制

### Skills 目录优先级（低 → 高）

```
extra dirs (config.skills.load.extraDirs)
  < bundled (内置 /skills/ 目录)
  < managed (~/.config/openclaw/skills/)
  < agents-skills-personal (~/.agents/skills/)
  < agents-skills-project ({workspace}/.agents/skills/)
  < workspace ({workspace}/skills/)
```

相同 name 的 skill，高优先级覆盖低优先级。

### SKILL.md 格式

```markdown
---
name: discord
description: "Discord ops..."
metadata:
  {
    "openclaw": {
      "emoji": "🎮",
      "requires": { "config": ["channels.discord.token"] }
    }
  }
allowed-tools: ["message"]
---

# 正文内容注入为 Agent 系统提示片段
```

Frontmatter 支持：
- `name` — skill 名称（唯一键）
- `description` — 简短描述
- `metadata.openclaw.emoji` — UI 图标
- `metadata.openclaw.requires.config` — 必需的配置路径
- `metadata.openclaw.requires.env` — 必需的环境变量
- `metadata.openclaw.requires.anyBins` — 至少需要其中一个可执行文件
- `allowed-tools` — skill 允许使用的工具列表

### Skills 注入流程

1. `loadWorkspaceSkillEntries()` — 扫描所有 skills 目录
2. `filterSkillEntries()` — 按 config.skills.allowBundled、eligibility（required binaries/envs）、skillFilter 过滤
3. `applySkillsPromptLimits()` — 按 count 和 chars 截断
4. `buildWorkspaceSkillsPrompt()` — 格式化为文本块
5. 文本块注入 Agent 系统提示

群组/Topic 级别 skill 过滤：
- `groupConfig.skills` 或 `topicConfig.skills` 指定允许的 skill 名列表
- `dispatchTelegramMessage` 中通过 `skillFilter` 参数传递

---

## 六、Gateway 启动顺序

### 主入口（server.impl.ts → startGatewayServer）

启动流程（基于 server-startup.ts 和 server-channels.ts 分析）：

```
1. loadConfig() — 加载配置文件（JSON5，支持 $include，${ENV} 替换）
2. migrateLegacyConfig() — 迁移旧配置格式
3. 清理 stale session lock files
4. startGatewaySidecars():
   a. startBrowserControlServerIfEnabled() — 浏览器控制服务器
   b. startGmailWatcherWithLogs() — Gmail webhook 监听（如配置）
   c. loadInternalHooks() — 加载内部钩子处理器
   d. startPluginServices() — 启动插件服务
   e. startGatewayMemoryBackend() — 记忆后端
5. startGatewayServer():
   a. HTTP 服务器（Express/Hono）
   b. WebSocket 服务器（客户端连接）
   c. Control UI
6. createChannelManager():
   a. 枚举所有已注册的 ChannelPlugin（telegram, discord, imessage 等）
   b. 对每个 channel 的每个 account 启动 runner
   c. 失败时按 BackoffPolicy 重试（initial: 5s, max: 5min, factor: 2）
7. startChannels() — 启动所有频道
8. runBootOnce() — 执行 BOOT.md 中的启动指令（如有）
9. scheduleRestartSentinelWake() — 监听 restart sentinel 文件
```

### ChannelManager 生命周期

- 每个频道账户有独立的 AbortController 和 task Promise
- `restartAttempts` 跟踪重试次数（max: 10）
- `manuallyStopped` 防止手动停止的频道被自动重启
- `resetRestartAttempts()` — 成功启动后重置计数器
- `markChannelLoggedOut()` — 标记登出状态（不触发重启）

### Telegram 频道启动（server-channels.ts + Telegram plugin）

1. 解析 `cfg.channels.telegram.accounts` — 多账户支持
2. 每个账户调用 `createTelegramBot(opts)`:
   - `new Bot(token)` — 创建 grammY Bot 实例
   - `apiThrottler()` — API 限流中间件
   - `sequentialize(getTelegramSequentialKey)` — 串行化中间件
   - `registerTelegramNativeCommands()` — 原生命令
   - `registerTelegramHandlers()` — 所有消息类型处理器
3. Polling 或 Webhook 模式启动
4. 持久化 updateId watermark（避免重启后重复处理）

---

## 七、配置文件加载机制

### 配置文件路径解析（config/paths.ts）

- 主配置：`~/.config/openclaw/config.json5`
- 支持 `$include` 指令（合并其他文件）
- 支持 `${ENV_VAR}` 环境变量替换（config/env-substitution.ts）
- 支持运行时覆盖（runtime-overrides.ts）

### 配置合并策略（merge-patch.ts）

- 使用 JSON Merge Patch（RFC 7396）
- 防止 prototype pollution（prototype-keys.ts 检测）
- `null` 值表示删除字段

### 配置验证（validation.ts / zod-schema.ts）

- Zod schema 验证
- 遗留字段迁移检测（legacy-migrate.ts）
- 插件 schema 合并（validateConfigObjectWithPlugins）

---

## 八、多账户支持

### Telegram 多账户

```json5
{
  "channels": {
    "telegram": {
      // 默认账户配置（accountId = "default"）
      "botToken": "...",
      // 命名账户
      "accounts": {
        "work": { "botToken": "...", "allowFrom": [123456] },
        "personal": { "botToken": "...", "dmPolicy": "open" }
      }
    }
  }
}
```

### Agent 路由绑定

```json5
{
  "bindings": [
    {
      "agentId": "work-agent",
      "match": { "channel": "telegram", "accountId": "work" }
    },
    {
      "agentId": "personal-agent",
      "match": { "channel": "telegram", "peer": { "kind": "direct", "id": "telegram:123456" } }
    }
  ]
}
```

---

## 九、关键数据结构

### MsgContext（ctxPayload）主要字段

```typescript
{
  Body           // 含 envelope 元数据的完整消息体
  BodyForAgent   // 纯用户文本（不含 metadata）
  RawBody        // 原始文本
  CommandBody    // 规范化的命令体
  From           // 来源标识（如 "telegram:group:123456:topic:7"）
  To             // 目标（如 "telegram:123456"）
  SessionKey     // 会话 key（用于状态持久化）
  AccountId      // 账户 ID
  ChatType       // "direct" | "group"
  Provider       // "telegram"
  MessageSid     // 消息 ID
  MediaPath      // 媒体文件路径（本地）
  MediaType      // MIME 类型
  MediaPaths     // 多媒体路径数组
  WasMentioned   // 是否被 mention（群组专用）
  ReplyToBody    // 回复目标的消息体
  ForwardedFrom  // 转发来源
  CommandAuthorized // 命令是否授权
  MessageThreadId   // Forum topic ID
  GroupSystemPrompt // 群组系统提示注入
}
```

---

## 参考资料

- `/tmp/openclaw/src/telegram/bot.ts` — Bot 创建，中间件管道
- `/tmp/openclaw/src/telegram/bot-message-context.ts` — 完整上下文构建逻辑
- `/tmp/openclaw/src/telegram/bot-message-dispatch.ts` — 流式 lane delivery
- `/tmp/openclaw/src/telegram/send.ts` — 发送 API（文本、媒体、贴纸、投票）
- `/tmp/openclaw/src/telegram/bot-access.ts` — AllowFrom 规范化
- `/tmp/openclaw/src/telegram/group-access.ts` — 群组策略检查
- `/tmp/openclaw/src/telegram/format.ts` — Markdown → HTML 转换
- `/tmp/openclaw/src/config/types.telegram.ts` — Telegram 配置类型定义
- `/tmp/openclaw/src/config/types.openclaw.ts` — 顶层 OpenClawConfig 结构
- `/tmp/openclaw/src/config/types.skills.ts` — Skills 配置类型
- `/tmp/openclaw/src/config/types.agents.ts` — AgentConfig + AgentBinding
- `/tmp/openclaw/src/agents/skills/workspace.ts` — Skills 加载/过滤/注入
- `/tmp/openclaw/src/gateway/server-startup.ts` — 启动侧链服务
- `/tmp/openclaw/src/gateway/server-channels.ts` — ChannelManager
- `/tmp/openclaw/src/gateway/boot.ts` — BOOT.md 启动指令执行
