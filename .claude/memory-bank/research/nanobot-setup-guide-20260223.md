# 调研报告: NanoBot 安装与项目初始化完整指南

**日期**: 2026-02-23
**任务**: 调研 NanoBot (HKUDS/nanobot) 的安装方式、项目初始化、配置格式、Skill 注册、Telegram 配置、多 LLM Provider 配置及 Agent Loop 扩展

---

## 调研摘要

NanoBot 在 PyPI 上的包名为 `nanobot-ai`（不是 `nanobot`），通过 `pip install nanobot-ai` 安装。初始化使用 `nanobot onboard` 命令，自动在 `~/.nanobot/config.json` 创建配置文件并初始化 workspace 模板文件。配置完全使用 JSON 格式（不是 YAML/env），支持 camelCase 和 snake_case 双格式。自定义 Skill 只需在 workspace 下创建目录 + `SKILL.md` 文件即可，无需代码。

---

## 一、安装方式

### PyPI 正式包名

```
pip install nanobot-ai
```

**注意**：PyPI 包名是 `nanobot-ai`，不是 `nanobot`。

### 三种安装方式

**方式 1：PyPI 稳定版（推荐生产环境）**
```bash
pip install nanobot-ai
```

**方式 2：uv 工具安装（推荐开发者）**
```bash
uv tool install nanobot-ai
```

**方式 3：源码开发模式（推荐贡献者）**
```bash
git clone https://github.com/HKUDS/nanobot.git
cd nanobot
pip install -e .
```

### 版本与依赖

- 当前版本：`0.1.4.post1`
- 要求 Python：`>= 3.11`（不是 3.10，必须 3.11+）
- 构建系统：Hatchling
- 许可证：MIT

**核心依赖（26个）**：
| 类别 | 依赖 |
|------|------|
| CLI | typer |
| LLM | litellm（统一多模型访问） |
| 数据验证 | pydantic, pydantic-settings |
| 通信 | websockets, httpx, python-telegram-bot, slack-sdk, dingtalk-stream, qq-botpy |
| 工具 | loguru, rich, croniter, prompt-toolkit, mcp, json-repair |
| 其他 | oauth-cli-kit, readability-lxml, python-socketio, msgpack |

---

## 二、项目初始化

### 唯一初始化命令

```bash
nanobot onboard
```

该命令执行：
1. 创建配置文件：`~/.nanobot/config.json`
2. 创建 workspace 目录（默认 `~/.nanobot/workspace`）
3. 生成模板文件：`AGENTS.md`、`SOUL.md`、`USER.md`、`HEARTBEAT.md`
4. 如果已有配置，提示选择覆盖或保留现有值

初始化后验证状态：
```bash
nanobot status
# 显示：config 路径、workspace 路径、当前模型、所有 Provider 的 API Key 可用性
```

---

## 三、CLI 命令完整列表

```bash
# 核心命令
nanobot onboard              # 初始化配置和 workspace
nanobot gateway              # 启动网关（加载消息总线+所有Channel+Cron+Heartbeat）
nanobot agent                # 直接与 Agent 对话（交互式模式）
nanobot agent -m "你好"      # 单次消息模式
nanobot agent -s "my-session" # 指定会话 ID
nanobot status               # 查看配置状态

# gateway 参数
nanobot gateway --port 18790  # 指定端口（默认 18790）
nanobot gateway --verbose     # 开启 debug 日志

# Channel 命令
nanobot channels status       # 查看所有 Channel 配置状态
nanobot channels login        # WhatsApp 设备登录（QR码）

# Cron 命令
nanobot cron list             # 列出所有定时任务
nanobot cron list --all       # 包含已禁用任务
nanobot cron add --name "daily-report" --message "生成今日报告" --cron "0 9 * * *" --tz "Asia/Shanghai"
nanobot cron add --every 3600 --message "每小时检查" --deliver --channel telegram --to "user_id"
nanobot cron remove <job_id>
nanobot cron enable <job_id>
nanobot cron enable --disable <job_id>
nanobot cron run <job_id>     # 立即执行
nanobot cron run --force <job_id>  # 强制执行（即使已禁用）

# Provider 命令
nanobot provider login openai-codex     # OAuth 登录（Codex）
nanobot provider login github-copilot   # OAuth 登录（Copilot）
```

---

## 四、配置文件格式

### 位置

```
~/.nanobot/config.json
```

### 完整配置结构

```json
{
  "agents": {
    "defaults": {
      "workspace": "~/.nanobot/workspace",
      "model": "anthropic/claude-opus-4-5",
      "maxTokens": 8192,
      "temperature": 0.7,
      "maxToolIterations": 20,
      "memoryWindow": 50
    }
  },
  "providers": {
    "anthropic": {
      "apiKey": "sk-ant-xxx"
    },
    "gemini": {
      "apiKey": "AIzaXXX"
    },
    "openrouter": {
      "apiKey": "sk-or-v1-xxx"
    },
    "openai": {
      "apiKey": "sk-proj-xxx"
    },
    "deepseek": {
      "apiKey": "sk-xxx"
    },
    "groq": {
      "apiKey": "gsk_xxx"
    }
  },
  "channels": {
    "telegram": {
      "enabled": true,
      "token": "YOUR_BOT_TOKEN",
      "allowFrom": ["YOUR_TELEGRAM_USER_ID"],
      "proxy": null,
      "replyToMessage": false
    }
  },
  "tools": {
    "restrictToWorkspace": false,
    "exec": {
      "timeout": 60
    },
    "web": {
      "braveApiKey": "YOUR_BRAVE_KEY",
      "maxResults": 5
    },
    "mcpServers": {}
  },
  "gateway": {
    "host": "0.0.0.0",
    "port": 18790
  }
}
```

### 字段命名规则

所有字段支持 **camelCase 和 snake_case 双写法**（Pydantic alias_generator 实现）：
- `maxTokens` == `max_tokens`
- `apiKey` == `api_key`
- `allowFrom` == `allow_from`

---

## 五、配置 Telegram Channel

### 步骤

**步骤 1：创建 Bot**
- 在 Telegram 中找到 `@BotFather`
- 发送 `/newbot`，按提示设置 bot 名称和用户名
- 复制返回的 Token（格式：`123456789:ABCdefGHI...`）

**步骤 2：获取自己的 User ID**
- 在 Telegram 中找到 `@userinfobot`，发送任意消息
- 或查看 Telegram 设置中的个人 ID（数字格式）

**步骤 3：更新配置**
```json
{
  "channels": {
    "telegram": {
      "enabled": true,
      "token": "123456789:ABCdefGHI...",
      "allowFrom": ["987654321"],
      "proxy": null,
      "replyToMessage": false
    }
  }
}
```

**字段说明**：
- `allowFrom`：白名单用户 ID 列表，空列表 `[]` 表示允许所有人
- `proxy`：代理地址（如 `"socks5://127.0.0.1:1080"`），可选
- `replyToMessage`：回复时是否引用原消息，默认 `false`

**步骤 4：启动网关**
```bash
nanobot gateway
```

---

## 六、配置多个 LLM Provider

### 模型命名规则（litellm 格式）

```
{provider}/{model-name}
```

示例：
- `anthropic/claude-opus-4-5`（Claude）
- `anthropic/claude-sonnet-4-5`
- `gemini/gemini-2.0-flash-exp`（Gemini）
- `gemini/gemini-1.5-pro`
- `openrouter/anthropic/claude-opus-4-5`（通过 OpenRouter）
- `groq/llama-3.3-70b-versatile`

### Claude + Gemini 双 Provider 配置

```json
{
  "providers": {
    "anthropic": {
      "apiKey": "sk-ant-api03-xxx"
    },
    "gemini": {
      "apiKey": "AIzaSyXXX"
    }
  },
  "agents": {
    "defaults": {
      "model": "anthropic/claude-opus-4-5"
    }
  }
}
```

### Provider 匹配逻辑

框架通过 `_match_provider()` 方法按以下优先级自动匹配 Provider：
1. 模型名称的显式前缀（如 `anthropic/...`）
2. 关键词匹配（如模型名含 `claude` → Anthropic）
3. 网关回退

### 支持的全部 Provider

| Provider | 配置键 | 模型前缀示例 |
|----------|--------|-------------|
| Anthropic | `anthropic` | `anthropic/claude-*` |
| OpenAI | `openai` | `openai/gpt-*` |
| OpenRouter | `openrouter` | `openrouter/*` |
| Gemini | `gemini` | `gemini/gemini-*` |
| DeepSeek | `deepseek` | `deepseek/*` |
| Groq | `groq` | `groq/*` |
| vLLM | `vllm` | `vllm/*` |
| Ollama | `ollama` | `ollama/*` |
| SiliconFlow | `siliconflow` | - |
| 阿里云通义 | `dashscope` / `qwen` | - |
| 月之暗面 | `moonshot` | - |
| 智谱 | `zhipu` | - |
| VolcEngine | `volcengine` | - |
| MiniMax | `minimax` | - |
| AiHubMix | `aihubmix` | - |
| OpenAI兼容 | 自定义 `apiBase` | - |

---

## 七、注册自定义 Skill

### Skill 目录结构

```
{workspace}/skills/
└── my-skill/
    ├── SKILL.md          # 必须（Skill 定义文件）
    ├── scripts/          # 可选（可执行脚本）
    ├── references/       # 可选（参考文档）
    └── assets/           # 可选（模板/素材）
```

**工作区默认位置**：`~/.nanobot/workspace/skills/`

### SKILL.md 格式

```markdown
---
name: my-skill
description: 一句话描述这个 Skill 的作用（Agent 用于决定是否加载）
always: false
metadata: '{"requires": {"bins": ["curl", "jq"], "env": ["MY_API_KEY"]}}'
---

# My Skill 标题

## 使用场景

[描述 Agent 在什么情况下应该使用这个 Skill]

## 操作步骤

1. [步骤 1 - 具体指令给 Agent]
2. [步骤 2]

## 示例

```bash
# 具体的命令示例
curl -s "https://api.example.com/data"
```

## 注意事项

- [注意点 1]
```

### 关键 frontmatter 字段

| 字段 | 类型 | 说明 |
|------|------|------|
| `name` | string | Skill 标识符（目录名即可） |
| `description` | string | 摘要，Agent 加载索引时看到的内容 |
| `always` | boolean | `true` = 始终注入全文；`false` = 按需加载（默认） |
| `metadata` | JSON string | 依赖声明：`bins`（需要的可执行文件）、`env`（需要的环境变量） |

### 加载优先级

1. `{workspace}/skills/` 下的 Skill（最高优先级，会覆盖同名内置 Skill）
2. `nanobot/skills/`（内置 Skill，随包安装）

### 内置 Skill 列表

| Skill | 功能 |
|-------|------|
| `weather` | wttr.in + Open-Meteo 天气查询（无需 API Key） |
| `github` | GitHub CLI 集成 |
| `memory` | 记忆操作 |
| `cron` | 定时任务管理 |
| `summarize` | URL/文件/YouTube 摘要 |
| `tmux` | tmux 远程控制 |
| `clawhub` | ClawHub 注册表搜索和安装社区 Skill |
| `skill-creator` | 让 Agent 自动创建新 Skill |

### Skill 设计原则（来自官方 skill-creator）

1. **简洁为王**：Context window 是公共资源，Skill 只提供 Agent 不知道的新知识
2. **渐进式披露**：先加载摘要，需要时才加载全文和脚本
3. **脚本 vs 文本**：固定流程用脚本，灵活决策用文本指导
4. **避免冗余文档**：只保留直接支持 Skill 功能的内容

---

## 八、Agent Loop 入口与扩展

### 启动 Agent Loop 的两种方式

**方式 1：通过 gateway 启动（生产环境）**
```bash
nanobot gateway  # 启动完整系统：MessageBus + AgentLoop + Channels + Cron + Heartbeat
```

**方式 2：通过 agent 命令直接交互（开发/测试）**
```bash
nanobot agent               # 交互式 CLI 对话
nanobot agent -m "执行任务"  # 单次消息
```

### AgentLoop 类接口

```python
from nanobot.agent.loop import AgentLoop
from nanobot.bus.queue import MessageBus

# 构造函数参数
loop = AgentLoop(
    bus=bus,                          # MessageBus 实例（必须）
    provider=provider,                # LLMProvider 实例（必须）
    workspace=Path("~/.nanobot/workspace"),  # 工作目录
    model="anthropic/claude-opus-4-5",       # 模型名称
    max_iterations=20,                # 最大工具迭代次数
    temperature=0.7,                  # 温度
    max_tokens=8192,                  # 最大 token
    memory_window=50,                 # 记忆窗口
    brave_api_key=None,               # Brave 搜索 API Key
    exec_config=None,                 # Shell 执行配置
    restrict_to_workspace=False,      # 是否限制文件访问到 workspace
    mcp_servers={},                   # MCP 服务器配置（懒加载）
)

# 入口方法
await loop.run()  # 主循环（消费消息总线）

# 直接调用（bypass message bus，用于 CLI/cron）
result = await loop.process_direct(
    content="执行任务",
    session="cli:direct"
)
```

### 扩展方式

**方式 1：注册自定义工具**
```python
# 创建工具类（实现 Tool 接口）
class MyTool:
    name = "my_tool"
    description = "工具描述"

    async def execute(self, **kwargs):
        return {"result": "..."}

# 注册到 AgentLoop
loop.tools.register(MyTool())
```

**方式 2：接入 MCP 服务器**
```json
{
  "tools": {
    "mcpServers": {
      "my-mcp": {
        "command": "python",
        "args": ["-m", "my_mcp_server"],
        "env": {"API_KEY": "xxx"}
      }
    }
  }
}
```

MCP 服务器在 AgentLoop 首次需要时懒加载连接（`_connect_mcp()`）。

**方式 3：覆盖记忆整合逻辑**
通过继承 `MemoryStore` 并重写 `consolidate()` 方法。

**方式 4：Skills as Markdown（最简单）**
在 workspace 下创建自定义 SKILL.md，无需修改代码。

---

## 九、Workspace 文件结构

初始化后生成的模板文件：

```
~/.nanobot/workspace/
├── AGENTS.md          # Agent 行为规范（系统提示的一部分）
├── SOUL.md            # Agent 个性/价值观定义
├── USER.md            # 用户偏好和背景信息
├── TOOLS.md           # 工具使用规范
├── IDENTITY.md        # Agent 身份定义
├── MEMORY.md          # 长期记忆（LLM 自动更新）
├── HEARTBEAT.md       # 定期任务列表（每30分钟检查）
├── HISTORY.md         # 对话历史摘要（append-only）
└── skills/            # 自定义 Skill 目录
    └── {skill-name}/
        └── SKILL.md
```

### HEARTBEAT.md 格式

```markdown
# Heartbeat Tasks

## Active Tasks

- 每天早上检查邮件并摘要
- 每30分钟检查系统资源使用情况
```

**规则**：
- 空文件或无有效任务 → Agent 跳过心跳
- 已完成任务移到其他区域或删除（不要加 `[x]` 勾选语法，会被过滤）
- 任务触发时以 system message 形式注入 Agent Loop

---

## 十、快速启动完整示例

```bash
# 1. 安装
pip install nanobot-ai

# 2. 初始化
nanobot onboard

# 3. 编辑配置（~/.nanobot/config.json）
cat > ~/.nanobot/config.json << 'EOF'
{
  "agents": {
    "defaults": {
      "model": "anthropic/claude-opus-4-5",
      "maxTokens": 8192,
      "temperature": 0.7,
      "maxToolIterations": 20,
      "memoryWindow": 50
    }
  },
  "providers": {
    "anthropic": {
      "apiKey": "sk-ant-xxx"
    },
    "gemini": {
      "apiKey": "AIzaXXX"
    }
  },
  "channels": {
    "telegram": {
      "enabled": true,
      "token": "YOUR_BOT_TOKEN",
      "allowFrom": ["YOUR_USER_ID"]
    }
  },
  "tools": {
    "restrictToWorkspace": false
  }
}
EOF

# 4. 验证配置
nanobot status

# 5. 测试 Agent
nanobot agent -m "你好，介绍一下你自己"

# 6. 启动完整服务（包含 Telegram 通道）
nanobot gateway

# 7. 添加自定义 Skill
mkdir -p ~/.nanobot/workspace/skills/my-skill
cat > ~/.nanobot/workspace/skills/my-skill/SKILL.md << 'EOF'
---
name: my-skill
description: 自定义功能描述
always: false
---

# My Skill

[给 Agent 的指令...]
EOF
```

---

## 参考资料

- [HKUDS/nanobot GitHub 仓库](https://github.com/HKUDS/nanobot)
- [nanobot-ai PyPI 页面](https://pypi.org/project/nanobot-ai/)
- [pyproject.toml 源码](https://github.com/HKUDS/nanobot/blob/main/pyproject.toml)
- [nanobot/cli/commands.py 源码](https://github.com/HKUDS/nanobot/blob/main/nanobot/cli/commands.py)
- [nanobot/config/schema.py 源码](https://github.com/HKUDS/nanobot/blob/main/nanobot/config/schema.py)
- [nanobot/agent/loop.py 源码](https://github.com/HKUDS/nanobot/blob/main/nanobot/agent/loop.py)
- [nanobot/agent/skills.py 源码](https://github.com/HKUDS/nanobot/blob/main/nanobot/agent/skills.py)
- [NanoBot 官方网站](https://nanobot.club/)
