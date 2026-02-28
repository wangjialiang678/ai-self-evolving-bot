# Nanobot 源码深度分析合集

> 本文档合并了 Nanobot 项目的三份深度源码分析报告。

## 目录
- [Part 1: Agent Loop + LLM Provider + Context](#part-1-agent-loop)
- [Part 2: 工具系统](#part-2-工具系统)
- [Part 3: Telegram + 配置 + 消息总线](#part-3-telegram-配置-消息总线)

---

# Part 1: Agent Loop + LLM Provider + Context

**日期**: 2026-02-25
**任务**: 深入阅读 Nanobot 源码中的 Agent Loop、LLM Provider、Context 三大模块，完整记录执行流程、数据结构和关键实现

---

## 调研摘要

Nanobot 的 Agent Loop 是一个经典的 ReAct 模式实现：接收消息 → 构建上下文 → 调用 LLM → 检测 tool_calls → 执行工具并注入结果 → 循环，直到 LLM 返回纯文本或达到迭代上限（默认 40 次）。Provider 层通过 LiteLLM 统一适配多家厂商，messages 数组遵循 OpenAI Chat Completions 格式。记忆系统是两层结构：MEMORY.md（长期事实）+ HISTORY.md（可 grep 的时序日志），由 LLM 工具调用来完成压缩写入。

---

## 一、Agent Loop 完整执行流程

### 1. 入口：`run()` 主循环 (`loop.py:240-268`)

```
AgentLoop.run()
  └─ while self._running:
       msg = await bus.consume_inbound()   # 1 秒超时，避免阻塞
       response = await _process_message(msg)
       await bus.publish_outbound(response)
```

### 2. `_process_message()` 核心分支 (`loop.py:296-423`)

```
_process_message(msg)
  ├─ [system channel] — 子代理回调，直接构建消息进入 agent loop
  ├─ [/new, /help] — 斜杠命令快速返回
  ├─ [unconsolidated >= memory_window] — 异步触发后台记忆压缩
  └─ [正常消息处理]:
       1. _set_tool_context()          设置 MessageTool / SpawnTool / CronTool 的路由上下文
       2. session.get_history()        取历史消息（最多 memory_window 条）
       3. context.build_messages()     构建初始 messages 列表
       4. _run_agent_loop()            ← 工具调用循环
       5. _save_turn()                 把新消息追加进 session（tool result 超 500 字符截断）
       6. sessions.save(session)       持久化
       7. 若 MessageTool 已在本轮发送过消息 → 返回 None（避免重复回复）
       8. 否则 return OutboundMessage
```

### 3. `_run_agent_loop()` 工具调用循环（核心）(`loop.py:174-238`)

这是整个系统的心脏：

```python
while iteration < self.max_iterations:   # max_iterations = 40
    iteration += 1

    response = await provider.chat(
        messages=messages,
        tools=self.tools.get_definitions(),
        model=self.model,
        temperature=self.temperature,
        max_tokens=self.max_tokens,
    )

    if response.has_tool_calls:
        # 1. 可选：发送进度通知（thinking 内容 + tool hint）
        # 2. 构建 tool_call_dicts（OpenAI 格式）
        # 3. context.add_assistant_message() → 追加 assistant 消息（含 tool_calls）
        # 4. 串行执行每个工具：
        for tool_call in response.tool_calls:
            result = await tools.execute(tool_call.name, tool_call.arguments)
            messages = context.add_tool_result(messages, tool_call.id, tool_call.name, result)
        # 5. 继续循环
    else:
        final_content = _strip_think(response.content)  # 去除 <think>...</think>
        break

if final_content is None and iteration >= max_iterations:
    final_content = "我达到了最大工具调用迭代次数..."
```

**关键细节**：
- 工具调用是**串行**的（for 循环，非并行）
- 每次工具调用后立即把结果注入 messages，再继续下一次 LLM 调用
- 迭代计数器以 LLM 调用次数为单位（非工具调用次数）
- `<think>...</think>` 标签会被正则剥离（`re.sub(r"<think>[\s\S]*?</think>", "", text)`）

---

## 二、工具调用循环的具体实现

### assistant 消息注入 (`context.py:220-253`)

```python
msg = {
    "role": "assistant",
    "content": content,           # 可为 None
    "tool_calls": [               # OpenAI 格式
        {
            "id": tc.id,
            "type": "function",
            "function": {
                "name": tc.name,
                "arguments": json.dumps(tc.arguments)  # JSON 字符串
            }
        }
    ],
    "reasoning_content": ...      # 可选，DeepSeek-R1/Kimi 思维链
}
```

**注意**：`content` 键始终存在（防止部分 provider 拒绝缺失 content 的消息，如 StepFun）。

### tool result 注入 (`context.py:193-218`)

```python
{
    "role": "tool",
    "tool_call_id": tool_call_id,
    "name": tool_name,
    "content": result            # 字符串
}
```

### 多轮工具调用时 messages 数组结构

```
[system]                        ← 系统提示词（固定，一次构建）
[user] (历史 turn 1)
[assistant + tool_calls] (历史 turn 1)
[tool result 1]
[tool result 2]
...
[user] (历史 turn N，含 Runtime Context)
[assistant + tool_calls] (当前 turn，本次调用新增)
[tool result] (tool 1 结果)
[tool result] (tool 2 结果)
...继续 LLM 调用...
[assistant] (最终回复)
```

---

## 三、messages 数组构建：`build_messages()` (`context.py:136-173`)

```python
messages = []
# 1. 系统提示词
messages.append({"role": "system", "content": build_system_prompt()})
# 2. 历史对话
messages.extend(history)
# 3. 当前用户消息（含可选图片 base64 + Runtime Context 注入）
user_content = _build_user_content(current_message, media)
user_content = _inject_runtime_context(user_content, channel, chat_id)
messages.append({"role": "user", "content": user_content})
```

**Runtime Context 注入**（追加到用户消息末尾）：
```
[Runtime Context]
Current Time: 2026-02-25 14:30 (Wednesday) (CST)
Channel: telegram
Chat ID: 12345678
```

**媒体（图片）处理**：
- 读取本地文件 → base64 编码 → `{"type": "image_url", "image_url": {"url": "data:image/png;base64,..."}}` 格式
- 图片放在 content 列表前，文字放最后

---

## 四、系统提示词构建：`build_system_prompt()` (`context.py:30-73`)

组装顺序（各部分用 `\n\n---\n\n` 分隔）：

```
1. _get_identity()              核心身份（workspace路径、工具使用规范、内存路径）
2. _load_bootstrap_files()      加载 AGENTS.md / SOUL.md / USER.md / TOOLS.md / IDENTITY.md
3. memory.get_memory_context()  MEMORY.md 内容 → "# Memory\n## Long-term Memory\n..."
4. always skills 内容           标记 always=true 的 SKILL.md 全文
5. skills summary               所有 skills 的 XML 摘要（供 agent 按需 read_file 加载）
```

**Skills 摘要格式**（XML）：
```xml
<skills>
  <skill available="true">
    <name>skill-name</name>
    <description>...</description>
    <location>/path/to/SKILL.md</location>
  </skill>
  <skill available="false">
    <name>needs-cli</name>
    <requires>CLI: ffmpeg, ENV: OPENAI_API_KEY</requires>
  </skill>
</skills>
```

**Skills 加载策略**：
- `always=true` 的 skill → 系统提示词中完整包含
- 其余 skill → 只包含摘要，agent 需要时通过 `read_file` 工具读取 SKILL.md 全文
- workspace skills 优先于 builtin skills（同名时 workspace 覆盖）
- requirements 检查：缺少 bin/env → `available="false"`

---

## 五、LLM 调用参数传递

### LiteLLMProvider.chat() 参数构建 (`litellm_provider.py:197-224`)

```python
kwargs = {
    "model": self._resolve_model(model),   # 加前缀，如 deepseek/deepseek-chat
    "messages": self._sanitize_messages(self._sanitize_empty_content(messages)),
    "max_tokens": max(1, max_tokens),
    "temperature": temperature,
}
if api_key: kwargs["api_key"] = api_key
if api_base: kwargs["api_base"] = api_base
if extra_headers: kwargs["extra_headers"] = extra_headers
if tools:
    kwargs["tools"] = tools
    kwargs["tool_choice"] = "auto"

response = await acompletion(**kwargs)
```

**消息净化 `_sanitize_messages()`**：只保留标准 OpenAI 字段：
```python
_ALLOWED_MSG_KEYS = {"role", "content", "tool_calls", "tool_call_id", "name"}
# 注意：reasoning_content 被剥离（严格 provider 不接受额外字段）
```

**空内容净化 `_sanitize_empty_content()`**（基类方法）：
- 空字符串 content → `None`（assistant + tool_calls）或 `"(empty)"`
- 空文本块从 list content 中过滤

**Prompt Caching（Anthropic/OpenRouter）**：
- 系统消息 content → 转为 `[{"type": "text", "text": "...", "cache_control": {"type": "ephemeral"}}]`
- tools 列表最后一项加 `cache_control`

---

## 六、Provider 基类接口

### `LLMProvider` (`base.py:31-110`)

```python
class LLMProvider(ABC):
    def __init__(self, api_key: str | None, api_base: str | None): ...

    @abstractmethod
    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
    ) -> LLMResponse: ...

    @abstractmethod
    def get_default_model(self) -> str: ...

    @staticmethod
    def _sanitize_empty_content(messages) -> list[dict]: ...  # 共用工具方法
```

### 返回值 `LLMResponse` (`base.py:17-28`)

```python
@dataclass
class LLMResponse:
    content: str | None
    tool_calls: list[ToolCallRequest] = []
    finish_reason: str = "stop"
    usage: dict[str, int] = {}          # prompt/completion/total_tokens
    reasoning_content: str | None = None  # DeepSeek-R1 / Kimi 思维链

    @property
    def has_tool_calls(self) -> bool:
        return len(self.tool_calls) > 0
```

### `ToolCallRequest` (`base.py:8-13`)

```python
@dataclass
class ToolCallRequest:
    id: str
    name: str
    arguments: dict[str, Any]   # 已解析为 dict（非 JSON 字符串）
```

---

## 七、LiteLLM Provider 解析 tool_calls 响应

### `_parse_response()` (`litellm_provider.py:233-268`)

```python
def _parse_response(self, response):
    choice = response.choices[0]
    message = choice.message

    tool_calls = []
    if hasattr(message, "tool_calls") and message.tool_calls:
        for tc in message.tool_calls:
            args = tc.function.arguments
            if isinstance(args, str):
                args = json_repair.loads(args)   # 使用 json_repair 容错解析
            tool_calls.append(ToolCallRequest(
                id=tc.id,
                name=tc.function.name,
                arguments=args,
            ))

    reasoning_content = getattr(message, "reasoning_content", None) or None

    return LLMResponse(
        content=message.content,
        tool_calls=tool_calls,
        finish_reason=choice.finish_reason or "stop",
        usage={...},
        reasoning_content=reasoning_content,
    )
```

**关键点**：使用 `json_repair` 而非 `json.loads`，对模型输出的不规范 JSON 有容错能力。

---

## 八、记忆管理

### 架构：两层记忆 (`memory.py`)

```
workspace/
  memory/
    MEMORY.md      ← 长期事实（LLM 负责更新，全量覆写）
    HISTORY.md     ← 时序日志（仅追加，每条 2-5 句话）
```

### 压缩触发条件 (`loop.py:363-380`)

```python
unconsolidated = len(session.messages) - session.last_consolidated
if unconsolidated >= self.memory_window:   # memory_window 默认 100
    # 异步后台触发，不阻塞当前消息处理
    asyncio.create_task(_consolidate_and_unlock())
```

- 触发条件：未压缩消息数 ≥ memory_window（100）
- 执行方式：异步 Task，不阻塞主流程
- 去重保护：用 `self._consolidating: set[str]` 防止同一 session 并发压缩
- 锁机制：每个 session_key 独立 `asyncio.Lock`

### 压缩过程 (`memory.py:69-150`)

```python
async def consolidate(session, provider, model, *, archive_all=False, memory_window=50):
    # 1. 确定要压缩的消息范围
    if archive_all:
        old_messages = session.messages   # /new 命令触发时压缩全部
    else:
        keep_count = memory_window // 2   # 保留最近 50 条
        old_messages = session.messages[last_consolidated:-keep_count]

    # 2. 格式化为文本（含时间戳、角色、工具调用列表）
    lines = [f"[{timestamp}] {role} [tools: ...]: {content}"]

    # 3. 调用 LLM，要求其调用 save_memory 工具
    response = await provider.chat(
        messages=[system_msg, user_msg_with_conversation],
        tools=_SAVE_MEMORY_TOOL,   # 强制 LLM 使用工具输出结构化结果
        model=model,
    )

    # 4. 解析 tool call 结果
    args = response.tool_calls[0].arguments
    # args = {"history_entry": "...", "memory_update": "完整 MEMORY.md 内容"}

    # 5. 追加历史日志，全量覆写长期记忆
    self.append_history(args["history_entry"])
    if args["memory_update"] != current_memory:
        self.write_long_term(args["memory_update"])

    session.last_consolidated = len(session.messages) - keep_count
```

**save_memory 工具定义**要求两个字段：
- `history_entry`：2-5 句话摘要，含 `[YYYY-MM-DD HH:MM]` 时间戳，支持 grep 检索
- `memory_update`：完整的长期记忆 Markdown（包含旧内容 + 新增内容）

### 保存到 session 时的截断 (`loop.py:427-438`)

```python
_TOOL_RESULT_MAX_CHARS = 500  # 工具结果超 500 字符截断
```

工具结果在写入 session 持久化时截断，但注入 LLM 的 messages 中保持完整。

---

## 九、迭代上限和超时的实现

### 迭代上限

```python
# AgentLoop 构造参数
max_iterations: int = 40    # LLM 调用次数上限（含首次调用）

# 子代理中独立配置
max_iterations = 15         # subagent.py:127，子代理更低

# 触发时的行为
if final_content is None and iteration >= self.max_iterations:
    final_content = (
        f"I reached the maximum number of tool call iterations ({self.max_iterations}) "
        "without completing the task."
    )
```

### 超时（非工具调用超时，是消息队列超时）

```python
# run() 主循环中等待消息的超时
msg = await asyncio.wait_for(
    self.bus.consume_inbound(),
    timeout=1.0    # 1 秒，防止 _running=False 时永久阻塞
)
```

LLM 调用本身没有显式超时设置，由 LiteLLM 内部处理。

### ExecTool 超时（工具层）

```python
ExecToolConfig.timeout   # 在构造 ExecTool 时传入
```

---

## 十、子代理（SubAgent）架构

子代理与主代理的区别：

| 特性 | 主代理 | 子代理 |
|------|--------|--------|
| max_iterations | 40 | 15 |
| MessageTool | 有 | 无 |
| SpawnTool | 有 | 无 |
| CronTool | 有 | 无 |
| 会话历史 | 有（session） | 无（每次全新） |
| 记忆系统 | 有 | 无 |
| 系统提示词 | 完整 | 聚焦任务型 |
| 结果回传 | 直接回复用户 | 通过 bus 发 InboundMessage（channel="system"）回主代理 |

子代理完成后，通过 `bus.publish_inbound(InboundMessage(channel="system", ...))` 把结果注入主代理的消息队列，主代理作为一个新的 system message 来处理，再用自然语言总结给用户。

---

## 十一、Provider 注册表设计亮点

`registry.py` 采用数据驱动方式，每个 `ProviderSpec` 包含：
- `litellm_prefix`：LiteLLM 路由前缀（如 `deepseek/deepseek-chat`）
- `skip_prefixes`：防止双重前缀的保护列表
- `detect_by_key_prefix` / `detect_by_base_keyword`：网关自动检测
- `strip_model_prefix`：AiHubMix 等网关需要剥离 `anthropic/` 前缀再重新加 `openai/`
- `model_overrides`：每模型参数覆盖（如 Kimi K2.5 强制 `temperature=1.0`）
- `supports_prompt_caching`：Anthropic 和 OpenRouter 支持 Prompt Caching

**网关检测优先级**：
1. config key（`provider_name`）直接指定
2. API key 前缀（如 `sk-or-` → OpenRouter）
3. api_base URL 关键词

---

## 参考文件

- `/tmp/nanobot/nanobot/agent/loop.py` — Agent Loop 核心（460 行）
- `/tmp/nanobot/nanobot/agent/context.py` — 上下文构建（254 行）
- `/tmp/nanobot/nanobot/agent/memory.py` — 记忆管理（151 行）
- `/tmp/nanobot/nanobot/agent/skills.py` — Skills 系统（229 行）
- `/tmp/nanobot/nanobot/agent/subagent.py` — 子代理（258 行）
- `/tmp/nanobot/nanobot/providers/base.py` — Provider 基类（111 行）
- `/tmp/nanobot/nanobot/providers/litellm_provider.py` — LiteLLM Provider（273 行）
- `/tmp/nanobot/nanobot/providers/registry.py` — Provider 注册表（463 行）
- `/tmp/nanobot/nanobot/providers/custom_provider.py` — 自定义 Provider（52 行）

---

# Part 2: 工具系统

**日期**: 2026-02-25
**任务**: 深度阅读 Nanobot 工具系统源码，分析 BaseTool 接口、ToolRegistry 实现、所有内置工具细节、安全机制与 LLM schema 生成

---

## 调研摘要

Nanobot 的工具系统是一个整洁的抽象层，以 `Tool` 抽象基类统一接口，通过 `ToolRegistry` 进行动态注册与分发。内置工具覆盖文件系统、Shell、Web、消息、定时任务、子代理、MCP 集成七大类。安全控制分两层：文件系统通过路径沙箱（`allowed_dir`），Shell 通过正则黑/白名单（`deny_patterns`/`allow_patterns`）及工作目录限制。工具向 LLM 暴露标准 OpenAI function-calling JSON Schema 格式。

---

## 文件结构

```
nanobot/agent/tools/
├── __init__.py       — 只导出 Tool, ToolRegistry
├── base.py           — Tool 抽象基类（含参数校验）
├── registry.py       — ToolRegistry（注册、执行、schema 生成）
├── filesystem.py     — ReadFile / WriteFile / EditFile / ListDir
├── shell.py          — ExecTool（Shell 执行 + 安全守卫）
├── web.py            — WebSearchTool / WebFetchTool
├── message.py        — MessageTool（发送消息到聊天频道）
├── cron.py           — CronTool（定时任务管理）
├── spawn.py          — SpawnTool（生成后台子代理）
└── mcp.py            — MCPToolWrapper + connect_mcp_servers
```

---

## 一、Tool 抽象基类（base.py）

### 类定义

```python
class Tool(ABC):
    _TYPE_MAP = {
        "string": str, "integer": int, "number": (int, float),
        "boolean": bool, "array": list, "object": dict,
    }
```

### 必须实现的抽象属性/方法

| 成员 | 类型 | 说明 |
|------|------|------|
| `name` | `@property` → `str` | 工具名，用于 function call 中的函数名 |
| `description` | `@property` → `str` | 描述，传给 LLM |
| `parameters` | `@property` → `dict[str, Any]` | JSON Schema 格式的参数定义 |
| `execute(**kwargs)` | `async` → `str` | 工具实际执行逻辑，返回字符串 |

### 具体方法（无需覆写）

| 方法 | 说明 |
|------|------|
| `validate_params(params: dict) -> list[str]` | 验证参数，返回错误列表（空表示合法） |
| `_validate(val, schema, path) -> list[str]` | 递归校验（type、enum、minimum/maximum、minLength/maxLength、required、items） |
| `to_schema() -> dict` | 生成 OpenAI function-calling 格式 schema |

### to_schema() 输出格式

```json
{
  "type": "function",
  "function": {
    "name": "<tool.name>",
    "description": "<tool.description>",
    "parameters": { ... }   // tool.parameters 的原始 JSON Schema
  }
}
```

### validate_params 校验能力

- 类型校验：string / integer / number / boolean / array / object
- enum 枚举值校验
- 数值范围：minimum / maximum
- 字符串长度：minLength / maxLength
- required 字段存在性
- 递归校验 object properties 和 array items
- path 参数提供清晰的错误定位（如 `.working_dir` 或 `[0]`）

---

## 二、ToolRegistry（registry.py）

### 数据结构

```python
class ToolRegistry:
    _tools: dict[str, Tool]  # name -> Tool 实例
```

### 方法列表

| 方法 | 说明 |
|------|------|
| `register(tool)` | 注册工具（按 `tool.name` 键） |
| `unregister(name)` | 注销工具 |
| `get(name) -> Tool \| None` | 按名查询 |
| `has(name) -> bool` | 检查是否已注册 |
| `get_definitions() -> list[dict]` | 生成所有工具的 OpenAI schema 列表 |
| `execute(name, params) -> str` | 按名执行工具（含校验与错误处理） |
| `tool_names -> list[str]` | 已注册工具名列表 |
| `__len__` | 注册数量 |
| `__contains__` | `in` 运算符支持 |

### execute() 核心逻辑

```
_HINT = "\n\n[Analyze the error above and try a different approach.]"

1. 查找工具 → 不存在则返回带 Available 列表的 Error
2. validate_params() → 有错误则返回拼接的 Error + _HINT
3. tool.execute(**params) → 若结果以 "Error" 开头则追加 _HINT
4. 捕获任何 Exception → 返回 "Error executing {name}: {e}" + _HINT
```

**关键设计**：所有错误路径都追加 `_HINT`，引导 LLM 自我纠错，而不是简单终止。

---

## 三、内置工具详解

### 3.1 文件系统工具（filesystem.py）

#### 路径解析与沙箱函数 `_resolve_path()`

```
输入: path (str), workspace (Path|None), allowed_dir (Path|None)
流程:
  1. Path(path).expanduser()        # 展开 ~
  2. 如果是相对路径 且 workspace 存在 → workspace / path
  3. p.resolve()                     # 转换为绝对路径（解析 symlink）
  4. 如果 allowed_dir 存在 → resolved.relative_to(allowed_dir.resolve())
     ↳ 抛出 ValueError → 转为 PermissionError: "Path ... outside allowed directory ..."
```

**沙箱机制**：通过 `Path.relative_to()` 严格限制路径在 `allowed_dir` 内，`resolve()` 防止 symlink 逃逸。

#### ReadFileTool

- **name**: `read_file`
- **参数**: `path` (string, required)
- **执行**: 读取 UTF-8 文件内容，返回原始字符串
- **错误处理**: 文件不存在 / 不是文件 / PermissionError / 其他异常

#### WriteFileTool

- **name**: `write_file`
- **参数**: `path` (string, required), `content` (string, required)
- **执行**: `file_path.parent.mkdir(parents=True, exist_ok=True)` → `write_text()`
- **返回**: `"Successfully wrote {N} bytes to {path}"`

#### EditFileTool

- **name**: `edit_file`
- **参数**: `path`, `old_text`, `new_text`（均 string, required）
- **执行**:
  1. 读取文件内容
  2. 检查 `old_text` 是否存在
  3. 统计出现次数（>1 则警告要求提供更多上下文）
  4. `content.replace(old_text, new_text, 1)` → 写回
- **not-found 错误增强**: 用 `difflib.SequenceMatcher` 滑动窗口查找最相似片段（ratio > 0.5 时输出 unified diff），帮助 LLM 定位实际内容

#### ListDirTool

- **name**: `list_dir`
- **参数**: `path` (string, required)
- **执行**: `sorted(dir_path.iterdir())`，目录加 `📁` 前缀，文件加 `📄` 前缀
- **返回**: 按行拼接的条目列表

---

### 3.2 Shell 工具（shell.py）

#### ExecTool 构造参数

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `timeout` | int | 60 | 命令超时秒数 |
| `working_dir` | str\|None | None | 默认工作目录（None → `os.getcwd()`）|
| `deny_patterns` | list[str]\|None | 见下 | 正则黑名单 |
| `allow_patterns` | list[str]\|None | [] | 正则白名单（空=不限制）|
| `restrict_to_workspace` | bool | False | 限制路径在工作目录内 |

#### 内置 deny_patterns（默认）

```python
r"\brm\s+-[rf]{1,2}\b"          # rm -r, rm -rf, rm -fr
r"\bdel\s+/[fq]\b"              # del /f, del /q
r"\brmdir\s+/s\b"               # rmdir /s
r"(?:^|[;&|]\s*)format\b"       # format 命令
r"\b(mkfs|diskpart)\b"          # 磁盘操作
r"\bdd\s+if="                   # dd
r">\s*/dev/sd"                  # 写磁盘
r"\b(shutdown|reboot|poweroff)\b"  # 系统电源操作
r":\(\)\s*\{.*\};\s*:"          # fork bomb
```

#### _guard_command() 安全守卫逻辑

```
1. 对 command.lower() 扫描所有 deny_patterns → 匹配则 block
2. 若 allow_patterns 非空 → 必须至少匹配一个，否则 block
3. 若 restrict_to_workspace:
   a. 检测 "../" 或 "..\" → block (路径穿越)
   b. 提取命令中的 Win 路径 (A:\...) 和 POSIX 绝对路径 (/...)
   c. 逐个 resolve 后判断是否在 cwd_path 内 → 超出则 block
```

#### execute() 执行流程

```
1. cwd = working_dir || self.working_dir || os.getcwd()
2. _guard_command() → 有错误立即返回
3. asyncio.create_subprocess_shell(command, stdout=PIPE, stderr=PIPE, cwd=cwd)
4. asyncio.wait_for(communicate(), timeout=self.timeout)
   → 超时: process.kill() + wait(5s) → 返回超时错误
5. 拼装输出: stdout + "STDERR:\n{stderr}" + "\nExit code: {code}"
6. 截断: len > 10000 → 截断并注明剩余字符数
```

---

### 3.3 Web 工具（web.py）

#### WebSearchTool

- **name**: `web_search`
- **参数**: `query` (string, required), `count` (integer, 1-10, optional)
- **后端**: Brave Search API (`https://api.search.brave.com/res/v1/web/search`)
- **API Key**: 构造时传入或读取 `BRAVE_API_KEY` 环境变量（延迟解析，支持运行时更改）
- **返回格式**:
  ```
  Results for: {query}
  1. {title}
     {url}
     {description}
  2. ...
  ```
- **注意**: 代码中存在 bug：`headers={"X-Subscription-Token": api_key}` 使用了局部变量 `api_key` 但该变量未定义（应为 `self.api_key`）

#### WebFetchTool

- **name**: `web_fetch`
- **参数**: `url` (string, required), `extractMode` (enum: markdown/text, default: markdown), `maxChars` (integer, min: 100)
- **URL 安全校验**: `_validate_url()` → 仅允许 http/https，要求有效域名
- **重定向限制**: `max_redirects=5`，防 DoS
- **内容处理**:
  - `application/json` → `json.dumps(indent=2)`
  - `text/html` → `readability.Document` 提取主体 → markdown 或纯文本
  - 其他 → 原始文本
- **返回**: JSON 格式字符串，包含 `url`, `finalUrl`, `status`, `extractor`, `truncated`, `length`, `text`
- **Markdown 转换** `_to_markdown()`: 处理 `<a>` → `[text](url)`、`<h1-6>` → `# 标题`、`<li>` → `- 条目`、`</p|div>` → 换行

---

### 3.4 MessageTool（message.py）

- **name**: `message`
- **参数**: `content` (required), `channel`, `chat_id`, `media` (array of paths)
- **设计**: 持有 `send_callback: Callable[[OutboundMessage], Awaitable[None]]`，实际发送由外部注入
- **上下文管理**:
  - `set_context(channel, chat_id, message_id)` — 每条入站消息前调用，设置默认投递目标
  - `start_turn()` — 重置 `_sent_in_turn` 标志
- **OutboundMessage**: `channel`, `chat_id`, `content`, `media: list[str]`, `metadata: {message_id}`
- **返回**: `"Message sent to {channel}:{chat_id}"` 或 `"... with {N} attachments"`

---

### 3.5 CronTool（cron.py）

- **name**: `cron`
- **参数**: `action` (enum: add/list/remove, required), 及调度相关可选参数

| 参数 | 说明 |
|------|------|
| `message` | 提醒内容（add 必需）|
| `every_seconds` | 循环间隔（秒）|
| `cron_expr` | Cron 表达式（如 `"0 9 * * *"`）|
| `tz` | IANA 时区（仅与 cron_expr 配合）|
| `at` | ISO datetime 字符串（一次性执行）|
| `job_id` | 任务 ID（remove 必需）|

#### 三种调度类型

| kind | 参数 | 说明 |
|------|------|------|
| `every` | `every_ms` | 固定间隔循环 |
| `cron` | `expr` + `tz` | cron 表达式，支持时区 |
| `at` | `at_ms` | 一次性执行，执行后自动删除（`delete_after_run=True`）|

- **上下文**: `set_context(channel, chat_id)` — 记录投递目标
- **时区校验**: 使用 `zoneinfo.ZoneInfo(tz)` 验证有效性

---

### 3.6 SpawnTool（spawn.py）

- **name**: `spawn`
- **参数**: `task` (string, required), `label` (string, optional)
- **委托**: 调用 `SubagentManager.spawn(task, label, origin_channel, origin_chat_id)`
- **返回**: `"Subagent [{label}] started (id: {task_id}). I'll notify you when it completes."`
- **上下文**: `set_context(channel, chat_id)` — 记录结果回报目标

#### SubagentManager 实现关键点

- 使用 `asyncio.create_task()` 在后台运行，主 agent 立即得到返回
- 子代理工具集：ReadFile / WriteFile / EditFile / ListDir / Exec / WebSearch / WebFetch（无 message 和 spawn 工具，避免递归）
- 最大迭代次数：15 次
- 完成后通过 `MessageBus.publish_inbound()` 注入 `InboundMessage(channel="system", sender_id="subagent")` 触发主 agent 汇报
- 子代理 system prompt 明确禁止直接发消息和生成子代理

---

### 3.7 MCPToolWrapper（mcp.py）

#### MCPToolWrapper

- **name**: `mcp_{server_name}_{tool_def.name}` — 加前缀避免名称冲突
- **description**: 来自 MCP tool definition
- **parameters**: 来自 `tool_def.inputSchema`（或空 object schema）
- **execute()**: `session.call_tool(original_name, arguments=kwargs)`，含超时控制（默认 30s）
- **输出处理**: 遍历 `result.content`，`TextContent` 转字符串，其他类型 `str()` 转换

#### connect_mcp_servers()

支持两种传输方式：
1. **Stdio**: `StdioServerParameters(command, args, env)` → `stdio_client`
2. **HTTP (streamable)**: `streamable_http_client(url, http_client=httpx.AsyncClient(timeout=None))`

注册流程：
```
for server_name, cfg in mcp_servers.items():
    session = ClientSession(read, write)
    await session.initialize()
    tools = await session.list_tools()
    for tool_def in tools.tools:
        registry.register(MCPToolWrapper(session, server_name, tool_def, cfg.tool_timeout))
```

---

## 四、工具向 LLM 暴露 Schema 的完整流程

```
Tool.to_schema()
    ↓
ToolRegistry.get_definitions()   # [tool.to_schema() for tool in _tools.values()]
    ↓
LLMProvider.chat(tools=definitions)  # 传入标准 OpenAI function-calling 格式
    ↓
LLM 返回 tool_call: {id, name, arguments}
    ↓
ToolRegistry.execute(name, arguments)
    ↓
tool.validate_params(arguments) → tool.execute(**arguments)
```

**schema 格式（OpenAI function-calling）**:
```json
[
  {
    "type": "function",
    "function": {
      "name": "read_file",
      "description": "Read the contents of a file at the given path.",
      "parameters": {
        "type": "object",
        "properties": {
          "path": {"type": "string", "description": "The file path to read"}
        },
        "required": ["path"]
      }
    }
  },
  ...
]
```

---

## 五、安全机制总结

### 文件系统沙箱

| 层次 | 机制 | 实现 |
|------|------|------|
| 工作目录相对路径 | 相对路径自动加 `workspace` 前缀 | `workspace / path` |
| 目录限制 | `Path.resolve().relative_to(allowed_dir.resolve())` | symlink 防逃逸 |
| 错误响应 | `PermissionError` → 返回 Error 字符串 | 不暴露系统细节 |

### Shell 安全

| 层次 | 机制 | 实现 |
|------|------|------|
| 危险命令黑名单 | 正则 deny_patterns | `re.search(pattern, cmd.lower())` |
| 命令白名单 | 可选 allow_patterns | 不匹配任何白名单则 block |
| 路径穿越防护 | `../` 检测 | 字符串匹配 |
| 工作目录限制 | 绝对路径提取 + resolve 判断 | `cwd_path not in p.parents` |
| 执行超时 | `asyncio.wait_for` | 默认 60s，超时 kill |
| 输出截断 | 10000 字符上限 | 防止超长输出 |

### Web 安全

| 层次 | 机制 |
|------|------|
| URL 协议限制 | 仅 http/https |
| 重定向限制 | max_redirects=5 |
| 输出截断 | max_chars（默认 50000）|

---

## 六、已发现的代码 Bug

**文件**: `web.py`，`WebSearchTool.execute()` 第 83 行

```python
# Bug: 使用了未定义的局部变量 api_key
headers={"X-Subscription-Token": api_key},
# 应该是:
headers={"X-Subscription-Token": self.api_key},
```

---

## 七、与本项目现有工具系统的对比

| 特性 | Nanobot | 本项目（AI自进化系统）|
|------|---------|----------------------|
| 工具基类 | `Tool(ABC)` 抽象基类 | 无统一基类 |
| 参数校验 | 内置 JSON Schema 校验 | 无 |
| Registry | `ToolRegistry` 统一管理 | 无 |
| LLM Schema | 自动从 `to_schema()` 生成 | 手动构造 |
| 错误引导 | 所有错误追加 `_HINT` | 无 |
| MCP 集成 | 原生支持 | 无 |
| 子代理工具 | `SpawnTool` + `SubagentManager` | 无正式抽象 |
| 路径沙箱 | `allowed_dir` + `resolve()` | 无 |
| Shell 安全 | deny_patterns + workspace 限制 | 无 |

---

## 参考文件

- `/tmp/nanobot/nanobot/agent/tools/base.py`
- `/tmp/nanobot/nanobot/agent/tools/registry.py`
- `/tmp/nanobot/nanobot/agent/tools/filesystem.py`
- `/tmp/nanobot/nanobot/agent/tools/shell.py`
- `/tmp/nanobot/nanobot/agent/tools/web.py`
- `/tmp/nanobot/nanobot/agent/tools/message.py`
- `/tmp/nanobot/nanobot/agent/tools/cron.py`
- `/tmp/nanobot/nanobot/agent/tools/spawn.py`
- `/tmp/nanobot/nanobot/agent/tools/mcp.py`
- `/tmp/nanobot/nanobot/agent/subagent.py`
- `/tmp/nanobot/nanobot/bus/events.py`
- `/tmp/nanobot/nanobot/cron/types.py`

---

# Part 3: Telegram + 配置 + 消息总线

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
