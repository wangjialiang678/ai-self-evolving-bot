# 调研报告: Nanobot 工具系统源码分析

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
