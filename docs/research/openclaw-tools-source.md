# 调研报告: OpenClaw 工具系统源码分析

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
