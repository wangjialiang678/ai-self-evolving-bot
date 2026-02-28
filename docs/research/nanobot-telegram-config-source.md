# 调研报告: Nanobot 源码深度分析 — Telegram + Config + Bus

**日期**: 2026-02-25
**来源**: `/tmp/nanobot/nanobot/`

---

## 调研摘要

Nanobot 采用"消息总线 + 通道插件"架构，所有通道（Telegram、WhatsApp、Discord 等）通过统一的 `MessageBus` 解耦通信。配置系统基于 Pydantic BaseSettings，支持 camelCase/snake_case 双格式，存储在 `~/.nanobot/config.json`。启动链路为：CLI 解析 → 加载配置 → 创建 Bus/Provider/Agent → 创建 ChannelManager → 并发启动所有组件。

---

## 一、消息总线（Bus）

### 文件位置
- `nanobot/bus/queue.py` — MessageBus 实现
- `nanobot/bus/events.py` — InboundMessage / OutboundMessage 数据类

### MessageBus 实现

```python
class MessageBus:
    def __init__(self):
        self.inbound: asyncio.Queue[InboundMessage] = asyncio.Queue()
        self.outbound: asyncio.Queue[OutboundMessage] = asyncio.Queue()

    async def publish_inbound(self, msg: InboundMessage) -> None  # 通道 → Agent
    async def consume_inbound(self) -> InboundMessage              # Agent 从此消费
    async def publish_outbound(self, msg: OutboundMessage) -> None # Agent → 通道
    async def consume_outbound(self) -> OutboundMessage            # ChannelManager 消费
```

- 两个独立的 `asyncio.Queue`，完全异步解耦
- 无 backpressure 机制（无界队列）

### InboundMessage 字段

| 字段 | 类型 | 说明 |
|------|------|------|
| `channel` | str | 来源通道名 (telegram/discord/slack/whatsapp) |
| `sender_id` | str | 用户标识符 |
| `chat_id` | str | 聊天/频道 ID |
| `content` | str | 消息文本 |
| `timestamp` | datetime | 接收时间（自动生成） |
| `media` | list[str] | 媒体文件路径列表 |
| `metadata` | dict[str, Any] | 通道特定数据 |
| `session_key_override` | str \| None | 覆盖默认 session key |

- `session_key` 属性：`session_key_override` 或 `f"{channel}:{chat_id}"`

### OutboundMessage 字段

| 字段 | 类型 | 说明 |
|------|------|------|
| `channel` | str | 目标通道名 |
| `chat_id` | str | 目标聊天 ID |
| `content` | str | 消息文本 |
| `reply_to` | str \| None | 引用消息 ID |
| `media` | list[str] | 媒体文件路径 |
| `metadata` | dict[str, Any] | 附加数据（含 `_progress`、`_tool_hint` 控制标志） |

**特殊 metadata 字段**：
- `_progress: bool` — 标记为进度消息（可配置是否发送）
- `_tool_hint: bool` — 标记为工具调用提示（可配置是否发送）
- `message_id` — 用于 Telegram reply_to

---

## 二、通道基类（BaseChannel）

### 文件位置
- `nanobot/channels/base.py`

### 抽象接口

```python
class BaseChannel(ABC):
    name: str = "base"

    def __init__(self, config: Any, bus: MessageBus): ...

    @abstractmethod
    async def start(self) -> None: ...    # 长期运行，监听消息

    @abstractmethod
    async def stop(self) -> None: ...     # 清理资源

    @abstractmethod
    async def send(self, msg: OutboundMessage) -> None: ...  # 发送消息

    def is_allowed(self, sender_id: str) -> bool: ...        # ACL 检查

    async def _handle_message(
        self,
        sender_id: str,
        chat_id: str,
        content: str,
        media: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        session_key: str | None = None,
    ) -> None: ...  # 检查权限 → 包装 InboundMessage → 发布到 Bus

    @property
    def is_running(self) -> bool: ...
```

### ACL 逻辑（is_allowed）

1. `config.allow_from` 为空 → 允许所有人
2. `sender_id` 直接在列表中 → 允许
3. `sender_id` 含 `|` 分隔符（如 `12345|username`）→ 逐段匹配 → 任一段在列表中则允许

---

## 三、Telegram 通道

### 文件位置
- `nanobot/channels/telegram.py`

### 类结构

```
TelegramChannel(BaseChannel)
├── name = "telegram"
├── BOT_COMMANDS: [/start, /new, /help]
├── _app: Application | None          # python-telegram-bot Application
├── _chat_ids: dict[str, int]          # sender_id → chat_id 映射（用于回复）
└── _typing_tasks: dict[str, asyncio.Task]  # chat_id → typing 循环 task
```

### 初始化参数

```python
def __init__(
    self,
    config: TelegramConfig,
    bus: MessageBus,
    groq_api_key: str = "",   # 用于语音转文字
):
```

### 启动流程（start()）

1. 检查 `config.token` 是否配置
2. 创建 `HTTPXRequest`（连接池 16，超时 30s）
3. 构建 `Application`，可选 proxy
4. 注册 error handler
5. 注册 CommandHandler：`/start` → `_on_start`，`/new` → `_forward_command`，`/help` → `_on_help`
6. 注册 MessageHandler：TEXT | PHOTO | VOICE | AUDIO | Document.ALL（排除 COMMAND）
7. `app.initialize()` + `app.start()`
8. 获取 bot 信息，注册命令菜单（`set_my_commands`）
9. `updater.start_polling(allowed_updates=["message"], drop_pending_updates=True)`
10. `while self._running: await asyncio.sleep(1)` 保持运行

### 消息接收流程（_on_message）

```
收到 Update
├── 提取 user、chat_id、sender_id（格式："{user_id}|{username}" 或 "{user_id}"）
├── 存储 chat_id 映射
├── 构建 content_parts 和 media_paths
│   ├── message.text → content_parts
│   ├── message.caption → content_parts
│   └── 媒体处理（photo/voice/audio/document）：
│       ├── 下载到 ~/.nanobot/media/{file_id[:16]}{ext}
│       ├── voice/audio → GroqTranscriptionProvider 转文字
│       │   ├── 成功 → "[transcription: ...]"
│       │   └── 失败 → "[voice: path]"
│       └── 图片/文件 → "[image: path]" / "[file: path]"
├── 启动 typing 指示器（_start_typing）
└── 调用 _handle_message() → 发布到 Bus
```

**metadata 字段**（Telegram 特有）：
```python
{
    "message_id": int,
    "user_id": int,
    "username": str | None,
    "first_name": str,
    "is_group": bool,
}
```

### 消息发送流程（send()）

```
OutboundMessage
├── 停止 typing 指示器
├── 解析 chat_id 为 int
├── 可选：构建 ReplyParameters（若 config.reply_to_message=True 且 metadata["message_id"] 存在）
├── 发送媒体（media 列表）：
│   ├── 根据扩展名推断类型（photo/voice/audio/document）
│   └── 打开文件 → 调用对应 bot.send_* 方法
└── 发送文本（content）：
    ├── 按 4000 字符分段（_split_message）
    └── 每段：
        ├── _markdown_to_telegram_html 转换
        ├── bot.send_message(parse_mode="HTML")
        └── 失败时 fallback → 纯文本发送
```

### Markdown → Telegram HTML 转换（_markdown_to_telegram_html）

处理顺序（关键：代码块先保护再恢复）：
1. 提取代码块（\`\`\`...```）→ 占位符 `\x00CB{i}\x00`
2. 提取行内代码（\`...\`）→ 占位符 `\x00IC{i}\x00`
3. 标题（`#...`）→ 纯文本
4. 引用（`> ...`）→ 纯文本
5. HTML 实体转义（`&` `<` `>`）
6. 链接（`[text](url)`）→ `<a href="url">text</a>`
7. 粗体（`**` 或 `__`）→ `<b>`
8. 斜体（`_..._`，避免 `some_var_name` 误匹配）→ `<i>`
9. 删除线（`~~`）→ `<s>`
10. 无序列表（`- ` 或 `* `）→ `• `
11. 恢复行内代码 → `<code>...</code>`（内容 HTML 转义）
12. 恢复代码块 → `<pre><code>...</code></pre>`（内容 HTML 转义）

### 消息分段（_split_message）

- 阈值：4000 字符
- 切分优先级：`\n` → ` `（空格）→ 强制截断
- 去除分割点前后空白

### Typing 指示器

```python
# 每 4 秒发送一次 "typing" action，直到 task 被 cancel
async def _typing_loop(self, chat_id: str):
    while self._app:
        await self._app.bot.send_chat_action(chat_id=int(chat_id), action="typing")
        await asyncio.sleep(4)
```

- `_start_typing(chat_id)` → 取消旧 task → 创建新 task
- `_stop_typing(chat_id)` → 弹出并 cancel task
- 收到消息时 start，发送回复时 stop

---

## 四、通道管理器（ChannelManager）

### 文件位置
- `nanobot/channels/manager.py`

### 支持的通道（按优先级检查）

| 通道 | 类 | 模块 |
|------|-----|------|
| Telegram | TelegramChannel | channels.telegram |
| WhatsApp | WhatsAppChannel | channels.whatsapp |
| Discord | DiscordChannel | channels.discord |
| Feishu | FeishuChannel | channels.feishu |
| Mochat | MochatChannel | channels.mochat |
| DingTalk | DingTalkChannel | channels.dingtalk |
| Email | EmailChannel | channels.email |
| Slack | SlackChannel | channels.slack |
| QQ | QQChannel | channels.qq |

所有通道均延迟导入（`try/except ImportError`），缺少依赖不影响其他通道。

### 核心方法

```python
async def start_all(self) -> None:
    # 1. 创建 outbound dispatch task（_dispatch_outbound）
    # 2. 为每个 channel 创建启动 task
    # 3. asyncio.gather 等待所有

async def _dispatch_outbound(self) -> None:
    # 无限循环，wait_for 超时 1s
    # 过滤 progress/tool_hint 消息（根据 config.channels.send_progress/send_tool_hints）
    # 根据 msg.channel 路由到对应 channel.send()
```

**progress 过滤规则**：
- `msg.metadata._progress=True` 且 `_tool_hint=True` → 检查 `config.channels.send_tool_hints`
- `msg.metadata._progress=True` 且非 tool_hint → 检查 `config.channels.send_progress`

---

## 五、配置系统

### 文件位置
- `nanobot/config/schema.py` — Pydantic 模型
- `nanobot/config/loader.py` — 加载/保存/迁移

### 配置文件路径
- `~/.nanobot/config.json`（默认）

### 根配置结构（Config extends BaseSettings）

```
Config
├── agents: AgentsConfig
│   └── defaults: AgentDefaults
│       ├── workspace: str = "~/.nanobot/workspace"
│       ├── model: str = "anthropic/claude-opus-4-5"
│       ├── max_tokens: int = 8192
│       ├── temperature: float = 0.1
│       ├── max_tool_iterations: int = 40
│       └── memory_window: int = 100
│
├── channels: ChannelsConfig
│   ├── send_progress: bool = True      # 流式进度发送到通道
│   ├── send_tool_hints: bool = False    # 工具调用提示发送到通道
│   ├── telegram: TelegramConfig
│   ├── whatsapp: WhatsAppConfig
│   ├── discord: DiscordConfig
│   ├── feishu: FeishuConfig
│   ├── mochat: MochatConfig
│   ├── dingtalk: DingTalkConfig
│   ├── email: EmailConfig
│   ├── slack: SlackConfig
│   └── qq: QQConfig
│
├── providers: ProvidersConfig
│   ├── custom: ProviderConfig          # 任意 OpenAI 兼容端点
│   ├── anthropic: ProviderConfig
│   ├── openai: ProviderConfig
│   ├── openrouter: ProviderConfig
│   ├── deepseek: ProviderConfig
│   ├── groq: ProviderConfig            # 也用于语音转文字
│   ├── zhipu: ProviderConfig
│   ├── dashscope: ProviderConfig       # 阿里云通义
│   ├── vllm: ProviderConfig
│   ├── gemini: ProviderConfig
│   ├── moonshot: ProviderConfig
│   ├── minimax: ProviderConfig
│   ├── aihubmix: ProviderConfig
│   ├── siliconflow: ProviderConfig
│   ├── volcengine: ProviderConfig
│   ├── openai_codex: ProviderConfig    # OAuth
│   └── github_copilot: ProviderConfig # OAuth
│
├── gateway: GatewayConfig
│   ├── host: str = "0.0.0.0"
│   ├── port: int = 18790
│   └── heartbeat: HeartbeatConfig
│       ├── enabled: bool = True
│       └── interval_s: int = 1800     # 30分钟
│
└── tools: ToolsConfig
    ├── web: WebToolsConfig
    │   └── search: WebSearchConfig
    │       ├── api_key: str = ""      # Brave Search API key
    │       └── max_results: int = 5
    ├── exec: ExecToolConfig
    │   └── timeout: int = 60
    ├── restrict_to_workspace: bool = False
    └── mcp_servers: dict[str, MCPServerConfig]
        └── MCPServerConfig:
            ├── command: str = ""      # stdio 模式
            ├── args: list[str]
            ├── env: dict[str, str]
            ├── url: str = ""          # HTTP 模式
            ├── headers: dict[str, str]
            └── tool_timeout: int = 30
```

### TelegramConfig 完整字段

```python
class TelegramConfig(Base):
    enabled: bool = False
    token: str = ""                       # BotFather token
    allow_from: list[str] = []            # 允许的 user ID 或 username
    proxy: str | None = None              # "http://..." 或 "socks5://..."
    reply_to_message: bool = False        # 是否引用原消息回复
```

### ProviderConfig 字段

```python
class ProviderConfig(Base):
    api_key: str = ""
    api_base: str | None = None
    extra_headers: dict[str, str] | None = None  # 如 AiHubMix 的 APP-Code
```

### 配置格式约定

- 基类 `Base` 使用 `alias_generator=to_camel`，支持 camelCase 和 snake_case
- 环境变量：`NANOBOT_` 前缀，`__` 作为嵌套分隔符（如 `NANOBOT_PROVIDERS__ANTHROPIC__API_KEY`）

### 配置加载流程

```python
def load_config(config_path: Path | None = None) -> Config:
    path = config_path or get_config_path()
    if path.exists():
        data = json.load(f)
        data = _migrate_config(data)     # 迁移旧格式
        return Config.model_validate(data)
    return Config()                      # 返回默认配置
```

### 配置迁移（_migrate_config）

- `tools.exec.restrictToWorkspace` → `tools.restrictToWorkspace`

### 提供商匹配逻辑（Config._match_provider）

1. 模型名含显式前缀（如 `anthropic/claude-*`）→ 精确匹配提供商
2. 按关键字模糊匹配（PROVIDERS registry 顺序）
3. Fallback：第一个有 api_key 的 gateway 提供商
4. OAuth 提供商不参与 fallback

---

## 六、会话管理（SessionManager）

### 文件位置
- `nanobot/session/manager.py`

### Session 数据类

```python
@dataclass
class Session:
    key: str                          # channel:chat_id
    messages: list[dict[str, Any]]    # 消息历史（只追加）
    created_at: datetime
    updated_at: datetime
    metadata: dict[str, Any]
    last_consolidated: int            # 已整合到文件的消息数量
```

**关键设计**：消息只追加（append-only），整合（consolidation）将摘要写入 MEMORY.md/HISTORY.md，不修改 messages 列表本身。

### get_history() 逻辑

```python
def get_history(self, max_messages: int = 500) -> list[dict]:
    unconsolidated = self.messages[self.last_consolidated:]
    sliced = unconsolidated[-max_messages:]
    # 对齐到第一个 user 消息（避免孤立的 tool_result blocks）
    for i, m in enumerate(sliced):
        if m.get("role") == "user":
            sliced = sliced[i:]
            break
    # 只返回 role、content 及 tool_calls/tool_call_id/name
    ...
```

### 存储格式（JSONL）

```jsonl
{"_type": "metadata", "key": "telegram:12345", "created_at": "...", "updated_at": "...", "metadata": {}, "last_consolidated": 0}
{"role": "user", "content": "hello", "timestamp": "..."}
{"role": "assistant", "content": "hi", "timestamp": "..."}
```

### SessionManager 关键方法

| 方法 | 说明 |
|------|------|
| `get_or_create(key)` | 从缓存或磁盘加载，不存在则创建新会话 |
| `save(session)` | 完整重写 JSONL 文件 |
| `invalidate(key)` | 从内存缓存删除（不删磁盘） |
| `list_sessions()` | 扫描 sessions/*.jsonl，只读元数据行，按 updated_at 降序 |

**路径**：
- 当前：`{workspace}/sessions/{safe_key}.jsonl`
- 旧版（自动迁移）：`~/.nanobot/sessions/{safe_key}.jsonl`

---

## 七、启动流程（完整链路）

### 入口文件

```
python -m nanobot  →  nanobot/__main__.py  →  cli/commands.py app()
```

### CLI 命令

| 命令 | 说明 |
|------|------|
| `nanobot onboard` | 初始化配置和 workspace |
| `nanobot agent [-m "..."]` | 直接与 Agent 交互（单次或交互模式） |
| `nanobot gateway` | 启动完整 gateway（含通道监听） |
| `nanobot channels status` | 显示通道状态 |
| `nanobot channels login` | 扫码登录 WhatsApp |
| `nanobot cron list/add/remove/enable/run` | 定时任务管理 |
| `nanobot status` | 显示配置和 API key 状态 |
| `nanobot provider login <name>` | OAuth 登录 |

### gateway 命令启动链路

```
nanobot gateway
│
├─ load_config()                          # 加载 ~/.nanobot/config.json
├─ MessageBus()                           # 创建消息总线（两个 asyncio.Queue）
├─ _make_provider(config)                 # 根据 model 名称创建 LLM 提供商
│   ├─ openai_codex → OpenAICodexProvider
│   ├─ custom → CustomProvider
│   └─ 其他 → LiteLLMProvider
├─ SessionManager(workspace_path)         # 会话管理器
├─ CronService(cron_store_path)           # 定时任务服务
├─ AgentLoop(bus, provider, ...)          # 创建 Agent（核心循环）
│   ├─ workspace
│   ├─ model / temperature / max_tokens
│   ├─ max_iterations / memory_window
│   ├─ brave_api_key（web search）
│   ├─ exec_config
│   ├─ cron_service
│   ├─ restrict_to_workspace
│   ├─ session_manager
│   ├─ mcp_servers
│   └─ channels_config
├─ CronService.on_job = on_cron_job       # 绑定 cron 回调 → agent.process_direct()
├─ ChannelManager(config, bus)            # 通道管理器（_init_channels 自动按配置初始化）
│   └─ TelegramChannel(telegram_config, bus, groq_api_key)  # 如果 enabled
├─ HeartbeatService(...)                  # 心跳服务（每 30 分钟）
│
└─ asyncio.run(run())
    ├─ await cron.start()
    ├─ await heartbeat.start()
    └─ await asyncio.gather(
           agent.run(),          # Agent 从 inbound queue 消费
           channels.start_all()  # 通道启动 + outbound dispatcher
       )
```

### agent 命令启动链路（简化）

```
nanobot agent -m "hello"
│
├─ load_config()
├─ MessageBus()
├─ _make_provider(config)
├─ CronService(store_path)
├─ AgentLoop(bus, provider, ...)        # 无 session_manager
├─ agent_loop.process_direct(message)  # 直接处理（不经 bus）
└─ 打印响应
```

交互模式（无 -m 参数）：
```
├─ agent_loop.run() 作为 bus_task
├─ _consume_outbound() 消费输出
└─ prompt_toolkit 读取用户输入 → bus.publish_inbound()
```

---

## 八、重要设计模式

### 1. 通道隔离
每个通道独立运行，通过 Bus 与 Agent 交换消息，通道失败不影响其他通道。

### 2. 延迟导入
通道类在 `_init_channels` 中按需导入，可选依赖缺失时优雅降级（`ImportError` 捕获后继续）。

### 3. 媒体文件处理
媒体下载到 `~/.nanobot/media/`，路径通过 InboundMessage.media 传递给 Agent，Agent 可直接读取本地文件。

### 4. sender_id 格式
Telegram 特有：`"{user_id}|{username}"` 或 `"{user_id}"`，ACL 检查时逐段匹配，支持按 ID 或 username 白名单。

### 5. Typing 指示器
收到消息立即 start，发出回复时 stop，避免长时间无反馈。每次收到新消息会重置计时器。

### 6. 消息分段
超过 4000 字符按换行/空格切分，每段独立发送，避免 Telegram API 限制。

### 7. HTML fallback
先尝试 Telegram HTML 格式，失败则 fallback 到纯文本，确保消息始终可发出。

---

## 九、与我们项目的差异点

| 特性 | Nanobot | 我们的项目 |
|------|---------|-----------|
| 消息总线 | asyncio.Queue（内存） | 待实现 |
| 配置格式 | JSON + Pydantic | YAML + dataclass |
| 会话存储 | JSONL 文件 | 待对比 |
| 通道管理 | ChannelManager 统一管理 | 待实现 |
| Telegram 通道 | 完整实现（polling） | 待实现 |
| 媒体处理 | 下载到本地 | 待实现 |
| 语音转文字 | Groq API | 待实现 |

---

## 十、关键实现细节（用于迁移参考）

### 需要的依赖
```
python-telegram-bot[ext]  # Telegram bot SDK
httpx                     # HTTP 客户端（连接池配置）
pydantic                  # 配置验证
pydantic-settings         # 环境变量支持
loguru                    # 日志
typer                     # CLI
rich                      # 终端 UI
prompt_toolkit            # 交互式输入
```

### Telegram 连接池配置（重要）
```python
req = HTTPXRequest(
    connection_pool_size=16,
    pool_timeout=5.0,
    connect_timeout=30.0,
    read_timeout=30.0
)
```

### 代理支持
```python
builder = builder.proxy(config.proxy).get_updates_proxy(config.proxy)
# 支持 "http://..." 和 "socks5://..."
```

### drop_pending_updates
```python
await app.updater.start_polling(
    allowed_updates=["message"],
    drop_pending_updates=True  # 启动时忽略积压消息
)
```
