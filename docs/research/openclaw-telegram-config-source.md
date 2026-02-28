# 调研报告: OpenClaw Telegram 集成 + 配置系统源码分析

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
