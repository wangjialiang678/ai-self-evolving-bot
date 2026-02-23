# Claude Code Bridge Server — 后端设计方案

> 文档版本：v2.0  
> 日期：2026-02-23（基于 v1.0 2026-02-21 更新）  
> 用途：交给 AI 智能体，照着写代码。同时也是人类可读的技术方案。  
> 前置阅读：《Claude Code 架构研究 — 背景信息文档》

### v2.0 主要变更

- **新增双引擎架构**：Direct CLI 引擎（支持订阅）+ Agent SDK 引擎（支持高级功能）
- **新增认证双模**：API Key 模式（合规）+ 订阅模式（个人使用）
- **扩展 Session 创建参数**：新增 `setting_sources`、`hooks`、`mcp_servers`、`auth_mode` 等
- **新增 Anthropic 政策分析**：明确哪些调用方式合规，哪些有风险
- **参考胡渊鸣方案**：将 `claude -p --output-format stream-json` 直接调用方式纳入引擎 A

---

## 1. 项目目标

开发一个 **Bridge Server（桥接服务器）**，作为 Claude Code CLI 和任意前端之间的中间层。

支持三种客户端接入：

1. **Mac 桌面客户端**：本机直接连接，体验等同 VS Code 插件
2. **手机移动端**：通过网络远程连接，操控运行在服务器上的 Claude Code
3. **本机 AI 智能体调用**：其他智能体（如 OpenClaw 或自研 Agent）通过 API 调用 Claude Code

支持两种认证方式：

4. **API Key 模式**（官方推荐，完全合规）
5. **订阅模式**（个人使用，有政策灰色地带）

---

## 2. 核心架构决策：双引擎

### 2.1 为什么需要两个引擎？

这源于 Anthropic 的一条政策限制：

> **OAuth authentication is intended exclusively for Claude Code and Claude.ai. Using OAuth tokens in any other product, tool, or service — including the Agent SDK — is not permitted.**  
> — Anthropic Usage Policy, 2026-02-17 更新

关键区别：

| 调用方式 | Anthropic 视角 | 订阅（OAuth） | API Key |
|----------|---------------|:---:|:---:|
| `claude -p`（直接调 CLI 二进制） | = 使用 Claude Code 本身 | ✅ 合规 | ✅ 合规 |
| Agent SDK `query()` / `ClaudeSDKClient` | = 第三方使用 SDK | ❌ 被明确禁止 | ✅ 合规 |

所以如果要合规地支持订阅模式，**只能直接调 CLI，不能走 SDK**。但 SDK 提供了多轮对话、中断、Hooks 等高级能力，直接调 CLI 做不到。

结论：两个都要，按场景自动选择。

### 2.2 双引擎对比

| 能力 | 引擎 A：Direct CLI | 引擎 B：Agent SDK |
|------|:---:|:---:|
| **订阅认证** | ✅ | ❌ |
| **API Key 认证** | ✅ | ✅ |
| 单次任务（fire-and-forget） | ✅ 原生模式 | ✅ |
| 多轮对话（保持上下文） | ⚠️ 通过 `--resume` | ✅ 原生支持 |
| 中断当前任务 | ⚠️ kill 进程 | ✅ `client.interrupt()` |
| Hooks（拦截/审计工具调用） | ❌ | ✅ |
| 自定义 MCP 工具（代码内定义） | ❌ | ✅ |
| Plan Mode（先规划再执行） | ✅ `--plan` | ❌ SDK 未暴露 |
| stream-json 实时输出 | ✅ 需自己解析 | ✅ SDK 已封装 |
| CLAUDE.md / Skills | ✅ 原生支持 | ⚠️ 需 `setting_sources` |
| `--dangerously-skip-permissions` | ✅ | ✅ `bypassPermissions` |
| 适合的使用模式 | 批量派发任务 | 交互式对话 |

### 2.3 引擎选择策略

```
用户创建 Session 时指定 auth_mode 和 engine
                │
                ├─ auth_mode = "subscription"
                │   └─ 强制使用引擎 A（Direct CLI）
                │
                ├─ auth_mode = "api_key"
                │   ├─ 需要多轮对话/中断/Hooks？
                │   │   └─ 使用引擎 B（Agent SDK）
                │   └─ 单次任务/批量派发？
                │       └─ 使用引擎 A（Direct CLI）
                │
                └─ 未指定 → 根据环境变量自动检测
                    ├─ 有 CLAUDE_CODE_OAUTH_TOKEN → 引擎 A
                    └─ 有 ANTHROPIC_API_KEY → 引擎 B（默认）
```

---

## 3. 认证方案详解

### 3.1 方式 A：API Key（推荐，完全合规）

```bash
# .env
ANTHROPIC_API_KEY=sk-ant-api03-your-key-here
AUTH_MODE=api_key
```

获取地址：https://console.anthropic.com/

费用参考：Anthropic 官方数据，90% 的开发者每天花费不超过 $12。

### 3.2 方式 B：订阅 OAuth Token（个人使用）

```bash
# 步骤 1：在本机生成长期 token（有效期 1 年）
claude setup-token
# 输出类似：sk-ant-xxx...

# 步骤 2：设置环境变量
# .env
CLAUDE_CODE_OAUTH_TOKEN=sk-ant-xxx...
AUTH_MODE=subscription

# 重要：两种认证不能同时存在
# 不要同时设置 ANTHROPIC_API_KEY 和 CLAUDE_CODE_OAUTH_TOKEN
```

### 3.3 方式 C：继承本机登录状态（仅限本机 Mac 场景）

如果本机已经执行过 `claude login`，CLI 子进程会自动继承 macOS Keychain 中的凭证。此时无需设置任何环境变量，只需确保：

```bash
# .env
AUTH_MODE=subscription
# 不设置 ANTHROPIC_API_KEY（否则会覆盖订阅登录态）
```

### 3.4 政策风险评估

| 场景 | 风险等级 | 说明 |
|------|:---:|------|
| 本机 Mac 桌面，个人自用 | 🟢 极低 | 和直接用 CLI 无区别 |
| 本机智能体调用（引擎 A） | 🟡 低 | CLI 子进程，技术上是 Claude Code 本身 |
| 远程手机调用（引擎 A） | 🟡 中 | 通过网络代理，但只有一个人用 |
| 公开平台多用户共享订阅 | 🔴 高 | 这是 Anthropic 打击的对象（OpenClaw 事件） |
| 任何使用引擎 B + OAuth Token | 🔴 高 | 被政策明确点名禁止 |

**建议**：MVP 阶段用订阅开发验证（省钱），正式部署切 API Key（合规）。

---

## 4. 整体架构

```
                    ┌─────────────┐     ┌─────────────┐
                    │ Mac 桌面 App │     │ 手机 App     │
                    │ (本地客户端)  │     │ (远程客户端)  │
                    └──────┬──────┘     └──────┬──────┘
                           │ WebSocket          │ WebSocket
                           │                    │
          ┌────────────┐   │                    │
          │ 本机 AI 智能体│   │                    │
          └─────┬──────┘   │                    │
                │ REST API  │                    │
                ▼           ▼                    ▼
┌──────────────────────────────────────────────────────────┐
│                   Bridge Server (FastAPI)                 │
│                                                          │
│  ┌────────────────────────────────────────────────────┐  │
│  │               路由层 (Routing Layer)                 │  │
│  │  WebSocket  /ws/{session_id}                       │  │
│  │  REST API   /api/sessions/...                      │  │
│  └────────────────────┬───────────────────────────────┘  │
│                       │                                  │
│  ┌────────────────────▼───────────────────────────────┐  │
│  │            Session Manager（会话管理器）              │  │
│  │                                                    │  │
│  │  SessionState:                                     │  │
│  │    - engine: EngineType (direct_cli / agent_sdk)   │  │
│  │    - auth_mode: AuthMode (api_key / subscription)  │  │
│  │    - status: idle / busy / interrupted             │  │
│  │    - websockets: set[WebSocket]                    │  │
│  └──────────┬─────────────────────┬───────────────────┘  │
│             │                     │                      │
│  ┌──────────▼──────────┐  ┌──────▼───────────────────┐  │
│  │  引擎 A: Direct CLI  │  │  引擎 B: Agent SDK       │  │
│  │                     │  │                          │  │
│  │  subprocess 启动     │  │  ClaudeSDKClient 实例     │  │
│  │  claude -p [prompt]  │  │  多轮对话 + 中断 + Hooks  │  │
│  │  --output-format     │  │  自定义 MCP 工具          │  │
│  │    stream-json       │  │                          │  │
│  │  解析 JSON 输出流     │  │  SDK 封装的 subprocess   │  │
│  │                     │  │                          │  │
│  │  ✅ 订阅 + API Key   │  │  ✅ 仅 API Key           │  │
│  └──────────┬──────────┘  └──────┬───────────────────┘  │
│             │                     │                      │
└─────────────┼─────────────────────┼──────────────────────┘
              │                     │
              ▼                     ▼
     ┌───────────────────────────────────┐
     │       Claude Code CLI (subprocess) │
     └────────────────┬──────────────────┘
                      │ HTTPS
                      ▼
             ┌───────────────────┐
             │   Anthropic API   │
             └───────────────────┘
```

---

## 5. 技术选型

| 组件 | 技术选择 | 原因 |
|------|----------|------|
| 后端框架 | **FastAPI** | 原生支持 async、WebSocket、自动 API 文档 |
| 引擎 A | **Python subprocess + stream-json 解析** | 直接调 CLI，支持订阅认证 |
| 引擎 B | **claude-agent-sdk (Python)** | 官方 SDK，多轮对话/中断/Hooks |
| 实时通信 | **WebSocket** | 流式响应必须 |
| 智能体调用 | **REST API** | 通用、简单 |
| 认证 | **Bearer Token** | 简单实用，后续可升级为 JWT |
| Python 版本 | **3.10+** | Agent SDK 的最低要求 |
| Node.js | **18+** | Claude Code CLI 的运行时依赖 |

---

## 6. 详细设计

### 6.1 项目文件结构

```
claude-code-bridge/
├── README.md
├── requirements.txt
├── .env                          # 环境变量配置
├── server.py                     # 主入口（FastAPI 应用）
├── session_manager.py            # 会话管理器（调度双引擎）
├── engine_direct_cli.py          # 引擎 A：Direct CLI 调用
├── engine_agent_sdk.py           # 引擎 B：Agent SDK 封装
├── stream_parser.py              # 引擎 A 的 stream-json 解析器
├── message_handler.py            # 统一消息格式转换
├── auth.py                       # 认证中间件
└── models.py                     # 数据模型定义
```

### 6.2 环境变量配置（.env）

```bash
# 服务器配置
HOST=0.0.0.0
PORT=8000

# Bridge Server 认证（客户端访问 Bridge Server 用的 token）
API_TOKEN=your-secret-token-here

# ========== Claude Code 认证（二选一）==========

# 方式 A：API Key（推荐，完全合规）
ANTHROPIC_API_KEY=sk-ant-api03-your-key-here

# 方式 B：订阅 OAuth Token（个人使用）
# CLAUDE_CODE_OAUTH_TOKEN=sk-ant-xxx-TOKEN

# 注意：不要同时设置两个。如果都设置了，API Key 优先。

# ========== 默认配置 ==========
DEFAULT_MODEL=sonnet                     # 默认模型
DEFAULT_PERMISSION_MODE=acceptEdits      # 默认权限模式
DEFAULT_PROJECT_PATH=/path/to/project    # 默认工作目录
DEFAULT_ENGINE=auto                      # auto / direct_cli / agent_sdk
MAX_SESSIONS=5                           # 最大并发会话数
SESSION_TIMEOUT_MINUTES=60               # 会话超时时间

# ========== 可选 ==========
# CLAUDE_CODE_USE_BEDROCK=1    # 使用 Amazon Bedrock
# CLAUDE_CODE_USE_VERTEX=1     # 使用 Google Vertex AI
```

### 6.3 数据模型定义（models.py）

```python
from pydantic import BaseModel
from enum import Enum
from datetime import datetime

# ========== 枚举类型 ==========

class AuthMode(str, Enum):
    API_KEY = "api_key"
    SUBSCRIPTION = "subscription"
    AUTO = "auto"                        # 根据环境变量自动检测

class EngineType(str, Enum):
    DIRECT_CLI = "direct_cli"            # 引擎 A：直接调 CLI
    AGENT_SDK = "agent_sdk"              # 引擎 B：Agent SDK
    AUTO = "auto"                        # 根据 auth_mode 和需求自动选择

class SessionStatus(str, Enum):
    IDLE = "idle"
    BUSY = "busy"
    INTERRUPTED = "interrupted"
    ERROR = "error"
    CLOSED = "closed"

# ========== 请求模型 ==========

class CreateSessionRequest(BaseModel):
    """创建新会话的请求"""
    # 基础配置
    project_path: str | None = None
    model: str | None = None
    system_prompt: str | None = None
    allowed_tools: list[str] | None = None
    permission_mode: str | None = None

    # 引擎和认证（v2 新增）
    engine: EngineType = EngineType.AUTO
    auth_mode: AuthMode = AuthMode.AUTO

    # SDK 高级功能（仅引擎 B 生效）
    setting_sources: list[str] | None = None   # ["project"] 以加载 CLAUDE.md
    hooks_preset: str | None = None            # 预设的 Hook 配置名
    mcp_servers_config: dict | None = None     # MCP 服务器配置
    max_turns: int | None = None               # 最大对话轮次
    max_budget_usd: float | None = None        # 最大花费（美元）

    # CLI 高级功能（仅引擎 A 生效）
    verbose: bool = True                       # --verbose
    plan_mode: bool = False                    # --plan（先规划再执行）

class SendMessageRequest(BaseModel):
    """发送消息的请求"""
    content: str

class SessionInfo(BaseModel):
    """会话信息（返回给客户端）"""
    session_id: str
    status: SessionStatus
    engine: EngineType
    auth_mode: AuthMode
    project_path: str
    model: str
    created_at: datetime
    message_count: int

class StreamMessage(BaseModel):
    """推送给客户端的流式消息（两个引擎的统一输出格式）"""
    type: str                # text / tool_use / tool_result / thinking / result / error / status
    content: str | None = None
    tool_name: str | None = None
    tool_input: dict | None = None
    is_final: bool = False
    metadata: dict | None = None
```

### 6.4 引擎 A：Direct CLI（engine_direct_cli.py）

这是参考胡渊鸣方案实现的引擎，直接调 `claude -p` 命令，解析 stream-json 输出。

**核心优势：可以合规使用订阅额度。**

```python
import asyncio
import json
import os
import shutil
import signal
from dataclasses import dataclass, field
from models import StreamMessage, AuthMode

@dataclass
class CLISession:
    """引擎 A 的会话状态"""
    session_id: str
    process: asyncio.subprocess.Process | None = None
    cli_session_id: str | None = None   # Claude Code 内部 session ID，用于 --resume
    project_path: str = "."
    model: str = "sonnet"
    permission_mode: str = "acceptEdits"
    verbose: bool = True

class DirectCLIEngine:
    """
    引擎 A：直接调用 Claude Code CLI。
    
    调用方式：
        claude -p [prompt] --output-format stream-json [--verbose]
              [--model sonnet] [--permission-mode acceptEdits]
              [--resume SESSION_ID]
    
    解析 stdout 的 JSON 流获取响应。
    支持订阅认证（OAuth Token）。
    """
    
    def __init__(self, auth_mode: AuthMode = AuthMode.AUTO):
        self.auth_mode = auth_mode
        self._cli_path = self._find_cli()
    
    def _find_cli(self) -> str:
        """查找 claude CLI 可执行文件路径"""
        path = shutil.which("claude")
        if not path:
            raise FileNotFoundError(
                "Claude Code CLI 未找到。请安装: npm install -g @anthropic-ai/claude-code"
            )
        return path
    
    def _build_env(self) -> dict:
        """构建子进程的环境变量"""
        env = os.environ.copy()
        
        if self.auth_mode == AuthMode.SUBSCRIPTION:
            # 订阅模式：确保使用 OAuth Token，移除 API Key
            if "ANTHROPIC_API_KEY" in env:
                del env["ANTHROPIC_API_KEY"]
            # CLAUDE_CODE_OAUTH_TOKEN 应该已在环境变量中
            # 或者 CLI 会从 macOS Keychain / ~/.claude/.credentials.json 读取
        
        elif self.auth_mode == AuthMode.API_KEY:
            # API Key 模式：确保使用 API Key
            if "CLAUDE_CODE_OAUTH_TOKEN" in env:
                del env["CLAUDE_CODE_OAUTH_TOKEN"]
        
        # AUTO 模式：不修改环境变量，让 CLI 自己决定
        return env
    
    def _build_command(
        self,
        prompt: str,
        session: CLISession,
        plan_mode: bool = False,
    ) -> list[str]:
        """构建 CLI 命令"""
        cmd = [self._cli_path, "-p", prompt]
        
        # 输出格式
        cmd.extend(["--output-format", "stream-json"])
        
        # 模型
        if session.model:
            cmd.extend(["--model", session.model])
        
        # 权限
        if session.permission_mode == "bypassPermissions":
            cmd.append("--dangerously-skip-permissions")
        elif session.permission_mode:
            cmd.extend(["--permission-mode", session.permission_mode])
        
        # 详细输出
        if session.verbose:
            cmd.append("--verbose")
        
        # Plan 模式
        if plan_mode:
            cmd.append("--plan")
        
        # 恢复之前的会话（实现多轮对话的关键）
        if session.cli_session_id:
            cmd.extend(["--resume", session.cli_session_id])
        
        return cmd
    
    async def execute(
        self,
        prompt: str,
        session: CLISession,
        plan_mode: bool = False,
    ) -> AsyncIterator[StreamMessage]:
        """
        执行一次 CLI 调用，yield 流式消息。
        
        这是引擎 A 的核心方法。每次调用启动一个新的 CLI 子进程，
        通过 --resume 参数实现跨调用的上下文保持。
        """
        cmd = self._build_command(prompt, session, plan_mode)
        env = self._build_env()
        
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=session.project_path,
            env=env,
        )
        session.process = process
        
        try:
            # 逐行读取 stdout，解析 stream-json
            async for line in process.stdout:
                line = line.decode("utf-8").strip()
                if not line:
                    continue
                
                try:
                    data = json.loads(line)
                    msg = self._parse_stream_json(data)
                    if msg:
                        # 捕获 session ID 用于后续 --resume
                        if data.get("sessionId"):
                            session.cli_session_id = data["sessionId"]
                        yield msg
                except json.JSONDecodeError:
                    continue  # 跳过非 JSON 行
            
            # 等待进程结束
            await process.wait()
            
            if process.returncode != 0:
                stderr = await process.stderr.read()
                error_text = stderr.decode("utf-8").strip()
                yield StreamMessage(
                    type="error",
                    content=f"CLI 退出码 {process.returncode}: {error_text}",
                    is_final=True,
                )
            else:
                yield StreamMessage(
                    type="status",
                    content="completed",
                    is_final=True,
                )
        
        except asyncio.CancelledError:
            # 被中断
            process.send_signal(signal.SIGINT)
            await process.wait()
            yield StreamMessage(
                type="status",
                content="interrupted",
                is_final=True,
            )
        
        finally:
            session.process = None
    
    async def interrupt(self, session: CLISession) -> None:
        """中断当前执行（发送 SIGINT，等同于用户按 Ctrl+C）"""
        if session.process and session.process.returncode is None:
            session.process.send_signal(signal.SIGINT)
    
    def _parse_stream_json(self, data: dict) -> StreamMessage | None:
        """
        解析 Claude Code CLI 的 stream-json 输出。
        
        CLI 输出的 JSON 格式示例：
        
        {"type": "assistant", "message": {"content": [{"type": "text", "text": "..."}]}}
        {"type": "tool_use", "name": "Edit", "input": {...}}
        {"type": "tool_result", "content": "...", "subtype": "success"}
        {"type": "result", "subtype": "success", "duration_ms": 3302, "session_id": "..."}
        {"type": "system", "subtype": "init", "sessionId": "..."}
        """
        msg_type = data.get("type")
        
        if msg_type == "assistant":
            message = data.get("message", {})
            content_blocks = message.get("content", [])
            for block in content_blocks:
                block_type = block.get("type")
                if block_type == "text":
                    return StreamMessage(type="text", content=block.get("text", ""))
                elif block_type == "tool_use":
                    return StreamMessage(
                        type="tool_use",
                        tool_name=block.get("name"),
                        tool_input=block.get("input"),
                        content=f"正在使用工具: {block.get('name')}",
                    )
                elif block_type == "thinking":
                    return StreamMessage(type="thinking", content=block.get("text", ""))
        
        elif msg_type == "tool_result":
            return StreamMessage(
                type="tool_result",
                content=str(data.get("content", "")),
            )
        
        elif msg_type == "result":
            return StreamMessage(
                type="result",
                content=data.get("result", "完成"),
                is_final=True,
                metadata={
                    "duration_ms": data.get("duration_ms"),
                    "num_turns": data.get("num_turns"),
                    "session_id": data.get("session_id"),
                    "subtype": data.get("subtype"),
                },
            )
        
        elif msg_type == "system":
            # 系统消息（初始化、配置等），通常不需要推送给客户端
            # 但 sessionId 需要捕获
            return None
        
        return None
```

### 6.5 引擎 B：Agent SDK（engine_agent_sdk.py）

这是 v1 方案中的原有引擎，基于官方 Agent SDK 的 `ClaudeSDKClient`。

**核心优势：多轮对话、中断、Hooks、自定义 MCP 工具。**

```python
import asyncio
from dataclasses import dataclass, field
from typing import AsyncIterator
from claude_agent_sdk import (
    ClaudeSDKClient,
    ClaudeAgentOptions,
    AssistantMessage,
    ResultMessage,
    TextBlock,
    ToolUseBlock,
    ToolResultBlock,
    ThinkingBlock,
)
from models import StreamMessage

@dataclass
class SDKSession:
    """引擎 B 的会话状态"""
    session_id: str
    client: ClaudeSDKClient
    options: ClaudeAgentOptions
    project_path: str = "."
    model: str = "sonnet"

class AgentSDKEngine:
    """
    引擎 B：基于 Claude Agent SDK 的 ClaudeSDKClient。
    
    提供完整的多轮对话、中断、Hook、自定义工具支持。
    仅支持 API Key 认证。
    """
    
    async def create_client(
        self,
        project_path: str = ".",
        model: str = "sonnet",
        system_prompt: str | None = None,
        allowed_tools: list[str] | None = None,
        permission_mode: str = "acceptEdits",
        setting_sources: list[str] | None = None,
        hooks: dict | None = None,
        mcp_servers: dict | None = None,
        max_turns: int | None = None,
        max_budget_usd: float | None = None,
    ) -> tuple[ClaudeSDKClient, ClaudeAgentOptions]:
        """创建并连接一个 ClaudeSDKClient 实例"""
        
        options = ClaudeAgentOptions(
            cwd=project_path,
            model=model,
            system_prompt=system_prompt,
            allowed_tools=allowed_tools or [
                "Read", "Write", "Edit", "MultiEdit",
                "Bash", "Glob", "Grep", "WebSearch", "WebFetch"
            ],
            permission_mode=permission_mode,
            setting_sources=setting_sources or ["project"],
            hooks=hooks,
            mcp_servers=mcp_servers or {},
            max_turns=max_turns,
            max_budget_usd=max_budget_usd,
        )
        
        client = ClaudeSDKClient(options=options)
        await client.connect()
        return client, options
    
    async def send_message(
        self,
        client: ClaudeSDKClient,
    prompt: str,
    ) -> AsyncIterator[StreamMessage]:
        """发送消息并 yield 流式响应"""
        
        await client.query(prompt)
        
        async for msg in client.receive_response():
            stream_msg = self._convert_message(msg)
            if stream_msg:
                yield stream_msg
        
        yield StreamMessage(
            type="status",
            content="completed",
            is_final=True,
        )
    
    async def interrupt(self, client: ClaudeSDKClient) -> None:
        """中断当前任务"""
        await client.interrupt()
    
    async def disconnect(self, client: ClaudeSDKClient) -> None:
        """断开连接"""
        try:
            await client.disconnect()
        except Exception:
            pass
    
    def _convert_message(self, msg) -> StreamMessage | None:
        """将 SDK Message 转换为统一的 StreamMessage"""
        
        if isinstance(msg, AssistantMessage):
            for block in msg.content:
                if isinstance(block, TextBlock):
                    return StreamMessage(type="text", content=block.text)
                elif isinstance(block, ToolUseBlock):
                    return StreamMessage(
                        type="tool_use",
                        tool_name=block.name,
                        tool_input=block.input if hasattr(block, "input") else None,
                        content=f"正在使用工具: {block.name}",
                    )
                elif isinstance(block, ThinkingBlock):
                    return StreamMessage(
                        type="thinking",
                        content=block.text if hasattr(block, "text") else None,
                    )
        
        elif isinstance(msg, ResultMessage):
            return StreamMessage(
                type="result",
                content=msg.result if hasattr(msg, "result") else "完成",
                is_final=True,
                metadata={
                    "duration_ms": getattr(msg, "duration_ms", None),
                    "num_turns": getattr(msg, "num_turns", None),
                },
            )
        
        return None
```

### 6.6 Session Manager（session_manager.py）

Session Manager 是调度层，根据配置选择引擎，提供统一接口。

```python
import asyncio
import os
import uuid
from datetime import datetime
from dataclasses import dataclass, field
from fastapi import WebSocket
from models import (
    SessionStatus, EngineType, AuthMode,
    StreamMessage, CreateSessionRequest,
)
from engine_direct_cli import DirectCLIEngine, CLISession
from engine_agent_sdk import AgentSDKEngine, SDKSession

@dataclass
class SessionState:
    """统一的会话状态（两个引擎共用）"""
    session_id: str
    engine_type: EngineType
    auth_mode: AuthMode
    status: SessionStatus = SessionStatus.IDLE
    websockets: set = field(default_factory=set)
    message_count: int = 0
    created_at: datetime = field(default_factory=datetime.now)
    project_path: str = ""
    model: str = "sonnet"
    
    # 引擎 A 的状态
    cli_session: CLISession | None = None
    
    # 引擎 B 的状态
    sdk_session: SDKSession | None = None

class SessionManager:
    """管理所有 Claude Code 会话，调度双引擎"""
    
    def __init__(self, max_sessions: int = 5, default_project_path: str = "."):
        self.sessions: dict[str, SessionState] = {}
        self.max_sessions = max_sessions
        self.default_project_path = default_project_path
        
        # 初始化两个引擎
        self.cli_engine = DirectCLIEngine()
        self.sdk_engine = AgentSDKEngine()
    
    def _resolve_auth_mode(self, requested: AuthMode) -> AuthMode:
        """解析实际的认证模式"""
        if requested != AuthMode.AUTO:
            return requested
        
        # AUTO：根据环境变量判断
        if os.getenv("CLAUDE_CODE_OAUTH_TOKEN"):
            return AuthMode.SUBSCRIPTION
        elif os.getenv("ANTHROPIC_API_KEY"):
            return AuthMode.API_KEY
        else:
            # 默认假设本机有登录态
            return AuthMode.SUBSCRIPTION
    
    def _resolve_engine(self, requested: EngineType, auth_mode: AuthMode) -> EngineType:
        """解析实际的引擎类型"""
        if requested != EngineType.AUTO:
            # 校验：订阅模式不允许用引擎 B
            if requested == EngineType.AGENT_SDK and auth_mode == AuthMode.SUBSCRIPTION:
                raise ValueError(
                    "订阅模式不支持 Agent SDK 引擎（Anthropic 政策限制）。"
                    "请使用 engine=direct_cli 或切换到 API Key 认证。"
                )
            return requested
        
        # AUTO：订阅 → 引擎 A，API Key → 引擎 B
        if auth_mode == AuthMode.SUBSCRIPTION:
            return EngineType.DIRECT_CLI
        else:
            return EngineType.AGENT_SDK
    
    async def create_session(self, req: CreateSessionRequest) -> SessionState:
        """创建新会话"""
        
        if len(self.sessions) >= self.max_sessions:
            raise RuntimeError(f"已达到最大会话数 {self.max_sessions}")
        
        session_id = str(uuid.uuid4())[:8]
        project_path = req.project_path or self.default_project_path
        model = req.model or "sonnet"
        
        # 解析认证和引擎
        auth_mode = self._resolve_auth_mode(req.auth_mode)
        engine_type = self._resolve_engine(req.engine, auth_mode)
        
        session = SessionState(
            session_id=session_id,
            engine_type=engine_type,
            auth_mode=auth_mode,
            project_path=project_path,
            model=model,
        )
        
        if engine_type == EngineType.DIRECT_CLI:
            # 引擎 A：创建 CLI 会话（轻量级，不启动进程）
            session.cli_session = CLISession(
                session_id=session_id,
                project_path=project_path,
                model=model,
                permission_mode=req.permission_mode or "acceptEdits",
                verbose=req.verbose,
            )
            self.cli_engine.auth_mode = auth_mode
        
        elif engine_type == EngineType.AGENT_SDK:
            # 引擎 B：创建 SDK 客户端（启动 CLI 子进程）
            client, options = await self.sdk_engine.create_client(
                project_path=project_path,
                model=model,
                system_prompt=req.system_prompt,
                allowed_tools=req.allowed_tools,
                permission_mode=req.permission_mode or "acceptEdits",
                setting_sources=req.setting_sources,
                hooks=None,                          # TODO: 从 hooks_preset 解析
                mcp_servers=req.mcp_servers_config,
                max_turns=req.max_turns,
                max_budget_usd=req.max_budget_usd,
            )
            session.sdk_session = SDKSession(
                session_id=session_id,
                client=client,
                options=options,
                project_path=project_path,
                model=model,
            )
        
        self.sessions[session_id] = session
        return session
    
    async def send_message(self, session_id: str, content: str) -> None:
        """发送消息（自动路由到正确的引擎）"""
        
        session = self.sessions.get(session_id)
        if not session:
            raise KeyError(f"会话 {session_id} 不存在")
        if session.status == SessionStatus.BUSY:
            raise RuntimeError("会话正忙，请等待当前任务完成或中断")
        
        session.status = SessionStatus.BUSY
        session.message_count += 1
        
        try:
            if session.engine_type == EngineType.DIRECT_CLI:
                # 引擎 A
                async for msg in self.cli_engine.execute(
                    prompt=content,
                    session=session.cli_session,
                ):
                    await self._broadcast(session, msg)
            
            elif session.engine_type == EngineType.AGENT_SDK:
                # 引擎 B
                async for msg in self.sdk_engine.send_message(
                    client=session.sdk_session.client,
                    prompt=content,
                ):
                    await self._broadcast(session, msg)
        
        except Exception as e:
            session.status = SessionStatus.ERROR
            await self._broadcast(session, StreamMessage(
                type="error", content=str(e), is_final=True,
            ))
            raise
        finally:
            if session.status == SessionStatus.BUSY:
                session.status = SessionStatus.IDLE
    
    async def interrupt(self, session_id: str) -> None:
        """中断当前任务"""
        session = self.sessions.get(session_id)
        if not session:
            raise KeyError(f"会话 {session_id} 不存在")
        
        if session.engine_type == EngineType.DIRECT_CLI:
            await self.cli_engine.interrupt(session.cli_session)
        elif session.engine_type == EngineType.AGENT_SDK:
            await self.sdk_engine.interrupt(session.sdk_session.client)
        
        session.status = SessionStatus.INTERRUPTED
        await self._broadcast(session, StreamMessage(
            type="status", content="interrupted", is_final=True,
        ))
    
    async def close_session(self, session_id: str) -> None:
        """关闭并销毁会话"""
        session = self.sessions.pop(session_id, None)
        if not session:
            return
        
        session.status = SessionStatus.CLOSED
        
        # 清理引擎资源
        if session.engine_type == EngineType.DIRECT_CLI and session.cli_session:
            await self.cli_engine.interrupt(session.cli_session)
        elif session.engine_type == EngineType.AGENT_SDK and session.sdk_session:
            await self.sdk_engine.disconnect(session.sdk_session.client)
        
        # 关闭所有 WebSocket
        for ws in session.websockets.copy():
            try:
                await ws.close()
            except Exception:
                pass
    
    def register_websocket(self, session_id: str, ws: WebSocket) -> None:
        session = self.sessions.get(session_id)
        if session:
            session.websockets.add(ws)
    
    def unregister_websocket(self, session_id: str, ws: WebSocket) -> None:
        session = self.sessions.get(session_id)
        if session:
            session.websockets.discard(ws)
    
    async def _broadcast(self, session: SessionState, msg: StreamMessage) -> None:
        """广播消息给会话的所有 WebSocket 客户端"""
        data = msg.model_dump_json()
        dead = set()
        for ws in session.websockets:
            try:
                await ws.send_text(data)
            except Exception:
                dead.add(ws)
        session.websockets -= dead
```

### 6.7 主服务入口（server.py）

路由层的代码与 v1 基本相同，主要变更在 `create_session` 接口：

```python
import os
import asyncio
from contextlib import asynccontextmanager
from dotenv import load_dotenv
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Depends, Header
from fastapi.middleware.cors import CORSMiddleware

from session_manager import SessionManager
from models import (
    CreateSessionRequest, SendMessageRequest,
    SessionInfo, StreamMessage, EngineType, AuthMode,
)

load_dotenv()

API_TOKEN = os.getenv("API_TOKEN", "default-dev-token")
MAX_SESSIONS = int(os.getenv("MAX_SESSIONS", "5"))
DEFAULT_PROJECT_PATH = os.getenv("DEFAULT_PROJECT_PATH", os.getcwd())

manager: SessionManager = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    global manager
    manager = SessionManager(
        max_sessions=MAX_SESSIONS,
        default_project_path=DEFAULT_PROJECT_PATH,
    )
    yield
    for sid in list(manager.sessions.keys()):
        await manager.close_session(sid)

app = FastAPI(
    title="Claude Code Bridge Server",
    description="双引擎桥接 Claude Code CLI — 支持订阅和 API Key 双模认证",
    version="2.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ========== 认证 ==========

async def verify_token(authorization: str = Header(None)):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid token")
    token = authorization.split(" ", 1)[1]
    if token != API_TOKEN:
        raise HTTPException(status_code=403, detail="Invalid token")

# ========== REST API ==========

@app.post("/api/sessions", response_model=SessionInfo)
async def create_session(req: CreateSessionRequest, _=Depends(verify_token)):
    """创建新的 Claude Code 会话
    
    关键参数：
    - engine: auto(默认) / direct_cli / agent_sdk
    - auth_mode: auto(默认) / api_key / subscription
    
    如果 auth_mode=subscription，引擎会强制切换为 direct_cli（Anthropic 政策要求）。
    """
    try:
        session = await manager.create_session(req)
        return SessionInfo(
            session_id=session.session_id,
            status=session.status,
            engine=session.engine_type,
            auth_mode=session.auth_mode,
            project_path=session.project_path,
            model=session.model,
            created_at=session.created_at,
            message_count=session.message_count,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=429, detail=str(e))

@app.post("/api/sessions/{session_id}/send")
async def send_message(session_id: str, req: SendMessageRequest, _=Depends(verify_token)):
    """向指定会话发送消息（同步等待完成）"""
    try:
        collected = []
        original_broadcast = manager._broadcast
        
        async def collecting_broadcast(sess, msg):
            collected.append(msg.model_dump())
            await original_broadcast(sess, msg)
        
        manager._broadcast = collecting_broadcast
        try:
            await manager.send_message(session_id, req.content)
        finally:
            manager._broadcast = original_broadcast
        
        return {"session_id": session_id, "messages": collected}
    except KeyError:
        raise HTTPException(status_code=404, detail="会话不存在")
    except RuntimeError as e:
        raise HTTPException(status_code=409, detail=str(e))

@app.post("/api/sessions/{session_id}/interrupt")
async def interrupt_session(session_id: str, _=Depends(verify_token)):
    """中断当前任务"""
    try:
        await manager.interrupt(session_id)
        return {"status": "interrupted"}
    except KeyError:
        raise HTTPException(status_code=404, detail="会话不存在")

@app.get("/api/sessions/{session_id}", response_model=SessionInfo)
async def get_session(session_id: str, _=Depends(verify_token)):
    """查询会话状态"""
    session = manager.sessions.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="会话不存在")
    return SessionInfo(
        session_id=session.session_id,
        status=session.status,
        engine=session.engine_type,
        auth_mode=session.auth_mode,
        project_path=session.project_path,
        model=session.model,
        created_at=session.created_at,
        message_count=session.message_count,
    )

@app.get("/api/sessions")
async def list_sessions(_=Depends(verify_token)):
    """列出所有活跃会话"""
    return [
        SessionInfo(
            session_id=s.session_id,
            status=s.status,
            engine=s.engine_type,
            auth_mode=s.auth_mode,
            project_path=s.project_path,
            model=s.model,
            created_at=s.created_at,
            message_count=s.message_count,
        )
        for s in manager.sessions.values()
    ]

@app.delete("/api/sessions/{session_id}")
async def delete_session(session_id: str, _=Depends(verify_token)):
    """销毁会话"""
    await manager.close_session(session_id)
    return {"status": "closed"}

# ========== WebSocket ==========

@app.websocket("/ws/{session_id}")
async def websocket_endpoint(ws: WebSocket, session_id: str):
    """WebSocket 连接入口（与 v1 相同，双引擎对客户端透明）"""
    await ws.accept()
    
    try:
        auth_data = await asyncio.wait_for(ws.receive_json(), timeout=10)
        if auth_data.get("type") != "auth" or auth_data.get("token") != API_TOKEN:
            await ws.send_json({"type": "error", "content": "认证失败"})
            await ws.close(code=4001)
            return
    except (asyncio.TimeoutError, Exception):
        await ws.close(code=4001)
        return
    
    if session_id not in manager.sessions:
        await ws.send_json({"type": "error", "content": f"会话 {session_id} 不存在"})
        await ws.close(code=4004)
        return
    
    manager.register_websocket(session_id, ws)
    
    # 告知客户端当前引擎信息
    session = manager.sessions[session_id]
    await ws.send_json({
        "type": "status",
        "content": "connected",
        "metadata": {
            "engine": session.engine_type.value,
            "auth_mode": session.auth_mode.value,
        },
    })
    
    try:
        while True:
            data = await ws.receive_json()
            msg_type = data.get("type")
            
            if msg_type == "message":
                content = data.get("content", "")
                if content:
                    asyncio.create_task(
                        _safe_send(manager, session_id, content, ws)
                    )
            elif msg_type == "interrupt":
                try:
                    await manager.interrupt(session_id)
                except Exception as e:
                    await ws.send_json({"type": "error", "content": str(e)})
            elif msg_type == "ping":
                await ws.send_json({"type": "pong"})
    
    except WebSocketDisconnect:
        pass
    finally:
        manager.unregister_websocket(session_id, ws)

async def _safe_send(mgr, session_id, content, ws):
    try:
        await mgr.send_message(session_id, content)
    except Exception as e:
        try:
            await ws.send_json({"type": "error", "content": str(e), "is_final": True})
        except Exception:
            pass

# ========== 健康检查 ==========

@app.get("/health")
async def health():
    return {
        "status": "ok",
        "active_sessions": len(manager.sessions) if manager else 0,
        "max_sessions": MAX_SESSIONS,
        "default_engine": os.getenv("DEFAULT_ENGINE", "auto"),
        "auth_configured": {
            "api_key": bool(os.getenv("ANTHROPIC_API_KEY")),
            "oauth_token": bool(os.getenv("CLAUDE_CODE_OAUTH_TOKEN")),
        },
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "server:app",
        host=os.getenv("HOST", "0.0.0.0"),
        port=int(os.getenv("PORT", "8000")),
        reload=True,
    )
```

### 6.8 依赖清单（requirements.txt）

```
fastapi>=0.110.0
uvicorn[standard]>=0.27.0
websockets>=12.0
python-dotenv>=1.0.0
claude-agent-sdk>=0.1.0
pydantic>=2.0.0
```

---

## 7. 客户端接入指南

### 7.1 创建会话时的引擎选择

```bash
# 使用订阅（自动选择引擎 A）
curl -X POST http://localhost:8000/api/sessions \
  -H "Authorization: Bearer your-token" \
  -H "Content-Type: application/json" \
  -d '{
    "project_path": "/path/to/project",
    "auth_mode": "subscription"
  }'

# 使用 API Key + 交互式对话（自动选择引擎 B）
curl -X POST http://localhost:8000/api/sessions \
  -H "Authorization: Bearer your-token" \
  -H "Content-Type: application/json" \
  -d '{
    "project_path": "/path/to/project",
    "auth_mode": "api_key",
    "setting_sources": ["project"],
    "max_budget_usd": 5.0
  }'

# 使用 API Key + 强制引擎 A（单次任务模式）
curl -X POST http://localhost:8000/api/sessions \
  -H "Authorization: Bearer your-token" \
  -H "Content-Type: application/json" \
  -d '{
    "project_path": "/path/to/project",
    "auth_mode": "api_key",
    "engine": "direct_cli",
    "plan_mode": true
  }'
```

### 7.2 双引擎对客户端透明

创建 session 之后，WebSocket 的使用方式**完全相同**，无论底层是引擎 A 还是引擎 B：

```
→ {"type": "auth", "token": "..."}
← {"type": "status", "content": "connected", "metadata": {"engine": "direct_cli", "auth_mode": "subscription"}}

→ {"type": "message", "content": "重构 auth 模块"}
← {"type": "text", "content": "让我来看看..."}
← {"type": "tool_use", "tool_name": "Read", "content": "正在使用工具: Read"}
← {"type": "tool_result", "content": "..."}
← {"type": "text", "content": "我发现了一个问题..."}
← {"type": "status", "content": "completed", "is_final": true}
```

唯一的区别在 `connected` 消息的 `metadata` 中会告诉客户端当前使用的引擎和认证模式。

### 7.3 引擎 A 的多轮对话

引擎 A（Direct CLI）通过 `--resume` 参数实现上下文保持：

- 第一次调用：CLI 返回 `session_id`，Bridge Server 自动捕获并存储
- 后续调用：自动追加 `--resume <session_id>`，Claude 恢复上下文

这意味着引擎 A 也能做多轮对话，但体验和引擎 B 有细微差别：每次调用都是一个新的 CLI 进程（有几百毫秒的启动开销），而引擎 B 的 `ClaudeSDKClient` 是一个持久进程。

---

## 8. 消息类型完整对照表

两个引擎的输出都统一为 `StreamMessage` 格式，客户端无需区分：

| type | 含义 | content | 其他字段 | UI 建议 |
|------|------|---------|----------|---------|
| `text` | Claude 的文字回复 | 文本内容 | — | Markdown 渲染 |
| `tool_use` | 正在调用工具 | 描述文字 | `tool_name`, `tool_input` | 状态提示 |
| `tool_result` | 工具执行结果 | 结果内容 | — | 可折叠代码块 |
| `thinking` | 推理过程 | 思考内容 | — | 灰色/折叠 |
| `result` | 最终结果 | 摘要 | `metadata`（耗时等） | 完成标记 |
| `error` | 错误 | 错误描述 | — | 红色提示 |
| `status` | 状态变更 | connected/completed/interrupted | `metadata`, `is_final` | 状态指示器 |
| `pong` | 心跳 | — | — | 不展示 |

---

## 9. 安全注意事项

### 9.1 必须做的

- 生产环境配置防火墙或仅绑定内网 IP
- 远程访问使用 WSS（Nginx 反向代理 + SSL）
- API Token 环境变量，不硬编码
- `permission_mode` 推荐 `acceptEdits`
- **不要同时设置 `ANTHROPIC_API_KEY` 和 `CLAUDE_CODE_OAUTH_TOKEN`**

### 9.2 引擎特定的安全考虑

| 安全措施 | 引擎 A | 引擎 B |
|----------|--------|--------|
| 拦截危险命令 | 在 prompt 构建前检查 | 通过 Hook / `can_use_tool` |
| 限制工作目录 | 校验 `cwd` 参数 | `ClaudeAgentOptions.cwd` |
| 费用控制 | 无内置机制 | `max_budget_usd` |
| 操作审计 | 解析 stream-json 日志 | Hook `PostToolUse` |

### 9.3 订阅模式特别注意

- `setup-token` 生成的 token 有效期 1 年，保管好
- 订阅额度与 claude.ai 网页端共享（5 小时滚动窗口）
- 不要把 OAuth Token 分享给他人或用于公开服务
- Anthropic 可能随时收紧政策，做好切换到 API Key 的准备

---

## 10. 部署方式

### 10.1 本地开发

```bash
pip install -r requirements.txt

# 配置认证（二选一）
export ANTHROPIC_API_KEY="sk-ant-api03-..."    # API Key
# 或
export CLAUDE_CODE_OAUTH_TOKEN="sk-ant-xxx-..."  # 订阅 Token

# 启动
python server.py
# http://localhost:8000
# API 文档：http://localhost:8000/docs
```

### 10.2 远程服务器

```bash
pip install -r requirements.txt
npm install -g @anthropic-ai/claude-code

# 如果用订阅模式，需要先在本机生成 token 再传到服务器
# 本机：claude setup-token → 复制 token
# 服务器：export CLAUDE_CODE_OAUTH_TOKEN="sk-ant-xxx-..."

# Nginx 配置（WebSocket 支持）
# location /ws/ {
#     proxy_pass http://127.0.0.1:8000;
#     proxy_http_version 1.1;
#     proxy_set_header Upgrade $http_upgrade;
#     proxy_set_header Connection "upgrade";
#     proxy_read_timeout 3600s;    # 重要：WebSocket 长连接超时
# }

uvicorn server:app --host 127.0.0.1 --port 8000
```

---

## 11. 待办事项清单

### Phase 1：核心双引擎（预计 2-3 天）

- [ ] 搭建项目结构
- [ ] 实现 `models.py` 数据模型
- [ ] 实现 `engine_direct_cli.py`（引擎 A：stream-json 解析）
- [ ] 实现 `engine_agent_sdk.py`（引擎 B：SDK 封装）
- [ ] 实现 `session_manager.py`（双引擎调度）
- [ ] 实现 `server.py`（REST API + WebSocket）
- [ ] 测试引擎 A：订阅模式，单次任务
- [ ] 测试引擎 B：API Key，多轮对话
- [ ] 测试引擎 A：`--resume` 多轮对话

### Phase 2：稳定性和安全（预计 1-2 天）

- [ ] Token 认证
- [ ] 错误处理和重试
- [ ] 会话超时清理
- [ ] WebSocket 心跳
- [ ] 操作日志
- [ ] 引擎 B：Hook 拦截危险命令

### Phase 3：生产部署（预计 1 天）

- [ ] Nginx + SSL
- [ ] 服务器部署
- [ ] 手机端测试
- [ ] 两种认证模式切换验证

### Phase 4：进阶功能（按需）

- [ ] Plan Mode 支持（引擎 A 的 `--plan` 参数）
- [ ] 自定义 MCP 工具注册（引擎 B）
- [ ] 费用监控（API Key 模式）
- [ ] session resume（跨服务器重启恢复会话）
- [ ] 多项目 Git worktree 管理（参考胡渊鸣方案，为将来的并行派发做准备）

---

## 12. 测试验证方法

### 12.1 验证引擎 A（Direct CLI + 订阅）

```bash
# 确保设置了订阅 Token
export CLAUDE_CODE_OAUTH_TOKEN="sk-ant-xxx-..."

# 创建订阅模式会话
curl -X POST http://localhost:8000/api/sessions \
  -H "Authorization: Bearer your-token" \
  -H "Content-Type: application/json" \
  -d '{"project_path": "/tmp/test", "auth_mode": "subscription"}'
# 应返回 engine: "direct_cli", auth_mode: "subscription"

# 发送消息
curl -X POST http://localhost:8000/api/sessions/SESSION_ID/send \
  -H "Authorization: Bearer your-token" \
  -H "Content-Type: application/json" \
  -d '{"content": "列出当前目录的文件"}'
```

### 12.2 验证引擎 B（Agent SDK + API Key）

```bash
# 确保设置了 API Key
export ANTHROPIC_API_KEY="sk-ant-api03-..."

# 创建 API Key 模式会话
curl -X POST http://localhost:8000/api/sessions \
  -H "Authorization: Bearer your-token" \
  -H "Content-Type: application/json" \
  -d '{"project_path": "/tmp/test", "auth_mode": "api_key"}'
# 应返回 engine: "agent_sdk", auth_mode: "api_key"
```

### 12.3 验证多轮对话（引擎 A 的 --resume）

```bash
# 第一轮
wscat -c ws://localhost:8000/ws/SESSION_ID
> {"type": "auth", "token": "your-token"}
> {"type": "message", "content": "法国的首都是哪里？"}
# 等待完成

# 第二轮（Claude 应该记得上一轮内容）
> {"type": "message", "content": "那里的人口是多少？"}
# Claude 应该知道是在问巴黎的人口
```

### 12.4 验证认证隔离

```bash
# 同时设置两个认证（不应该这样做，但要测试保护机制）
export ANTHROPIC_API_KEY="sk-ant-api03-..."
export CLAUDE_CODE_OAUTH_TOKEN="sk-ant-xxx-..."

# 创建 subscription 会话 — 应该只用 OAuth Token
curl -X POST http://localhost:8000/api/sessions \
  -d '{"auth_mode": "subscription"}'
# 引擎 A 会在环境变量中删除 ANTHROPIC_API_KEY

# 创建 api_key 会话 — 应该只用 API Key
curl -X POST http://localhost:8000/api/sessions \
  -d '{"auth_mode": "api_key"}'
# 引擎 B 会在环境变量中删除 CLAUDE_CODE_OAUTH_TOKEN
```

---

## 13. 总结

### v2 的核心变更

1. **双引擎架构**：引擎 A（Direct CLI）支持订阅，引擎 B（Agent SDK）支持高级功能
2. **合规的订阅方案**：通过直接调 CLI 而非 SDK，绕过 Anthropic 的政策限制
3. **对客户端透明**：无论底层用哪个引擎，WebSocket 和 REST API 的接口完全一致
4. **参考业界实践**：引擎 A 的设计参考了胡渊鸣（Meshy AI CEO）的 10 个 Claude Code 并行方案

### 一句话总结

**用 Claude Code 自己的 CLI 做订阅认证，用 Agent SDK 做高级功能，两者共存互补。**
