# 调研报告: NanoBot 框架架构与扩展机制

**日期**: 2026-02-23
**任务**: 调研 NanoBot AI Agent 框架的架构、核心模块、扩展机制及 Telegram 集成方式

---

## 调研摘要

NanoBot（HKUDS/nanobot）是香港大学数据智能实验室开发的超轻量级个人 AI Agent 框架，核心代码约 3,862 行 Python，比 OpenClaw（前身 Clawdbot）少 99%。采用事件驱动的双队列消息总线架构，支持 9+ 通道（Telegram/Discord/WhatsApp/飞书等）、15+ LLM Provider，具备持久化记忆、后台 Subagent、定时任务（Heartbeat/Cron）等完整 Agent 能力。项目已在 GitHub 公开，MIT 许可证。

**GitHub**: https://github.com/HKUDS/nanobot

---

## 现有代码分析

### 项目目录结构

```
nanobot/
├── agent/
│   ├── loop.py        # Agent 主循环（核心编排器）
│   ├── context.py     # 上下文构建器
│   ├── memory.py      # 记忆管理
│   ├── skills.py      # Skills 加载器
│   ├── subagent.py    # 后台 Subagent
│   ├── tools/         # 内置工具（文件/Shell/搜索/MCP等）
│   └── __init__.py
├── bus/
│   ├── queue.py       # 消息总线（双向 asyncio.Queue）
│   └── events.py      # 事件类型定义
├── channels/
│   ├── base.py        # BaseChannel 抽象类
│   ├── telegram.py    # Telegram 通道（~450行）
│   ├── discord.py     # Discord 通道
│   ├── whatsapp.py    # WhatsApp 通道
│   ├── feishu.py      # 飞书通道
│   ├── slack.py       # Slack 通道
│   ├── dingtalk.py    # 钉钉通道
│   ├── email.py       # Email 通道
│   ├── mochat.py      # Mochat 通道
│   ├── qq.py          # QQ 通道
│   └── manager.py     # 通道管理器
├── providers/         # LLM Provider 抽象层
├── session/           # 会话状态管理
├── cron/
│   ├── service.py     # Cron 调度服务
│   └── types.py       # 类型定义
├── heartbeat/
│   └── service.py     # Heartbeat 服务
├── skills/            # 内置 Skills（SKILL.md 格式）
│   ├── clawhub/       # ClawHub 注册表搜索
│   ├── cron/          # 定时任务 Skill
│   ├── github/        # GitHub CLI 集成
│   ├── memory/        # 记忆操作
│   ├── skill-creator/ # 自动创建新 Skill
│   ├── summarize/     # URL/文件/YouTube 摘要
│   ├── tmux/          # tmux 远程控制
│   └── weather/       # 天气查询
├── config/            # 配置管理
├── cli/               # CLI 入口
├── utils/             # 工具函数
├── __init__.py
└── __main__.py

bridge/                # WhatsApp Node.js WebSocket 桥接层
case/                  # 示例用例（市场分析/SE工作流/日常管理）
tests/                 # 测试套件
workspace/             # Agent 工作目录（MEMORY.md/HEARTBEAT.md等）
```

### 核心配置
- 配置文件：`~/.nanobot/config.json`，集中管理凭证和偏好
- Workspace：`workspace/`，包含 `AGENTS.md`、`SOUL.md`、`USER.md`、`TOOLS.md`、`IDENTITY.md`、`MEMORY.md`、`HEARTBEAT.md`

---

## 技术架构详解

### 1. Message Bus（bus/）

**双向异步队列架构**，解耦 Channel 和 Agent 核心：

```
Channel → publish_inbound() → [inbound queue] → consume_inbound() → Agent
Agent   → publish_outbound() → [outbound queue] → consume_outbound() → Channel
```

- 使用 `asyncio.Queue` 实现，完全异步非阻塞
- 提供 `inbound_size` / `outbound_size` 监控属性
- 实现消息路由的完全解耦，各 Channel 独立运行

### 2. Agent Loop（agent/loop.py）

主循环实现"推理-工具执行-响应"的核心 REPL 循环：

```python
# 主循环
while running:
    msg = await bus.consume_inbound(timeout=1s)
    response = await _process_message(msg)
    await bus.publish_outbound(response)

# _process_message 处理三类消息：
# 1. System Messages（来自 cron/heartbeat）→ 后台执行
# 2. Slash Commands（/new, /help）→ 直接处理
# 3. 普通消息 → 完整 agent loop
```

**Agent Loop 迭代**（`_run_agent_loop()`）：
1. 构建上下文（history + memory + skills）
2. 调用 LLM（带工具定义）
3. 检查是否有工具调用
4. 顺序执行工具，收集结果
5. 将结果加入消息历史
6. 循环直到无工具调用或达到 `max_iterations`（默认 20）

**内置工具（ToolRegistry）**：
- 文件操作：read, write, edit, list
- Shell 执行
- Web 搜索 + Web Fetch
- 消息发送（send_message）
- Subagent 生成（spawn）
- Cron 调度
- MCP 服务器集成（懒加载）

### 3. Context Builder（agent/context.py）

系统提示组装顺序：
1. 身份信息（当前时间、运行时信息、工作区路径、行为准则）
2. Bootstrap 文件（AGENTS.md、SOUL.md、USER.md、TOOLS.md、IDENTITY.md）
3. 长期记忆（从 MEMORY.md 读取）
4. Always-on Skills（全文内容）
5. 可用 Skills（仅摘要，按需加载）

**消息组装**：System Prompt → 对话历史 → 当前用户消息（可含 base64 图片）

**Progressive Skill Loading 策略**：
- 所有 Skills 先提供摘要（XML 格式索引）
- Agent 需要时用 `read_file` 加载完整 Skill 内容
- 节省 context window，降低 token 成本

### 4. Channel System（channels/）

**BaseChannel 抽象接口**：
```python
class BaseChannel:
    name: str                          # 通道标识符
    async def start()                  # 启动长连接监听
    async def stop()                   # 停止释放资源
    async def send(msg: OutboundMessage)  # 发送消息

    def is_allowed(sender_id: str) -> bool  # ACL 白名单检查
    async def _handle_message(...)          # 授权验证 + 发布到 bus
```

**ACL 机制**：
- `allow_from` 配置白名单
- 空列表 = 允许所有人
- 拒绝时记录警告日志，不通知发送方

### 5. Provider System（providers/）

支持 15+ LLM Provider，配置分离（认证 vs 模型选择）：
- OpenRouter（推荐，统一多模型访问）
- Anthropic（Claude 系列）
- OpenAI（GPT 系列）
- DeepSeek
- Groq（含 Whisper 语音转文字）
- Gemini
- vLLM / Ollama（本地部署）
- 任何 OpenAI 兼容接口

添加新 Provider 只需 2 步（官方声明）。

---

## Skills 扩展机制

### Skill 格式

每个 Skill 是一个目录，包含 `SKILL.md` 文件：

```markdown
---
name: weather
description: Get weather info using wttr.in and Open-Meteo
always: false
requires:
  env: []
  bins: []
---

# Weather Skill

[Agent 使用说明...]
```

### Skill 加载机制（agent/skills.py）

```
SkillsLoader
├── 扫描 workspace/skills/（用户自定义，高优先级）
├── 扫描 nanobot/skills/（内置 Skills）
├── 检查 requires（env 变量 + 可执行文件）
├── always=true → 始终加载全文
└── always=false → 提供摘要，按需加载
```

### 创建自定义 Skill

1. 在 workspace 或 `nanobot/skills/` 下创建目录
2. 编写 `SKILL.md`（YAML frontmatter + Markdown 说明）
3. Skill 内容是给 Agent 的指令，不是代码
4. 也可使用内置 `skill-creator` Skill 让 Agent 自动创建

### ClawHub 生态

内置 `clawhub` Skill 支持从 ClawHub 注册表搜索和安装社区 Skills。

---

## Subagent 机制（agent/subagent.py）

用于处理长时后台任务，不阻塞主 Agent Loop：

```python
# 生成方式：主 Agent 调用 spawn tool
await spawn(task="分析这个代码库并生成报告", label="code-analysis")
```

**执行特性**：
- 最多 15 次迭代（主 Agent 是 20 次）
- 独立消息历史和系统提示
- 可用工具：文件操作、Shell、Web 搜索/Fetch
- **禁用工具**：`send_message`（不能直接联系用户）、`spawn`（不能创建子 Subagent）
- 结果通过 bus 发布为 system message，主 Agent 处理后摘要给用户

**防递归设计**：Subagent 不能创建 Subagent，避免无限嵌套。

---

## Heartbeat/Cron 机制

### Heartbeat（heartbeat/service.py）

**工作原理**：
1. 默认每 **30 分钟**读取 workspace 的 `HEARTBEAT.md`
2. 过滤空行、注释、未勾选的 checkbox
3. 有任务内容 → 以 system message 形式触发 Agent Loop
4. Agent 响应 `HEARTBEAT_OK` → 表示无需操作
5. 支持 `trigger_now()` 手动触发

**HEARTBEAT.md 示例**：
```markdown
- [ ] 每天早上检查邮件并摘要
- [x] 已完成：昨天的代码审查
```

### Cron（cron/service.py）

支持三种调度模式：
1. **"at"** - 一次性，指定时间戳执行
2. **"every"** - 周期性，指定间隔（如每 5 分钟）
3. **"cron"** - 标准 cron 表达式，支持时区

**任务生命周期**：
- 加入内存存储 + 持久化为 JSON
- async timer 计算最近到期任务，sleep 等待
- 到期执行 `on_job` 回调（发布 system message 到 bus）
- 更新状态（最后执行时间、下次执行时间）
- 一次性任务：`delete_after_run=true` 则删除，否则禁用

---

## 上下文与对话管理（session/ + agent/memory.py）

### 双层记忆架构

**短期（SessionManager）**：
- 按 user/channel 组合维护对话历史
- 追踪消息序列和上下文窗口
- 并发会话隔离
- 每次交互后更新，支持多轮对话

**长期（MemoryStore）**：
- `MEMORY.md`：持久化事实（LLM 压缩后的关键信息）
- `HISTORY.md`：可 grep 的时间线日志（每次对话 2-5 句摘要）

### 记忆整合流程

当未整合消息数超过 `memory_window` 时异步触发：
1. 选取需处理的旧消息
2. 格式化为带时间戳的对话记录
3. 调用 LLM + `save_memory` 工具
4. LLM 输出：
   - `history_entry`：追加到 HISTORY.md
   - `memory_update`：覆写 MEMORY.md（仅有变化时）
5. 更新 `session.last_consolidated`

**并发控制**：每会话一个 asyncio lock，防止并发整合冲突。

---

## Telegram 通道集成（channels/telegram.py，~450行）

### 实现方式
- 使用 `python-telegram-bot` 库
- **长轮询**（long polling），无需公网 IP
- 连接池 16 连接，5 秒超时（避免池耗尽）

```python
await self._app.updater.start_polling(
    allowed_updates=["message"],
    drop_pending_updates=True  # 启动时丢弃待处理消息
)
```

### 消息接收
支持多媒体类型：文本、照片、语音（Groq Whisper 转文字）、音频、文档
- 媒体文件下载到本地
- 通过 `_handle_message()` 路由到消息总线

### 消息发送
- 超过 4000 字符按行分割发送
- Markdown → Telegram HTML 转换（`_markdown_to_telegram_html()`）
- 媒体发送失败自动降级为文本通知

### 授权
- `_sender_id()` 生成用户标识（user_id + username 组合）
- BaseChannel 的白名单机制控制访问
- `/help` 命令绕过 ACL（所有用户可用）

---

## 技术方案

### 方案 A: 直接使用/参考 NanoBot

**描述**: 将 NanoBot 作为参考实现，借鉴其架构模式构建 AI 自进化系统。

**优点**:
- 4000 行代码可完整阅读，架构清晰
- 双队列消息总线天然支持多通道
- Skills as Markdown 机制极简，无需编写 Python 代码
- Subagent 防递归设计可直接借鉴
- 双层记忆（短期 session + 长期 MEMORY.md）设计成熟

**缺点**:
- Skill 系统是"指令"而非"代码"，不适合复杂工具
- Subagent 不支持嵌套，限制复杂任务分解
- 记忆依赖 LLM 整合，成本较高

**实现复杂度**: 低（参考）/ 中（集成）

### 方案 B: 扩展 NanoBot 核心

**描述**: fork NanoBot，在其基础上添加自进化系统所需功能（如代码生成 Skill、自我修改机制等）。

**优点**:
- 继承完整基础设施（通道、记忆、调度）
- 专注于自进化逻辑而非基础设施
- 活跃社区，roadmap 显示持续演进

**缺点**:
- 需跟踪上游更新
- 自进化修改可能与框架约定冲突

**实现复杂度**: 中

---

## 推荐方案

**推荐**: 方案 A（参考借鉴）

**理由**:
1. NanoBot 的消息总线 + Channel 架构直接解决多通道路由问题
2. Skills as SKILL.md 的设计可直接移植用于快速扩展能力
3. Heartbeat/Cron 机制完整，可直接参考实现定时自进化任务
4. 代码量小（<4000行），完全可读，风险低

---

## 实施建议

### 关键步骤
1. Clone NanoBot 仓库，通读 `agent/loop.py` 和 `bus/queue.py`（核心 200 行）
2. 参考 `channels/base.py` 设计 AI 自进化系统的通道接口
3. 参考 `agent/skills.py` 的 SKILL.md 格式设计自进化 Skill 机制
4. 参考 `heartbeat/service.py` 实现定时进化触发器
5. 参考 `agent/memory.py` 的双层记忆实现经验积累机制

### 风险点
- **LLM 记忆整合成本** - 缓解措施: 调整 memory_window，减少整合频率
- **Subagent 递归限制** - 缓解措施: 参考 NanoBot 防递归设计，维护任务树深度限制
- **Skills 权限边界** - 缓解措施: 自进化 Skill 需要沙箱隔离，避免破坏系统

### 依赖项
- Python 3.10+
- python-telegram-bot（Telegram 集成）
- asyncio（核心异步框架）
- croniter 或类似库（cron 表达式解析）

---

## 参考资料

- [HKUDS/nanobot GitHub 仓库](https://github.com/HKUDS/nanobot)
- [NanoBot DeepWiki 架构分析](https://deepwiki.com/lightweight-openclaw/nanobot)
- [NanoBot DataCamp 教程](https://www.datacamp.com/tutorial/nanobot-tutorial)
- [NanoBot 官方网站](https://nanobot.club/)
- [NanoBot Roadmap Discussion #431](https://github.com/HKUDS/nanobot/discussions/431)
- [NanoBot Analytics Vidhya 实战教程](https://www.analyticsvidhya.com/blog/2026/02/ai-crypto-tracker-with-nanobot/)
- [nanobot/agent/context.py 源码](https://github.com/HKUDS/nanobot/blob/main/nanobot/agent/context.py)
- [nanobot/skills 目录](https://github.com/HKUDS/nanobot/tree/main/nanobot/skills)
