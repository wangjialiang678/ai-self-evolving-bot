# 调研报告: OpenClaw 项目

**日期**: 2026-02-25
**任务**: 调研 OpenClaw 开源 AI agent 项目，重点关注工具调用、Agent Loop、LLM 接口抽象、工具注册、安全机制和 Telegram 集成

---

## 调研摘要

OpenClaw（前身为 Clawdbot/Moltbot）是一个本地优先（local-first）的个人 AI 助手平台，通过 WebSocket Gateway 连接多个消息渠道（WhatsApp、Telegram、Slack、Discord 等）。其核心架构分两层：OpenClaw 负责 Gateway 编排和渠道集成，Pi Agent Framework 负责底层 Agent Loop 和工具调用。技术上使用 TypeScript/Node.js 实现，MIT 开源，2025 年 11 月发布后已积累 214,000+ GitHub Stars。

---

## 项目基本信息

- **GitHub**: https://github.com/openclaw/openclaw
- **文档**: https://docs.openclaw.ai
- **技能注册表**: https://github.com/openclaw/clawhub（ClawHub.ai）
- **语言**: TypeScript (ESM)，Node.js >= 22
- **包管理**: pnpm（主要），Bun（支持）
- **许可证**: MIT
- **Stars**: ~214,000（2026-02）
- **创始人**: Peter Steinberger（2026-02 宣布加入 OpenAI，项目移交开源基金会）

---

## 核心架构

### 整体设计：Hub-and-Spoke

```
Channels (Telegram/Discord/WhatsApp/...)
         |
         v
  [Gateway Control Plane]  ws://127.0.0.1:18789
    - WebSocket Hub
    - Session Manager
    - Channel Adapters
    - Plugin System
         |
         v
  [Agent Runtime]  (Pi Agent Core)
    - Context Assembly
    - LLM Inference
    - Tool Execution
    - Event Streaming
         |
         v
  [LLM Providers]  (Claude/OpenAI/Gemini/Local)
```

**核心理念**："Gateway 是永远在线的控制平面；助手是产品。"

### 关键组件

1. **Gateway**: 单一 Node.js 进程，监听 `ws://127.0.0.1:18789`，协调所有渠道和工具
2. **Channel Adapters**: 各平台适配器，将平台消息规范化为内部格式
3. **Agent Runtime**: 基于 Pi Agent Core，实现完整的 Agent Loop
4. **Session Manager**: 以会话为安全边界，JSONL 持久化

---

## Agent Loop 设计

### 完整执行路径

```
intake → context assembly → model inference → tool execution → streaming replies → persistence
```

### 详细步骤

1. **Entry & Validation**: `agent` RPC 验证参数，立即返回 `runId`
2. **Preparation**: 加载 Skills，解析工作区，组装系统提示（base template + context）
3. **Model Execution**: 调用 `runEmbeddedPiAgent`（pi-agent-core 运行时），按 session 串行化队列
4. **Event Streaming**: 工具事件、助手 delta、生命周期事件分流并发
5. **Completion**: `agent.wait` 轮询生命周期 end/error 事件，返回最终状态

### 关键机制

- **串行化**: Runs 按 session key（session lane）串行化，可选全局 lane，防止竞态条件
- **超时**: 默认 600 秒运行超时；`agent.wait` 额外 30 秒超时
- **Hook 拦截**: 内部 gateway hooks（bootstrap + 命令）和插件 hooks（模型解析、提示构建、工具执行、消息处理）

### Pi Agent Framework 层次结构

```
pi-tui          → 终端 UI，Markdown 渲染，差分屏幕更新
pi-coding-agent → 会话持久化，文件/执行工具，扩展系统
pi-agent-core   → Agent Loop，工具调用，事件流
pi-ai           → LLM 通信，多 provider，流式，成本追踪
```

---

## 工具调用（Tool Use / Function Calling）

### 工具定义方式

使用 **TypeBox schemas** 实现类型安全的工具定义：

```typescript
// 每个工具包含：
{
  name: string,           // 工具名称
  description: string,   // 给 LLM 的描述
  parameters: TSchema,   // TypeBox schema（映射为 JSON Schema）
  execute: async (params) => {
    content: string,     // 发回 LLM 的结果
    details: any         // UI 展示用数据
  }
}
```

### 工具注册

通过 `createOpenClawCodingTools()` 工厂函数组装工具集：

```typescript
// 内置核心工具（25个）
group:runtime   → exec, bash, process
group:fs        → read, write, edit
group:memory    → memory search, session管理
group:messaging → 消息发送，渠道操作
group:browser   → Chrome CDP 浏览器自动化
group:canvas    → A2UI 可视工作区
group:nodes     → 配对设备控制
group:cron      → 定时任务和 webhook
```

### 工具调用流程

```
LLM 响应 → 检测 tool_use block
    → 发出 tool_start 事件
    → 执行 tool.execute()
    → 发出 tool_end 事件（含结果）
    → 将结果注入下一轮 context
    → 继续 LLM 推理
    → 重复直到无工具调用
```

### 流式输出

- Assistant deltas 实时流式返回
- 工具调用全程可见（call → result → model reasoning）
- Block streaming: partial replies 可在 `text_end` 或 `message_end` 时触发
- Reasoning streaming: 可作为独立流或作为 block replies

---

## LLM 接口抽象层

### Pi-AI Provider 抽象

`pi-ai` 包统一了多个 LLM provider 的接口：
- **支持**: Anthropic (Claude), OpenAI, Google (Gemini), Groq，以及本地模型
- **功能**: 流式响应、工具定义、成本追踪、失败时 profile rotation（模型故障转移）

### 配置方式

```json
// ~/.openclaw/openclaw.json
{
  "model": {
    "provider": "anthropic",  // 或 openai, google, groq
    "id": "claude-3-5-sonnet-20241022"
  }
}
```

### 多代理路由

支持跨隔离工作区的多代理路由，每个 agent 有独立 session，工具权限可独立配置。

---

## Skills（技能）系统

### 核心概念

- **Tools 是器官**：决定 OpenClaw 能做什么（实际执行能力）
- **Skills 是教材**：教 OpenClaw 如何组合 Tools 完成任务（纯文档，注入 system prompt）

### Skill 格式

Skills 是目录 + `SKILL.md` 文件，不是编译代码：

```markdown
---
name: "skill-name"
version: "1.0.0"
description: "功能描述"
tags: ["tag1", "tag2"]
requires:           # 门控条件
  binaries: [...]
  env: [...]
---

# 技能指令（自然语言）

...工具使用说明、示例、参数配置...
```

### Skill 加载机制

优先级（高→低）：
1. `<workspace>/skills/` - 工作区级别
2. `~/.openclaw/skills/` - 用户级别（多 agent 共享）
3. 内置 Skills（随安装附带）

**选择性注入**：运行时只将当前 turn 相关的 skill 注入 prompt，避免 prompt 膨胀

**Token 成本**:
- 基础开销（至少 1 个 skill）: 195 字符
- 每个 skill: 97 字符 + name/description/location 的 XML 转义长度

### ClawHub 注册表

- 官方公开注册表，类比 npm for Node.js
- 当前拥有 5,705+ 社区技能（2026-02）
- 安装命令：`clawhub install <skill-slug>`
- 搜索：`clawhub search "calendar management"`（语义搜索，使用 OpenAI embeddings）

---

## 工具权限与安全机制

### 五层权限链（级联过滤，只能收窄不能扩大）

```
1. Global policy    → tools.allow / tools.deny
2. Provider policy  → tools.byProvider
3. Agent policy     → agents.list[].tools
4. Session policy   → 每个 session 独立设置
5. Sandbox policy   → sandbox.tools
```

**规则**: "Deny 规则在任何层级都优先于 Allow 规则"

### 预定义工具 Profiles

| Profile | 包含工具 |
|---------|---------|
| minimal | session_status only |
| coding | 文件 I/O, 执行, sessions, memory |
| messaging | 消息和 session 工具 |
| full | 无限制 |

### Sandbox 隔离

三种沙箱模式：
- **off**: 所有工具运行在 host
- **non-main**: 非 DM 会话运行在 Docker 沙箱
- **all**: 所有会话都沙箱化

工作区访问级别控制文件工具权限：`none` / `ro` / `rw`

`elevated` 模式允许特定工具绕过沙箱（需显式配置 `tools.elevated`）

### 会话信任边界

| 会话类型 | 默认权限 | 典型场景 |
|---------|---------|---------|
| `main` | 全量 host 权限 | 操作者直接交互 |
| `dm:<channel>:<id>` | 沙箱 + 受限工具 | 外部用户 DM |
| `group:<channel>:<id>` | 沙箱 + 受限工具 | 群组消息 |

### 网络安全

- Gateway 默认仅绑定 loopback（127.0.0.1 / ::1）
- 远程访问通过 SSH tunnel 或 Tailscale
- Web UI 仅供本地使用
- 不推荐多个互不信任用户共享同一 Gateway（应该分别部署独立实例）

### 防注入机制

- 用户输入、系统指令、工具结果在结构上保持分离
- 对抗 prompt injection 攻击

### 数据存储

- 配置: `~/.openclaw/openclaw.json`（JSON5 格式）
- 会话: `~/.openclaw/sessions/`（append-only JSONL event logs）
- 凭证: `~/.openclaw/credentials/`（受限文件权限）
- 自动 session compaction：防止超出模型 context 限制，通过 memory files 和语义搜索保留关键上下文

---

## Telegram 集成

### 架构

```
Telegram Bot API (grammY) ←→ Channel Adapter ←→ Gateway ←→ Agent Runtime
```

### 技术栈

- 使用 **grammY** 库对接 Telegram Bot API
- 默认使用 **long polling**（无需额外配置）
- 可选 Webhook 模式（需配置 `webhookUrl` 和 `webhookSecret`）

### 配置步骤

1. 通过 `@BotFather` 创建 bot，获取 token
2. 将 token 加入配置文件或环境变量
3. 启动 Gateway，批准初始 DM 配对
4. 配置群组访问策略

### 访问控制模式

| 模式 | 说明 |
|------|------|
| pairing（默认） | 未知发送者收到配对码，显式批准后加入白名单 |
| allowlist | 数字 ID 白名单 |
| open | 完全开放访问（需显式 opt-in） |
| disabled | 禁用该渠道 |

### 群组配置

- 默认 privacy mode：bot 只收到 @mention 消息
- 若需响应所有消息：通过 `/setprivacy` 关闭 privacy mode，或设为群组管理员
- 群组消息默认在 Docker 沙箱中执行

### 常见问题

- IPv6 连接问题（Telegram API 服务器 DNS 解析）
- 建议关注 `NETWORK_ERROR` 日志排查连接问题

---

## 与本项目（AI 自进化系统）的对比

| 维度 | OpenClaw | 本项目 |
|------|----------|--------|
| 架构层次 | Gateway + Pi Agent（双层） | 单体 Python（agent_loop.py） |
| Agent Loop | Pi Agent Core（TypeScript） | 自研（Python） |
| 工具定义 | TypeBox schema + 函数 | 自定义格式 |
| 工具权限 | 五层级联策略链 | 待完善 |
| 沙箱 | Docker 容器隔离 | 无 |
| Telegram 集成 | Channel Adapter（grammY） | 无/未知 |
| LLM 抽象 | pi-ai 多 provider | llm_client.py |
| 技能系统 | SKILL.md（Markdown） | 无 |
| 持久化 | JSONL event log + semantic search | memory.py |

---

## 可借鉴的设计模式

### 1. 工具权限策略链

多层级联过滤（只能收窄），Deny 优先于 Allow，是安全工具系统的最佳实践。

### 2. Session 作为安全边界

将 main/dm/group 区分为不同信任级别的会话，main 有全权，外部输入默认沙箱化。

### 3. Skills = Markdown 文档，Tool = 代码函数

分离"如何做"（skills，可热更新）和"能做什么"（tools，需代码实现），选择性注入避免 prompt 膨胀。

### 4. 工具调用可见性

全程流式：工具调用 → 结果 → LLM 推理，用户可实时观察，便于调试和信任建立。

### 5. 串行化 per-session 避免竞态

并发请求在 session 维度串行化，防止历史记录不一致。

---

## 参考资料

- [OpenClaw GitHub 主库](https://github.com/openclaw/openclaw)
- [OpenClaw 官方文档](https://docs.openclaw.ai)
- [Agent Loop 文档](https://docs.openclaw.ai/concepts/agent-loop)
- [Skills 文档](https://docs.openclaw.ai/tools/skills)
- [Telegram 集成文档](https://docs.openclaw.ai/channels/telegram)
- [Pi Agent Framework 介绍 - Armin Ronacher](https://lucumr.pocoo.org/2026/1/31/pi/)
- [How to Build with Pi - Nader Dabit](https://nader.substack.com/p/how-to-build-a-custom-agent-framework)
- [OpenClaw Gateway 深度解析](https://practiceoverflow.substack.com/p/deep-dive-into-the-openclaw-gateway)
- [Tools and Skills - DeepWiki](https://deepwiki.com/openclaw/openclaw/6-tools-and-skills)
- [OpenClaw Architecture Overview - Substack](https://ppaolo.substack.com/p/openclaw-system-architecture-overview)
- [ClawHub 注册表指南](https://help.apiyi.com/en/clawhub-ai-openclaw-skills-registry-guide-en.html)
- [安全默认配置 Issue #7827](https://github.com/openclaw/openclaw/issues/7827)
- [Tanmay1112004/openclaw-telegram-agent](https://github.com/Tanmay1112004/openclaw-telegram-agent)
- [fiv3fingers/openclaw-telegram-ai-agent](https://github.com/fiv3fingers/openclaw-telegram-ai-agent)
