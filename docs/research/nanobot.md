# 调研报告: Nanobot 项目

**日期**: 2026-02-25
**任务**: 调研 Nanobot 开源项目的架构、工具调用机制、Agent Loop 设计、LLM 接口抽象、工具注册方式、安全机制及 Telegram 集成

---

## 调研摘要

存在两个同名但完全不同的 "nanobot" 项目。主要目标是 **HKUDS/nanobot**（Python，~4000 行，香港大学数据智能实验室，2026-02-02 发布，17800+ stars），它是一个超轻量级多平台 AI 助手框架，具备完整的 Tool Calling、Multi-Channel（含 Telegram）、MCP 集成能力。另有 **nanobot-ai/nanobot**（Go，MCP Host 框架，由 Obot.ai 维护）专注于 MCP 协议，无 Telegram 集成。本报告以 HKUDS/nanobot 为主。

---

## 项目基本信息

| 属性 | HKUDS/nanobot | nanobot-ai/nanobot |
|------|---------------|-------------------|
| 语言 | Python | Go (81%) + Svelte (12%) |
| 定位 | 超轻量 AI 助手，多平台 | MCP Host / Agent 框架 |
| 核心代码量 | ~3,806 行 | 未知 |
| Telegram | 支持（长轮询） | 不支持 |
| MCP | 支持（作为 client） | 核心能力（作为 host） |
| License | 未提及 | Apache 2.0 |
| Stars | 17,800+ | 较少 |
| 发布时间 | 2026-02-02 | 早期开发中 |

---

## 现有代码分析（HKUDS/nanobot）

### 关键源文件（GitHub）

- `nanobot/agent/loop.py` - Agent Loop 核心，AgentLoop 类，最多 20 轮迭代
- `nanobot/agent/context.py` - ContextBuilder，组装 LLM prompt
- `nanobot/providers/litellm_provider.py` - LLM Provider 抽象，基于 LiteLLM
- `nanobot/providers/registry.py` - Provider 注册表，单一数据源
- `nanobot/agent/tools/registry.py` - 工具注册表，维护可用工具集合
- `SECURITY.md` - 安全策略文档

### 项目目录结构（推断）

```
nanobot/
├── agent/
│   ├── loop.py           # AgentLoop 核心
│   ├── context.py        # ContextBuilder
│   └── tools/
│       └── registry.py   # ToolRegistry
├── providers/
│   ├── registry.py       # LLM Provider 注册表
│   └── litellm_provider.py
├── channels/
│   └── telegram.py       # TelegramChannel（推断）
└── gateway/
    └── ...               # Gateway 服务入口
```

### 配置文件

- `~/.nanobot/config.json` - 主配置（API Keys、Channel Token、allowFrom 等）
- `~/.nanobot/workspace/` - Workspace（文件沙箱目录）
- `~/.nanobot/workspace/AGENTS.md` / `SOUL.md` / `USER.md` / `TOOLS.md` / `IDENTITY.md` - 引导文件
- `~/.nanobot/workspace/MEMORY.md` - 记忆汇总
- `~/.nanobot/workspace/HISTORY.md` - 历史日志

---

## 架构概览

### 五层架构

```
┌─────────────────────────────────────────────────────┐
│  用户界面层 (UI Layer)                                │
│  CLI + 9个Channel: Telegram/Discord/WhatsApp/...    │
├─────────────────────────────────────────────────────┤
│  核心编排层 (Core Orchestration)                     │
│  MessageBus  ←→  ChannelManager  ←→  SessionManager│
├─────────────────────────────────────────────────────┤
│  Agent 处理引擎 (Agent Processing Engine)            │
│  AgentLoop  ←→  ContextBuilder  ←→  MemoryStore    │
├─────────────────────────────────────────────────────┤
│  工具生态 (Tool Ecosystem)                           │
│  内置工具 + Skills + MCP服务 + CronTool + MsgTool   │
├─────────────────────────────────────────────────────┤
│  LLM Provider 系统 (Provider System)                │
│  ProviderRegistry → LiteLLMProvider/CustomProvider  │
└─────────────────────────────────────────────────────┘
```

### 两种运行模式

- **Agent Mode** (`nanobot agent`)：直接 CLI 交互，用于开发/测试
- **Gateway Mode** (`nanobot gateway`)：多 Channel 服务器，生产部署

---

## 工具调用（Tool Calling）机制

### 工具分类（五类）

1. **内置工具（Built-in Tools）**：文件操作、Shell 执行、网页搜索
2. **技能（Skills）**：预打包的能力组合（类似 OpenClaw 的 skills 系统）
3. **MCP 服务（MCP Servers）**：外部 MCP server，作为原生工具使用
4. **CronTool**：计划任务（cron 表达式、interval、单次时间戳）
5. **MessageTool**：跨 Channel 消息发送

### 工具注册

```python
# ToolRegistry 维护工具集合，向 LLM 提供 schema
# _register_default_tools() 在初始化时注册内置工具

# 工具定义使用 OpenAI function calling 格式
{
  "type": "function",
  "function": {
    "name": "exec",
    "description": "执行 shell 命令",
    "parameters": {
      "type": "object",
      "properties": {
        "command": {"type": "string"}
      }
    }
  }
}
```

### ContextBuilder 工具加载策略

```python
# 渐进式 Skill 加载（防止 Prompt 膨胀）
# - Always-loaded skills: 包含完整内容
# - Available skills: 只显示摘要，agent 用 read_file 按需加载
```

### Tool Calling 数据流

```
LLM 返回 tool_calls
  → AgentLoop._run_agent_loop() 解析
  → 查找 ToolRegistry 中对应工具
  → 执行工具，获得结果
  → add_tool_result() 追加到对话
  → 继续下一轮 LLM 调用
  → 直至无 tool_calls 或达到 max_iterations(20)
```

---

## Agent Loop 设计

### 核心类：AgentLoop (loop.py)

```python
class AgentLoop:
    def __init__(self, provider, workspace, config):
        # 初始化 LLM provider、workspace、工具执行配置、记忆管理

    def _register_default_tools(self):
        # 注册内置工具：文件操作、shell执行、网页搜索、消息发送

    def _run_agent_loop(self, session):
        # 核心：协调 LLM 交互与工具执行，迭代推理（最多20轮）
        # 每轮：build context → LLM call → parse tool_calls → execute → append result

    def _process_message(self, inbound_msg):
        # 处理入站消息，管理 session 状态
        # 触发记忆整合（防止 context 溢出）
        # 路由响应

    def run(self):
        # 主事件循环：消费 MessageBus 消息，处理，发布结果
```

### 关键设计决策

- **最大迭代限制**：20 轮，防止无限循环
- **事件驱动**：基于 asyncio.gather() 并发处理多 Channel
- **会话隔离**：SessionManager 以 `channel:chat_id` 为 key 维护状态
- **记忆整合**：超出 context 时自动归档到 MEMORY.md + HISTORY.md
- **子代理支持**：AgentLoop 可 spawn 后台子代理并发执行

---

## LLM 接口抽象层

### Provider Registry（providers/registry.py）

注册表驱动，无 if-elif 链，添加新 Provider 只需 2 步：

**Step 1**：在 `PROVIDERS` 列表添加 `ProviderSpec`：
```python
ProviderSpec(
    name="myprovider",
    keywords=["myprovider"],
    env_key="MYPROVIDER_API_KEY",
    display_name="MyProvider",
    litellm_prefix="myprovider",
    skip_prefixes=[]
)
```

**Step 2**：在 `ProvidersConfig` (config/schema.py) 添加字段：
```python
myprovider: ProviderConfig = ProviderConfig()
```
环境变量、模型前缀、配置匹配、状态显示自动生效。

### LiteLLMProvider（providers/litellm_provider.py）

- 通过 LiteLLM 统一支持 15+ LLM 服务（OpenRouter、Anthropic、OpenAI、Gemini、MiniMax、DeepSeek、Groq 等）
- 支持中国区 Provider：Dashscope（Qwen）、VolcEngine、MiniMax
- **模型自动前缀**：`"anthropic/claude-opus-4-5"` 等
- **缓存控制（Prompt Cache）**：自动检测支持情况，注入 ephemeral cache control
- **消息清洗**：`_sanitize_messages()` 剥离非标准字段
- **Tool Calling 解析**：从 JSON 字符串解析函数参数，返回 `ToolCallRequest(id, name, args)`
- **推理内容支持**：处理 Kimi、DeepSeek-R1 的 reasoning_content

### 支持的 LLM Provider

OpenRouter（推荐全球）、Anthropic、OpenAI、DeepSeek、Groq、Gemini、Dashscope/Qwen、MiniMax、VolcEngine、自托管（vLLM/Ollama 等）

---

## Telegram 集成

### 实现方式

- 使用 `python-telegram-bot` 库
- **长轮询模式**（HTTP Long Polling），无需公网 IP 或 Webhook
- 连接池大小：16；启动时丢弃 pending 消息（`drop_pending_updates=True`）

### TelegramChannel 类

实现 `BaseChannel` 接口，统一 Channel 抽象。

### 配置（config.json）

```json
{
  "channels": {
    "telegram": {
      "enabled": true,
      "token": "YOUR_BOT_TOKEN",
      "allowFrom": ["USER_ID_OR_USERNAME"],
      "reply_to_message": true,
      "proxy": "socks5://..."
    }
  }
}
```

### 消息处理能力

- **文本消息**：解析 → InboundMessage → MessageBus → AgentLoop
- **媒体消息**：照片、语音、音频、文档，下载到 `~/.nanobot/media/`
- **语音转文字**：需配置 Groq API，调用 Whisper，结果用 `[transcription: ...]` 标记
- **Markdown → HTML**：Telegram 需 HTML 格式，自动转换，失败降级为纯文本
- **长文本分割**：超 4000 字符按行分割发送
- **Typing 指示器**：Agent 处理时显示"正在输入"

### 访问控制

`allowFrom` 支持多种格式：
- 纯数字 User ID：`"123456789"`
- 用户名：`"@username"`
- 组合格式：`"123456789|username"`
- 空列表 = 允许所有人（个人使用）

### 消息流向

```
Telegram API → TelegramChannel._handle_message()
  → 解析/下载附件 → InboundMessage
  → MessageBus.publish(inbound)
  → AgentLoop.consume()
  → 处理完成 → OutboundMessage
  → MessageBus.publish(outbound)
  → ChannelManager.dispatch()
  → TelegramChannel.send()
  → Telegram API
```

---

## 安全机制

### 工作空间沙箱

```json
// config.json
"restrictToWorkspace": true
```
所有文件操作限制在 `~/.nanobot/workspace/` 内，File 工具会校验路径不能 traversal 出目录。

### Shell 命令过滤（ExecTool）

```json
"deny_patterns": ["rm -rf /", ":(){ :|:& };:", "dd if=", "mkfs"],
"allow_patterns": []
```
基于模式匹配过滤危险命令（`rm -rf /`、fork bomb、磁盘格式化等）。

注意：是**模式匹配**而非白名单，有绕过风险。

### 迭代上限

AgentLoop 最大 20 轮迭代，防止无限循环消耗资源。

### 访问控制

每个 Channel 独立的 `allowFrom` 白名单，按 User ID 或用户名鉴权。

### 已知安全限制（官方承认）

1. **无内置限流**（Rate Limiting）
2. **凭证明文存储**（config.json 中 API Key 明文）
3. **无自动 Session 过期**
4. **命令过滤基于模式**，非完整白名单
5. **审计日志功能最小化**

### 生产加固建议（官方）

- 容器化运行（Docker）
- 专用低权限系统用户，禁 root
- 目录权限 0700，配置文件 0600
- 定期 `pip-audit` 检查依赖漏洞
- 配置 LLM Provider 层的 Rate Limit

---

## Gateway 启动流程（gateway/service.py 推断）

```python
# 8步顺序初始化，asyncio.gather() 并发运行
1. load_config()
2. create MessageBus
3. create Provider
4. create SessionManager
5. create CronService
6. create AgentLoop
7. create HeartbeatService
8. create ChannelManager
```

---

## 与本项目（AI自进化系统）的对比与启示

| 特性 | HKUDS/nanobot | 本项目 |
|------|---------------|--------|
| Agent Loop 上限 | 20 轮 | 需确认 |
| Tool 注册方式 | ToolRegistry 集中 | 需评估 |
| LLM 抽象 | LiteLLM + ProviderRegistry | LLMClient |
| 消息总线 | asyncio Queue | 无 |
| 多 Channel | 9+ 平台统一 | 无 |
| 记忆管理 | MEMORY.md + HISTORY.md 文件 | memory.py 模块 |
| 沙箱 | restrictToWorkspace | 无明显沙箱 |
| 技能系统 | Skills（渐进加载） | 无 |
| 子代理 | 支持后台 spawn | 无 |

### 可借鉴的设计模式

1. **渐进式技能加载**：避免 prompt 膨胀，摘要先行、按需全载
2. **Provider Registry 无 if-elif**：注册表驱动，易扩展
3. **MessageBus 解耦**：生产/消费解耦，多 Channel 统一路由
4. **Workspace 沙箱**：文件操作限制在指定目录
5. **迭代上限**：防止失控的工具调用循环

---

## 参考资料

- [HKUDS/nanobot GitHub](https://github.com/HKUDS/nanobot)
- [nanobot-ai/nanobot GitHub](https://github.com/nanobot-ai/nanobot)
- [DeepWiki - HKUDS/nanobot 架构概览](https://deepwiki.com/HKUDS/nanobot)
- [DeepWiki - Gateway and Message Bus](https://deepwiki.com/HKUDS/nanobot/3.5.1-gateway-and-message-bus)
- [DeepWiki - Telegram Integration](https://deepwiki.com/HKUDS/nanobot/4.1-telegram-integration)
- [DeepWiki - Best Practices](https://deepwiki.com/HKUDS/nanobot/6.5-best-practices)
- [nanobot/agent/loop.py 源码](https://github.com/HKUDS/nanobot/blob/main/nanobot/agent/loop.py)
- [nanobot/agent/context.py 源码](https://github.com/HKUDS/nanobot/blob/main/nanobot/agent/context.py)
- [nanobot/providers/litellm_provider.py 源码](https://github.com/HKUDS/nanobot/blob/main/nanobot/providers/litellm_provider.py)
- [SECURITY.md](https://github.com/HKUDS/nanobot/blob/main/SECURITY.md)
- [NanoBot Architecture Teardown (Medium)](https://jinlow.medium.com/nanobot-architecture-teardown-4-000-lines-achieving-openclaw-capability-3f242113ccbc)
- [WangyiNTU/nanobot-study](https://github.com/WangyiNTU/nanobot-study)
- [Analytics Vidhya - Build an Agent with Nanobot](https://www.analyticsvidhya.com/blog/2026/02/ai-crypto-tracker-with-nanobot/)
