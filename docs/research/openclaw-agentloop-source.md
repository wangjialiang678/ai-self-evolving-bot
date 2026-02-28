# 调研报告: OpenClaw Agent Loop (Pi Embedded Runner) 源码分析

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
