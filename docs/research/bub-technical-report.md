# 调研报告: Bub 项目深度技术分析

**日期**: 2026-02-25
**任务**: 深度解析 Bub（https://github.com/PsiACE/bub）源代码架构、工作原理及 AI Native 设计理念

---

## 调研摘要

Bub 是一个以 "Tape-First"（磁带优先）为核心理念的编码 Agent CLI，构建于 `republic` 框架之上。它的核心创新在于：**同一套路由规则同时作用于用户输入和 AI 输出**，命令执行与模型推理是显式分离的两层，会话上下文以追加只读的 JSONL "磁带"（Tape）存储。项目明确声称自己是 "OpenClaw（Claude Code）核心功能的社区复刻"，目标是打造一个可自我修复、可自举（self-bootstrapping）的 Agent。

---

## 1. 项目概述

### 1.1 定位与目标

| 维度 | 描述 |
|------|------|
| 定位 | CLI-first 编码 Agent，面向真实工程工作流 |
| 口号 | "Bub it. Build it." |
| 核心主张 | 执行可预测（predictable）、可检查（inspectable）、可恢复（recoverable） |
| 自我定位 | Claude Code 核心功能的开源复刻（"OpenClaw"） |
| 自举目标 | Agent 能够修改并改进自身代码库 |

### 1.2 技术栈

| 层次 | 组件 |
|------|------|
| Python 版本 | Python 3.12+，异步优先（asyncio） |
| LLM 抽象层 | `republic`（自研框架，封装 LLM 调用和 Tape 管理） |
| LLM 默认模型 | `openrouter:qwen/qwen3-coder-next`，支持任意 OpenRouter 模型 |
| CLI 框架 | Typer + Rich + prompt-toolkit |
| 消息渠道 | python-telegram-bot（长轮询）+ discord.py |
| 调度器 | APScheduler（定时任务） |
| 配置管理 | pydantic-settings（`BUB_` 前缀环境变量 + `.env` 文件） |
| 持久化 | 自实现 JSONL FileTapeStore（线程安全，支持 fork/merge） |
| 搜索 | rapidfuzz（模糊搜索 Tape 条目） |
| 容器化 | Docker + docker-compose，tini 作为 PID 1 |
| 包管理 | uv（现代 Python 包管理器） |

---

## 2. 架构分析

### 2.1 目录结构（核心模块）

```
src/bub/
├── app/
│   ├── bootstrap.py     # 全局单例 runtime 构建
│   ├── runtime.py       # AppRuntime + SessionRuntime（多 session 管理）
│   └── jobstore.py      # APScheduler JSON 持久化 jobstore
├── core/
│   ├── agent_loop.py    # AgentLoop：一次输入的顶层协调器
│   ├── router.py        # InputRouter：用户/AI 输出的统一路由引擎
│   ├── model_runner.py  # ModelRunner：有界模型循环 + 工具调用处理
│   ├── command_detector.py
│   ├── commands.py      # 命令解析工具
│   └── types.py         # DetectedCommand 等类型定义
├── tape/
│   ├── service.py       # TapeService：高层 tape 操作（search/anchor/handoff）
│   ├── store.py         # FileTapeStore：JSONL 文件存储，fork/merge 语义
│   ├── anchors.py       # AnchorSummary 数据模型
│   └── context.py       # TapeContext：messages 序列化 / 反序列化
├── tools/
│   ├── registry.py      # ToolRegistry：统一工具注册表
│   ├── builtin.py       # 所有内置工具（bash/fs/web/schedule/tape/skills/quit）
│   ├── progressive.py   # ProgressiveToolView：按需展开工具详情
│   ├── schedule.py      # 定时任务辅助
│   └── view.py          # 渲染工具 prompt 块
├── skills/
│   ├── loader.py        # Skill 发现和加载（SKILL.md frontmatter 解析）
│   ├── view.py          # Skill compact 渲染
│   ├── discord/         # 内置 discord skill
│   ├── telegram/        # 内置 telegram skill（含 scripts/）
│   ├── gh/              # 内置 GitHub CLI skill
│   ├── skill-creator/   # 内置 skill 创建引导 skill
│   └── skill-installer/ # 内置 skill 安装器 skill
├── channels/
│   ├── base.py          # BaseChannel 抽象基类
│   ├── manager.py       # ChannelManager：多渠道协调
│   ├── runner.py        # SessionRunner：debounce + 消息聚合
│   ├── telegram.py      # TelegramChannel 适配器
│   ├── discord.py       # DiscordChannel 适配器
│   └── utils.py         # 代理解析等工具
├── cli/
│   ├── app.py           # Typer CLI 入口（chat/message/run/idle 四个命令）
│   ├── interactive.py   # InteractiveCli：prompt-toolkit 交互式 shell
│   └── render.py        # 输出渲染
├── config/
│   └── settings.py      # Settings（pydantic-settings）
└── integrations/
    └── republic_client.py # republic LLM 和 TapeStore 构建
```

### 2.2 核心数据流

```
用户输入 / Telegram 消息
        │
        ▼
  AgentLoop.handle_input(raw)
        │
        ├─ fork_tape()  [创建 tape 分叉，隔离本次会话上下文]
        │
        ├─ InputRouter.route_user(raw)
        │       │
        │       ├─ 以 "," 开头？
        │       │       ├─ Yes → 解析为内置命令 or Shell 命令
        │       │       │         成功 → 直接返回（不进入模型）
        │       │       │         失败 → 包装成 <command status="error"> 块，进入模型
        │       │       └─ No  → 自然语言，直接进入模型
        │       │
        │       └─ UserRouteResult { enter_model, model_prompt, immediate_output }
        │
        ├─ enter_model == True → ModelRunner.run(prompt)
        │       │
        │       └─ while step < max_steps:
        │               │
        │               ├─ _chat(prompt)  [调用 republic tape.run_tools_async]
        │               │       │
        │               │       ├─ 模型返回 tool_call → followup_prompt = "Continue the task."
        │               │       └─ 模型返回 text    → 进入 route_assistant
        │               │
        │               └─ InputRouter.route_assistant(text)
        │                       │
        │                       ├─ 每行检测 "," 前缀
        │                       │       命令成功 → command_block 追加，继续
        │                       │       命令失败 → command_block 追加，模型处理错误
        │                       │
        │                       ├─ next_prompt 非空 → 继续 while 循环
        │                       └─ next_prompt 为空 → 退出循环，返回 visible_text
        │
        └─ merge_tape()  [分叉合并回主 tape]
```

---

## 3. 核心工作原理深度解析

### 3.1 Agent Loop（AgentLoop）

`AgentLoop` 是整个系统的顶层协调器，设计极其简洁，仅 72 行代码：

```python
class AgentLoop:
    async def handle_input(self, raw: str) -> LoopResult:
        with self._tape.fork_tape():           # 1. 创建 tape 分叉
            route = await self._router.route_user(raw)  # 2. 路由用户输入
            if route.exit_requested:           # 3. 退出检测
                return LoopResult(exit_requested=True, ...)
            if not route.enter_model:          # 4. 直接命令，无需模型
                return LoopResult(assistant_output="", ...)
            model_result = await self._model_runner.run(route.model_prompt)  # 5. 模型推理
            self._record_result(model_result)  # 6. 记录到 tape
            return LoopResult(...)
```

**关键设计决策**：
- Tape 的 `fork_tape()` 使用 Python `ContextVar`，在 asyncio 任务间实现 tape 隔离，不同 session 不会干扰
- 整个 loop 是无状态的（frozen dataclass 返回值），所有状态都在 tape 里

### 3.2 统一路由引擎（InputRouter）

这是 Bub 最核心的创新点。**同一个 InputRouter 同时处理用户输入和 AI 输出**，保证了一致性：

```
用户输入 ─→ route_user()   ─→ 解析 "," 前缀命令
AI 输出  ─→ route_assistant() ─→ 解析 "," 前缀命令（支持代码块中的 Shell 命令）
```

命令解析规则：
- `,help`、`,tools`、`,tape.info` 等 → 查 ToolRegistry，是内置命令
- `,git status`、`, ls -la` 等 → 不在 Registry，走 bash 执行
- 不以 `,` 开头 → 自然语言，进入模型

失败回退机制（关键）：
```python
# 命令执行失败时，不是直接报错，而是构建结构化上下文送给模型
result.block() → '<command name="git" status="error">\n...\n</command>'
```
这让 AI 能根据真实错误输出进行调试，而不是盲目猜测。

### 3.3 模型运行器（ModelRunner）

`ModelRunner.run()` 实现了一个有界的内部循环（`max_steps=20`）：

```python
while state.step < self._max_steps and not state.exit_requested:
    response = await self._chat(state.prompt)    # LLM 调用
    if response.followup_prompt:                 # tool_call → 继续
        state.prompt = TOOL_CONTINUE_PROMPT
        continue
    route = await self._router.route_assistant(assistant_text)  # 路由 AI 输出
    if route.next_prompt:                        # 有命令执行结果 → 继续
        state.prompt = route.next_prompt
    else:
        break                                    # 纯文本输出 → 结束
```

System Prompt 的动态构建（每次 LLM 调用都重新构建）：
1. `base_system_prompt`（来自配置）
2. `workspace_system_prompt`（读取 `/workspace/AGENTS.md`）
3. `_runtime_contract()`（运行时契约，告知 AI 如何使用工具和渠道）
4. `render_tool_prompt_block()`（工具视图：compact 列表 + 按需展开的详情）
5. `render_compact_skills()`（Skill 摘要）

**Runtime Contract（运行时契约）** 是 AI Native 设计的核心体现：
```
1) 所有操作使用 tool calls（文件、shell、web、tape、skills）
2) 不要在正常流程中使用 comma 命令（兼容性回退除外）
3) 收集足够证据后，返回自然语言答案
4) 用 '$name' hints 请求工具/skill 详情展开
5) 上下文过长时，先使用 tape.handoff 工具缩短历史
6) 回复时必须通过对应渠道发送消息
```

### 3.4 渐进式工具视图（ProgressiveToolView）

这是一个优雅的上下文窗口管理机制：

**初始状态**（每次 LLM 调用）：所有工具只展示一行 compact 描述
```xml
<tool_view>
  - bash: Run shell command
  - fs_read: Read file content
  - tape_handoff: Create anchor handoff
  ...
</tool_view>
```

**触发展开**（三种方式）：
1. 用户输入或 AI 输出中包含 `$tool_name` hints
2. 用户执行了 `,tool.describe name=xxx`
3. AI 在输出中提到了某个工具名

展开后追加 `<tool_details>` 块，包含完整 schema：
```xml
<tool_details>
  <tool name="fs_read">
    name: fs.read
    source: builtin
    description: Read file content
    schema: {...}
  </tool>
</tool_details>
```

这样做的好处：在不知道需要什么工具时，prompt 保持精简；需要特定工具时，按需展开。

---

## 4. Tape（磁带）系统深度解析

### 4.1 Tape 的设计哲学

Tape 是 Bub 区别于其他 Agent 框架最核心的设计元素，名字来自"磁带录音机"的比喻：

- **Append-Only**：所有事件只追加，不修改（类似 Event Sourcing）
- **JSONL 格式**：每行一个 JSON 对象，人类可读，机器可解析
- **workspace 级别隔离**：用 workspace 路径的 MD5 作为前缀

Tape 条目类型：
| kind | 描述 |
|------|------|
| `message` | LLM 对话消息（user/assistant） |
| `tool_call` | 工具调用记录 |
| `tool_result` | 工具调用结果 |
| `anchor` | 阶段标记（`handoff` 创建） |
| `event` | 运行时事件（`loop.step.start`、`command`、`loop.result` 等） |

### 4.2 Fork/Merge 语义

每次处理用户输入时，创建一个临时的 tape 分叉（fork），完成后合并回主 tape。这个设计让：
- 每个 asyncio 任务有独立的 tape 视图（通过 `ContextVar`）
- 异常时分叉不会污染主 tape
- 支持并发处理（多 session 互不干扰）

```python
@contextlib.contextmanager
def fork_tape(self) -> Generator[Tape, None, None]:
    fork_name = self._store.fork(self._tape.name)   # 拷贝当前 tape
    reset_token = _tape_context.set(self._llm.tape(fork_name))
    try:
        yield _tape_context.get()
    finally:
        self._store.merge(fork_name, self._tape.name)  # 合并回主 tape
        _tape_context.reset(reset_token)
```

### 4.3 Anchor/Handoff（锚点/交接）

这是 Bub 对长任务上下文管理的解决方案：

```
session/start ──> 工作 ──> handoff(phase-1, summary="...") ──> 工作 ──> handoff(phase-2)
      │                           │                                          │
   [anchor]                   [anchor]                                   [anchor]
```

- `tape.anchors`：列出所有阶段边界（最多 50 个）
- `tape.search`：用 rapidfuzz 模糊搜索历史条目
- `tape.reset archive=true`：归档当前 tape，创建新的 session/start 锚点

---

## 5. Skill 系统深度解析

### 5.1 Skill 的本质

Skill 不是代码，而是"给另一个 Bub 实例读的操作手册"。每个 Skill 是一个目录，必须包含 `SKILL.md`：

```yaml
---
name: telegram
description: |
  Telegram Bot skill for sending and editing Telegram messages via Bot API.
  Use when Bub needs to: (1) Send a message to a Telegram user/group/channel...
---
# Telegram Skill
Agent-facing execution guide...
```

**关键设计**：`description` 是触发机制——Bub 扫描所有 skill 的 description，当用户请求匹配时，AI 自动展开对应 skill 的完整 body。

### 5.2 三级发现优先级

```python
ordered_roots = [
    (workspace_path / ".agent/skills", "project"),  # 1. 项目级（最高优先级）
    (Path.home() / ".agent/skills", "global"),       # 2. 全局（~/.agent/skills）
    (_builtin_skills_root(), "builtin"),              # 3. 内置（随包分发）
]
```

项目级 skill 可以覆盖全局和内置 skill，实现定制化。

### 5.3 渐进式加载（三级）

1. **元数据**（name + description，约 100 词）：始终在 System Prompt 中
2. **SKILL.md body**（Skill 触发时展开，< 5k 词）：需要使用该 skill 时加载
3. **捆绑资源**（scripts/、references/、assets/）：按需由 AI 读取

`$name` hint 机制：用户或 AI 输出中出现 `$telegram` 时，自动展开 telegram skill 的完整 body。

### 5.4 内置 Skills

| Skill | 作用 |
|-------|------|
| `telegram` | Telegram 消息发送/编辑脚本封装 + 响应策略指南 |
| `discord` | Discord 消息发送脚本封装 |
| `gh` | GitHub CLI 操作手册 |
| `skill-creator` | 创建新 skill 的引导手册（渐进式设计原则） |
| `skill-installer` | 从 openai/skills 仓库安装 skill |

---

## 6. OpenClaw 功能复刻分析

Bub 明确声称是 Claude Code（OpenClaw）的社区复刻。对比分析：

### 6.1 已复刻的核心功能

| Claude Code 功能 | Bub 实现 |
|-----------------|----------|
| bash 工具 | `builtin.run_bash`，支持 .env 注入，30s 超时 |
| 文件读写编辑 | `fs.read`、`fs.write`、`fs.edit`（精确文本替换） |
| Web 获取 | `web.fetch`（HTML→Markdown），`web.search` |
| 工具调用循环 | `ModelRunner` 中的 tool_call followup 机制 |
| AGENTS.md 支持 | `read_workspace_agents_prompt()` 读取项目级 prompt |
| Skill 系统 | 与 Claude Code Skills（`.agent/skills`）完全兼容 |
| 会话历史 | Tape JSONL 存储（追加只读，支持搜索） |
| 多渠道接入 | Telegram + Discord 适配器 |

### 6.2 Bub 的差异化设计

| 维度 | Claude Code | Bub |
|------|-------------|-----|
| 命令系统 | 内置斜杠命令 `/` | 逗号命令 `,`（用户和 AI 通用）|
| 会话持久化 | 隐式管理 | 显式 Tape + Anchor/Handoff |
| 阶段管理 | 无明确机制 | anchor/handoff 标记阶段边界 |
| 工具视图 | 完整 schema 始终可见 | 渐进式展开（节省 context） |
| 调度系统 | 无 | APScheduler（cron/interval/delay） |
| 自治模式 | 无 | `bub idle`（纯调度器模式） |

---

## 7. Telegram 集成分析

### 7.1 长轮询架构

```python
class TelegramChannel(BaseChannel[Message]):
    async def start(self, on_receive):
        app = Application.builder().token(token).build()
        app.add_handler(CommandHandler("start", self._on_start))
        app.add_handler(CommandHandler("bub", self._on_text, has_args=True, block=False))
        app.add_handler(MessageHandler(~filters.COMMAND, self._on_text, block=False))
        await updater.start_polling(drop_pending_updates=True)
        await asyncio.Event().wait()  # 无限等待
```

使用 `block=False` 实现非阻塞消息处理（多消息并发）。

### 7.2 Session 隔离

每个 chat_id 对应独立的 session：
```python
session_id = f"telegram:{chat_id}"  # 例如 "telegram:123456789"
```

`AppRuntime.get_session()` 按 session_id 懒创建 `SessionRuntime`，每个 session 有独立的：
- tape（命名为 `bub:{session_hash}`）
- ToolRegistry 实例
- ModelRunner 实例
- ProgressiveToolView

### 7.3 消息防抖（Debounce）

`SessionRunner` 实现了消息防抖和聚合：

```python
# 收到被 @mention 的消息：1秒防抖后触发
# 收到后续消息（30秒窗口内）：debounce_seconds 防抖
# 收到逗号命令：立即执行，不防抖
```

这允许用户快速发送多条消息，Bub 会聚合后一次性处理。

### 7.4 消息类型处理

支持 text / photo / audio / sticker / video / voice / document / video_note，非文本消息转换为结构化 metadata JSON 传给 AI。

### 7.5 群组支持

```python
# 私聊：处理所有消息
# 群组：只处理 @mention 或 reply-to-bot 的消息
```

### 7.6 Typing 指示器

处理消息时自动发送 `chat_action=typing`，每 4 秒发送一次，直到处理完成。

---

## 8. Startup 协议与 AI 自驱动机制

### 8.1 Docker Entrypoint 设计

`entrypoint.sh` 实现了一个优雅的启动协议：

```bash
# 1. 如果 /workspace/bub_hooks.py 存在，注入到 Python 包目录（运行时扩展）
if [ -f "/workspace/bub_hooks.py" ]; then
    cp /workspace/bub_hooks.py /app/.venv/lib/python3.12/site-packages/
    export BUB_HOOKS_MODULE="bub_hooks"
fi

# 2. 如果 /workspace/startup.sh 存在，说明是 AI 自驱动模式
if [ -f "/workspace/startup.sh" ]; then
    nohup /app/.venv/bin/bub idle ...  &  # 后台启动调度器（自治模式）
    exec bash /workspace/startup.sh       # 前台执行启动脚本
else
    exec /app/.venv/bin/bub message       # 默认：启动消息渠道服务
fi
```

**这意味着**：如果 AI 在 workspace 写入了 `startup.sh`，下次容器重启时会执行该脚本并同时运行调度器。AI 可以安排自己在重启后继续某个任务。

### 8.2 Hooks 机制（运行时扩展）

`bub_hooks.py` 可以注册自定义 channel：

```python
# /workspace/bub_hooks.py 示例
def install(ctx):
    ctx.register_channel(MyCustomChannel)
```

这允许在不修改 Bub 源码的情况下扩展渠道能力，是面向 workspace 的插件机制。

### 8.3 `bub idle` 命令（纯自治模式）

```python
@app.command()
def idle():
    """Start the scheduler only, this is a good option for running a completely autonomous agent."""
    scheduler = BlockingScheduler(jobstores={"default": job_store})
    scheduler.start()  # 阻塞运行，等待 cron 触发
```

AI 可以通过 `schedule.add` 工具安排定时任务，`bub idle` 在后台持续执行这些任务，实现完全自治的定时 Agent。

### 8.4 自我演进的 Bootstrap 里程碑

Bub 博客记录了一个关键里程碑（2025-07-16）：

> Bub 修复了自己的第一个 mypy 错误（将 24 个错误减少到 23 个）。虽然微小，但这证明了 Agent 能够推理、定位并修复自身代码库中的类型错误。这是实现自我托管、自我修复 Agent 循环的第一步。

这标志着系统从"帮你写代码"到"能改进自己"的质的转变。

### 8.5 Runtime Contract 中的自驱动指令

System Prompt 中的 `_runtime_contract()` 包含关键的渠道响应指令：

```
"You MUST send message to the corresponding channel before finish when you want to respond.\n"
"Route your response to the same channel the message came from.\n"
"There is a skill named `{channel}` for each channel that you need to figure out how to send a response to that channel.\n"
```

这意味着 **AI 被明确告知要主动向渠道发送消息**，而不是等待框架自动发送。AI 使用 `$telegram` 展开 skill，用 `uv run ./scripts/telegram_send.py` 脚本发送消息——这是典型的 AI Native 设计：把发消息变成 AI 的一个主动行为，而不是被动响应。

---

## 9. AI Native 设计理念

### 9.1 "AI 是一等公民"

Bub 的设计中，AI 不是"被服务的客户"，而是"主动的执行者"：

1. **AI 主动发消息**：不依赖框架自动回复，而是通过 telegram skill 脚本主动调用 Bot API
2. **AI 自己管理上下文**：`tape.handoff` 是 AI 主动调用的工具，而不是框架自动触发
3. **AI 按需展开工具**：通过 `$hint` 机制按需获取工具详情，主动管理 prompt 空间
4. **AI 调度自己的任务**：`schedule.add` 让 AI 安排自己的定时工作

### 9.2 可观察性设计

Bub 强调 inspectable（可检查）：
- 所有命令执行记录在 tape 中（`kind="event", name="command"`）
- 每次 loop step 开始/结束都有 tape 记录
- `tape.info` 提供实时统计（条目数、锚点数、context 长度估算）
- `tape.search` 支持模糊搜索历史

### 9.3 确定性优先

Bub 反复强调"deterministic"（确定性）：
- 命令路由规则固定：`,` 前缀触发命令，其他进模型
- 成功命令直接返回，不经过模型（减少 LLM 不确定性）
- 失败命令送给模型处理（让 AI 处理不确定的情况）
- 同一路由规则作用于用户和 AI 输出（消除双重标准）

### 9.4 上下文窗口经济学

Bub 的多项设计都指向"节省 context 空间"：
- ProgressiveToolView：按需展开工具详情
- Skill 三级加载：元数据始终在，body 按需加载，资源按需读取
- Tape anchor/handoff：长任务中截断历史，保留摘要
- Runtime contract 告知 AI：context 过长时先 handoff

---

## 10. 对 AI 自进化系统的启发

### 10.1 Tape = 可审计的演进记录

Bub 的 Tape 系统（append-only JSONL + anchor/handoff）是对"AI 会话记忆"的优雅实现。相较于我们当前的 Memory Bank（静态文件），Tape 有以下优势：

- **时间序列**：每个事件都有 ID，可以回溯
- **结构化查询**：支持按 kind 过滤、按 anchor 范围查询、模糊搜索
- **Fork/Merge**：隔离实验性操作，失败不污染历史

**启发**：可以考虑将 `config/evo_config.yaml` 的修改历史、每次演化周期的决策过程也以 JSONL 事件流记录，而不仅仅是 Git commit。

### 10.2 Skill 系统 = 模块化知识库

Bub 的 Skill 系统（SKILL.md + frontmatter + 三级加载）是一种精妙的"知识模块化"方案：
- 每个 Skill 是独立的"专业知识包"
- description 是触发机制，body 是执行指南
- 三级加载减少 context 浪费

**启发**：我们的 `workspace/rules/` 目录可以参考 Skill 格式重组，让每条规则都有 YAML frontmatter 标注触发条件，而不是 AI 每次都读全部规则。

### 10.3 Runtime Contract = 明确的 AI 行为协议

Bub 在 System Prompt 中放置的 `_runtime_contract()` 是一种"AI 行为协议"——明确告知 AI：
- 什么是允许的操作
- 什么是禁止的行为
- 上下文超限时应该如何处理
- 如何与外部渠道交互

**启发**：我们的 `workspace/rules/constitution/identity.md` 可以参考这种格式，增加更明确的"禁止行为"和"边界条件"描述。

### 10.4 `schedule.add` + `bub idle` = AI 自主定时任务

这是 Bub 实现"AI 自驱动"的关键机制：AI 可以安排自己的未来任务，`idle` 模式纯靠定时器驱动，实现完全自治。

**启发**：我们的 Observer Engine 可以考虑类似机制——允许 AI 在完成一次演化后，通过 `schedule.add` 安排下次演化的触发时机，而不是依赖外部 cron。

### 10.5 startup.sh 协议 = AI 编写的自启动脚本

Bub 的 entrypoint 会检查 workspace 中是否有 `startup.sh`，如果有则执行。这意味着 **AI 可以编写一个脚本，让自己在容器重启后自动继续工作**。

**启发**：我们的 `main.py` 可以支持类似机制——检查 workspace 中是否有 AI 写入的 `next-task.json`，如果有则在下次启动时自动执行。

### 10.6 Proactive Response 模式

Bub 的 `proactive_response` 设置（默认 `false`）非常有趣：当为 `false` 时，框架不自动回复，全靠 AI 通过 telegram skill 主动发消息；当为 `true` 时，框架自动回复 `assistant_output`。

这意味着可以给 AI 选择：是让框架"帮它说话"，还是"自己主动说话"。后者更适合需要精细控制消息时机和格式的场景。

---

## 11. 实施建议

### 短期可借鉴项

1. **引入 Tape 格式的事件日志**：在 `core/memory.py` 中，用 JSONL 记录每次演化周期的事件（决策、工具调用、结果），而不只是更新静态文件
2. **Skills 化现有规则**：将 `workspace/rules/` 中的规则文件改造为 SKILL.md 格式（frontmatter 触发描述 + body 详细指南）
3. **明确的 Runtime Contract**：在 System Prompt 中增加类似 `_runtime_contract()` 的"禁止行为"和"边界条件"

### 中期可借鉴项

4. **Fork/Merge Tape**：在 Agent Loop 中引入类似的隔离机制，让实验性演化操作不会污染主状态
5. **Proactive Messaging 模式**：让 AI 主动通过 Telegram 发送演化报告，而不只是被动等待查询

### 长期方向参考

6. **startup.sh 协议**：允许 AI 在完成任务后，写入 `next-task.json`，下次启动时自动继续
7. **schedule.add 工具**：给演化系统增加定时任务能力，让 AI 能安排自己的定期自检和演化触发

---

## 参考资料

- [Bub GitHub 仓库](https://github.com/PsiACE/bub)
- [Bub 官方文档](https://bub.build)
- [Baby Bub Bootstrap 里程碑博客](https://bub.build/posts/2025-07-16-baby-bub-bootstrap-milestone/)
- [How to Build an Agent - ampcode.com](https://ampcode.com/how-to-build-an-agent)
- [Tiny Agents - HuggingFace Blog](https://huggingface.co/blog/tiny-agents)
- [republic 框架](https://pypi.org/project/republic/)（Bub 的核心 LLM/Tape 抽象层）
- Bub 源码路径：`/Users/michael/projects/repos/bub/src/bub/`
