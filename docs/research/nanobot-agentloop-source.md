# 调研报告: Nanobot Agent Loop + LLM Provider + Context 源码分析

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
