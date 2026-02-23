# Claude Artifacts + 计算机沙盒：架构解析、原理剖析与开源复刻指南

> 本文深入解析 Claude.ai 中 Artifacts、计算机沙盒（Computer Use Sandbox）、任务分步执行、思考过程可视化等独特功能的底层实现原理，并提供开源替代方案和复刻路线图。

---

## 一、你观察到的能力全景

在 Claude.ai 网页端，你可以看到以下几个 ChatGPT / Gemini 目前没有（或部分实现）的能力：

| 能力 | 具体表现 |
|------|----------|
| **Artifacts** | 在对话旁边生成可交互的 React 组件、HTML 页面、SVG、Mermaid 图、Markdown 文档等，实时预览 |
| **计算机沙盒** | 拥有一台完整的 Linux (Ubuntu 24) 虚拟机，可以执行 bash 命令、安装 npm/pip 包、创建/编辑文件 |
| **任务分步执行** | 自动将复杂任务拆解为多步，逐步调用不同工具（bash、文件创建、字符串替换、Web 搜索等） |
| **思考过程可视化** | Extended Thinking —— 显示模型的推理链（chain of thought） |
| **文档导出** | 生成 .docx / .pptx / .xlsx / .pdf / .md 等格式文件并提供下载链接 |
| **技能系统 (Skills)** | 内置专业领域的"最佳实践提示词"，在创建文档前自动读取相关 Skill.md |

---

## 二、核心架构：不是"魔法"，是 Tool Use + Sandbox 的工程化组合

### 2.1 整体架构图

```
┌────────────────────────────────────────────────────────┐
│                   Claude.ai 前端 (React)                │
│  ┌─────────────┐  ┌──────────────┐  ┌──────────────┐  │
│  │ 对话面板     │  │ Artifact 预览 │  │ 文件下载面板  │  │
│  └──────┬──────┘  └──────┬───────┘  └──────┬───────┘  │
│         │                │                  │           │
└─────────┼────────────────┼──────────────────┼───────────┘
          │                │                  │
          ▼                ▼                  ▼
┌────────────────────────────────────────────────────────┐
│              Anthropic 后端 API 服务                     │
│                                                         │
│  ┌──────────────────────────────────────────────┐      │
│  │        Claude 大模型 (Opus / Sonnet)          │      │
│  │  ┌──────────┐  ┌─────────┐  ┌────────────┐  │      │
│  │  │ 文本生成  │  │Tool Call│  │Extended     │  │      │
│  │  │          │  │ 决策引擎 │  │Thinking    │  │      │
│  │  └──────────┘  └────┬────┘  └────────────┘  │      │
│  └──────────────────────┼───────────────────────┘      │
│                         │                               │
│         ┌───────────────┼───────────────┐              │
│         ▼               ▼               ▼              │
│  ┌────────────┐  ┌────────────┐  ┌────────────┐       │
│  │ bash_tool  │  │ file_create│  │ web_search │       │
│  │ (执行命令)  │  │ (创建文件)  │  │ (网页搜索)  │       │
│  └─────┬──────┘  └─────┬──────┘  └────────────┘       │
│        │               │                               │
│        ▼               ▼                               │
│  ┌─────────────────────────────────────┐               │
│  │    Linux 沙盒容器 (Ubuntu 24)        │               │
│  │  /home/claude      ← 工作目录       │               │
│  │  /mnt/user-data/uploads ← 用户上传  │               │
│  │  /mnt/user-data/outputs ← 最终输出  │               │
│  │  /mnt/skills/       ← 技能文档      │               │
│  │                                     │               │
│  │  可安装: npm, pip, apt 包            │               │
│  │  网络: 仅白名单域名可访问            │               │
│  │  文件系统: 会话间重置                │               │
│  └─────────────────────────────────────┘               │
└────────────────────────────────────────────────────────┘
```

### 2.2 核心原理：Tool Use（函数调用）

**这是一切的基石。** Claude 本身并不"执行"代码——它通过 Anthropic Messages API 的 Tool Use 机制，生成结构化的工具调用请求，由后端系统实际执行。

工作流程如下：

1. **用户发送消息** → API 将消息连同可用工具定义一起发给模型
2. **模型分析需求** → 决定需要调用哪些工具，生成 `tool_use` 内容块（包含工具名和参数）
3. **后端拦截并执行** → 系统解析 `tool_use` 块，在沙盒环境中执行对应操作
4. **结果回传** → 执行结果作为 `tool_result` 发回模型
5. **模型生成最终回复** → 基于工具返回的数据，生成自然语言回复

这与 ChatGPT 的 Function Calling 和 Gemini 的 Tool Use 在概念上是一样的，但 Anthropic 在**工具种类的丰富程度**和**沙盒环境的完整性**上做得更深入。

### 2.3 Claude.ai 注册的工具清单

根据系统运行时的配置，Claude.ai 中的模型可以调用以下工具：

| 工具名 | 功能 | 对应你看到的体验 |
|--------|------|------------------|
| `bash_tool` | 在 Linux 容器中执行 bash 命令 | "安装工具""运行代码" |
| `file_create` | 创建新文件 | 生成 .md / .html / .jsx 文件 |
| `str_replace` | 精确替换文件中的字符串 | 编辑现有文件 |
| `view` | 查看文件/目录/图片 | 读取上传文件、查看技能文档 |
| `present_files` | 将文件呈现给用户下载 | "导出文档"功能 |
| `web_search` | 搜索网页 | 实时搜索最新信息 |
| `web_fetch` | 获取指定 URL 内容 | 读取网页全文 |
| `image_search` | 搜索图片 | 返回相关图片 |
| `event_create_v1` | 创建日历事件 | 日程管理 |
| `alarm_create_v0` | 设置闹钟 | 提醒功能 |
| `places_search` | 搜索地点/商家 | 位置推荐 |
| `chart_display_v0` | 内联显示图表 | 数据可视化 |
| `message_compose_v1` | 撰写邮件/消息 | 消息草稿 |
| `ask_user_input_v0` | 向用户提问（选择题） | 交互式选项 |
| `memory_user_edits` | 管理用户记忆 | 记住偏好 |
| `conversation_search` | 搜索历史对话 | 引用之前聊天 |
| `recent_chats` | 检索最近对话 | 回顾历史 |

**关键洞察**：模型"看到"的是一段很长的系统提示词（System Prompt），里面定义了所有可用工具的 JSON Schema、使用规则和最佳实践。模型并不是在"思考要怎么分步骤做"——它是在根据提示词中的工具描述，决定调用哪个工具。

---

## 三、Artifacts 的实现原理

### 3.1 什么是 Artifact？

Artifact 不是一个独立的系统，而是一种**前端渲染约定 + 文件创建**的组合：

1. 模型通过 `file_create` 工具创建一个特定格式的文件（.html / .jsx / .md / .svg / .mermaid）
2. 前端识别文件类型，在对话旁边的独立面板中渲染
3. React (.jsx) 文件在浏览器内沙盒中运行，支持 Tailwind CSS、Recharts、D3、Three.js 等库

### 3.2 Artifact 的技术限制

- **不能使用 localStorage / sessionStorage**（浏览器存储 API 不可用）
- **可以使用 `window.storage`**（Anthropic 提供的持久化 KV 存储 API）
- React 组件必须**无必填 props** 且使用 **default export**
- 只能使用 Tailwind 的核心工具类（没有编译器）
- 可导入的库是预定义白名单（lucide-react、recharts、d3、Three.js、shadcn/ui 等）

### 3.3 Artifact 内嵌 API 调用

Artifact 中的 React/HTML 代码可以直接调用 Anthropic API（不需要 API Key，由平台自动注入鉴权）：

```javascript
const response = await fetch("https://api.anthropic.com/v1/messages", {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({
    model: "claude-sonnet-4-20250514",
    max_tokens: 1000,
    messages: [{ role: "user", content: "..." }],
    // 甚至可以接入 MCP 服务器！
    mcp_servers: [{ type: "url", url: "https://mcp.notion.com/mcp", name: "notion" }]
  })
});
```

这意味着 Artifact 可以构建"AI 驱动的 AI 应用"——在网页组件内部再次调用 Claude。

---

## 四、计算机沙盒的实现原理

### 4.1 沙盒环境规格

| 属性 | 配置 |
|------|------|
| 操作系统 | Ubuntu 24 LTS |
| 工作目录 | `/home/claude` |
| 用户上传 | `/mnt/user-data/uploads`（只读） |
| 输出目录 | `/mnt/user-data/outputs`（用户可见） |
| 生命周期 | 会话间重置（每次新对话是全新环境） |
| 包管理 | npm, pip（需 `--break-system-packages`）, apt |
| 网络 | 仅白名单域名（pypi.org, npmjs.org, github.com 等） |
| 预装工具 | Node.js, Python, pandoc, LibreOffice, pdftoppm 等 |

### 4.2 沙盒的底层技术

Anthropic 在 2025 年开源了沙盒运行时的核心组件：

- **GitHub 仓库**: [`anthropic-experimental/sandbox-runtime`](https://github.com/anthropic-experimental/sandbox-runtime)
- **macOS**: 使用 Apple 的 **Seatbelt**（sandbox-exec）框架，内核级隔离
- **Linux**: 使用 **bubblewrap** (bwrap) + **seccomp BPF** 过滤器
  - bubblewrap 创建隔离的 Linux namespace 和 bind mount
  - seccomp BPF 在系统调用级别拦截 AF_UNIX socket 创建
  - 预编译的 BPF 过滤器支持 x64 和 arm64（约 104 字节）

### 4.3 网络隔离

所有网络流量通过**代理服务器**（运行在沙盒外部）：

- 域名白名单：只允许预批准的域名
- 新域名请求：触发权限提示
- Unix socket 控制：可阻止本地进程间通信
- 代理返回 `x-deny-reason` 头部说明拒绝原因

### 4.4 安全设计哲学

Anthropic 的沙盒采用**双层安全模型**：

1. **声明式规则**（settings.json 中的 permission deny rules）
2. **OS 级强制执行**（内核级文件系统和网络隔离）

没有沙盒时，bash 命令可以绕过权限规则；有了沙盒，限制在内核级强制执行，适用于所有子进程。

---

## 五、任务分步执行与思考过程可视化

### 5.1 分步执行的原理

Claude 的"分步执行"并不是一个特殊的架构特性，而是 **Tool Use 的 Agentic Loop（代理循环）** 的自然结果：

```
用户消息 → 模型推理 → tool_use(bash) → 执行 → tool_result 
                     → 模型推理 → tool_use(file_create) → 执行 → tool_result
                     → 模型推理 → tool_use(present_files) → 执行 → 最终回复
```

每次 `tool_use` → `tool_result` 构成一个"步骤"。前端将每个步骤渲染为可折叠的面板，显示：
- 工具名称和参数
- 执行状态（进行中/完成/失败）
- 输出结果

### 5.2 Extended Thinking（思考过程可视化）

这是模型层面的能力，不是工程 hack：

- Anthropic 在训练 Claude 时加入了 **chain-of-thought（思维链）** 的显式输出
- API 中通过 `thinking` 参数启用
- 模型在生成最终回复之前，先输出一段"思考过程"文本块
- 前端将这段文本渲染在可折叠的"Thinking"面板中

这是 Claude 相比 ChatGPT 的一个差异化特性（ChatGPT 的 o1/o3 也有类似的"reasoning"，但展示方式不同）。

### 5.3 Skills 系统

Skills 是一套**提示词注入架构**：

1. `/mnt/skills/` 目录下存放各类 `SKILL.md` 文件
2. 每个 SKILL.md 包含该领域（如 docx、pptx、pdf 创建）的最佳实践和代码模板
3. 模型在执行任务前，先用 `view` 工具读取相关 SKILL.md
4. 读取到的内容成为上下文的一部分，指导后续代码生成

这本质上是一种**元工具（meta-tool）**设计——不是直接执行操作，而是注入专业知识来改善执行质量。

---

## 六、Claude Code 及其与 Claude.ai 的关系

### 6.1 Claude Code 是什么？

Claude Code 是 Anthropic 的**命令行 AI 编程工具**，运行在你的终端里，可以：
- 理解整个代码库
- 读取/编辑/创建文件
- 运行 bash 命令
- 管理 Git 工作流
- 使用 MCP 协议连接外部工具

### 6.2 开源状态

**Claude Code 的核心代码并未开源。** GitHub 仓库 ([anthropics/claude-code](https://github.com/anthropics/claude-code)) 包含的是：
- README 和文档
- 插件系统（plugins 目录）
- 配置示例
- CHANGELOG

代码本体是闭源的，通过 `brew install` / `npm install` 分发编译后的二进制/包。License 是 Anthropic 的商业服务条款，不是 MIT/Apache。

### 6.3 开源的沙盒运行时

Anthropic 开源的是**沙盒运行时**部分：
- **仓库**: [`anthropic-experimental/sandbox-runtime`](https://github.com/anthropic-experimental/sandbox-runtime)
- 这是 Claude Code 内部使用的 OS 级隔离组件
- 可以独立使用，为你自己的 AI agent 提供沙盒

### 6.4 Claude.ai 沙盒 vs Claude Code 的相似性

| 维度 | Claude.ai 计算机沙盒 | Claude Code |
|------|---------------------|-------------|
| 运行环境 | 云端 Linux 容器 | 用户本地终端 |
| 文件访问 | 受限的虚拟文件系统 | 用户项目目录（有权限控制） |
| 网络 | 白名单域名 | 代理+域名白名单 |
| 工具 | bash, file_create, view, str_replace | bash, Read, Edit, Write, WebFetch 等 |
| 生命周期 | 会话间重置 | 持久（操作用户本地文件） |
| 沙盒技术 | 服务端容器化 | OS 级沙盒（Seatbelt/bubblewrap） |
| 底层模型交互 | 相同的 Tool Use API | 相同的 Tool Use API |

**本质相同**：两者都是通过 Tool Use 让模型调用工具，区别在于执行环境的位置和权限范围。

---

## 七、开源替代方案

### 7.1 完整 Artifacts 替代

| 项目 | 描述 | GitHub |
|------|------|--------|
| **E2B Fragments** | Claude Artifacts 的开源克隆，基于 E2B Sandbox SDK + Next.js 14 + Vercel AI SDK | [e2b-dev/fragments](https://github.com/e2b-dev/fragments) |
| **LibreChat** | 多模型聊天界面，支持 Artifacts（React/HTML/Mermaid）、Code Interpreter、MCP | [danny-avila/LibreChat](https://github.com/danny-avila/LibreChat) |
| **Open WebUI** | 自托管 AI 界面，支持本地模型，有代码执行能力 | [open-webui/open-webui](https://github.com/open-webui/open-webui) |

### 7.2 沙盒/代码执行

| 项目 | 描述 | 特点 |
|------|------|------|
| **E2B SDK** | 云端 Firecracker 微虚拟机，专为 AI 代码执行设计 | 100% 开源基础设施，Python/JS SDK，秒级启动 |
| **sandbox-runtime** | Anthropic 开源的 OS 级沙盒 | 文件系统+网络隔离，macOS Seatbelt + Linux bubblewrap |
| **Docker** | 容器化隔离 | 最成熟的方案，中高等隔离 |
| **Daytona** | 开发者沙盒环境 | 快速冷启动，镜像级沙盒 |
| **Northflank** | 企业级微虚拟机平台 | 支持 BYOC，长期存活的沙盒 |

### 7.3 Agentic 编程工具（Claude Code 替代）

| 项目 | 类型 | 开源 | 特点 |
|------|------|------|------|
| **Cline** | VS Code 扩展 | ✅ Apache 2.0 | 最接近 Claude Code 的开源替代，Plan Mode + MCP + 任意模型 |
| **OpenCode (原 Aider)** | 终端工具 | ✅ | 100K+ Stars，Git-aware，支持 100+ 语言 |
| **OpenHands (原 OpenDevin)** | 自主编程 Agent | ✅ | 项目级编排，自主执行端到端任务 |
| **Open Interpreter** | 终端工具 | ✅ | 本地运行 LLM，代码+Shell 自动化 |
| **Continue** | VS Code/JetBrains | ✅ Apache 2.0 | 构建自定义 AI 编程助手的框架 |
| **Plandex** | 终端工具 | ✅ MIT | 2M token 上下文窗口，diff review sandbox |
| **bolt.new** | Web 平台 | ✅ | 浏览器内全栈开发，一键部署 |
| **CodingIT** | Web 平台 | ✅ | v0.dev / Cursor / bolt.new 的开源替代 |

---

## 八、如何复刻 Claude.ai 的完整体验？

### 8.1 架构蓝图

如果你想复刻 Claude.ai 的 Artifacts + 计算机沙盒体验，核心架构是：

```
┌──────────────────────────────────────────────┐
│          你的前端 (Next.js / React)           │
│  ┌──────────┐  ┌──────────┐  ┌────────────┐ │
│  │ 聊天界面  │  │ 代码预览  │  │ 文件下载   │ │
│  └─────┬────┘  └─────┬────┘  └─────┬──────┘ │
└────────┼─────────────┼─────────────┼─────────┘
         │             │             │
         ▼             ▼             ▼
┌──────────────────────────────────────────────┐
│           你的后端 (Node.js / Python)         │
│                                              │
│  1. 接收用户消息                              │
│  2. 构造 System Prompt（含工具定义）           │
│  3. 调用 LLM API（Claude/GPT/本地模型）       │
│  4. 解析 tool_use 响应                        │
│  5. 在沙盒中执行工具                          │
│  6. 将 tool_result 回传模型                   │
│  7. 循环直到模型停止调用工具                    │
│  8. 返回最终回复给前端                         │
│                                              │
│  ┌────────────────────────────┐              │
│  │   沙盒环境                  │              │
│  │   (Docker / E2B / bwrap)   │              │
│  │   - bash 执行              │              │
│  │   - 文件读写               │              │
│  │   - 网络白名单             │              │
│  └────────────────────────────┘              │
└──────────────────────────────────────────────┘
```

### 8.2 具体实施步骤

#### 步骤 1：选择 LLM + Tool Use 方案

```python
# 使用 Anthropic API 的 Tool Use
import anthropic

client = anthropic.Anthropic()

tools = [
    {
        "name": "execute_bash",
        "description": "在沙盒中执行 bash 命令",
        "input_schema": {
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "要执行的命令"}
            },
            "required": ["command"]
        }
    },
    {
        "name": "create_file",
        "description": "创建文件",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "content": {"type": "string"}
            },
            "required": ["path", "content"]
        }
    }
]

# Agentic Loop
messages = [{"role": "user", "content": user_input}]

while True:
    response = client.messages.create(
        model="claude-sonnet-4-5-20250929",
        max_tokens=4096,
        tools=tools,
        messages=messages
    )
    
    if response.stop_reason == "tool_use":
        # 解析工具调用，在沙盒中执行
        for block in response.content:
            if block.type == "tool_use":
                result = execute_in_sandbox(block.name, block.input)
                messages.append({"role": "assistant", "content": response.content})
                messages.append({
                    "role": "user",
                    "content": [{
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": result
                    }]
                })
    else:
        break  # 模型停止调用工具，返回最终回复
```

#### 步骤 2：搭建沙盒环境

**方案 A：Docker（推荐入门）**

```dockerfile
FROM python:3.12-slim
RUN apt-get update && apt-get install -y nodejs npm git curl
RUN pip install numpy pandas matplotlib
WORKDIR /workspace
```

```python
import docker

client = docker.from_env()

def execute_in_sandbox(command):
    container = client.containers.run(
        "your-sandbox-image",
        command=f"bash -c '{command}'",
        detach=False,
        remove=True,
        network_mode="none",  # 网络隔离
        mem_limit="512m",
        cpu_quota=50000
    )
    return container.decode("utf-8")
```

**方案 B：E2B SDK（推荐生产环境）**

```python
from e2b_code_interpreter import Sandbox

with Sandbox() as sandbox:
    execution = sandbox.run_code("print('Hello from sandbox!')")
    print(execution.logs.stdout)
```

**方案 C：Anthropic sandbox-runtime（最接近 Claude Code 的方案）**

```bash
npm install @anthropic-ai/sandbox-runtime
# 使用 srt 命令包装进程
srt --allow-net="pypi.org,github.com" -- python my_script.py
```

#### 步骤 3：实现 Artifacts 前端渲染

```jsx
// 前端 Artifact 渲染器 (简化版)
function ArtifactRenderer({ file }) {
  const ext = file.name.split('.').pop();
  
  switch (ext) {
    case 'html':
      return <iframe srcDoc={file.content} sandbox="allow-scripts" />;
    case 'jsx':
      return <ReactSandbox code={file.content} />;
    case 'md':
      return <MarkdownRenderer content={file.content} />;
    case 'svg':
      return <div dangerouslySetInnerHTML={{ __html: file.content }} />;
    case 'mermaid':
      return <MermaidRenderer chart={file.content} />;
    default:
      return <CodeBlock code={file.content} language={ext} />;
  }
}
```

#### 步骤 4：实现 Skills 系统

```python
# 简单的 Skills 系统
SKILLS = {
    "docx": "/skills/docx/SKILL.md",
    "pptx": "/skills/pptx/SKILL.md",
    "pdf": "/skills/pdf/SKILL.md",
}

def get_skill_context(task_description):
    """根据任务描述，注入相关 Skill 内容到 System Prompt"""
    relevant_skills = []
    for keyword, path in SKILLS.items():
        if keyword in task_description.lower():
            with open(path) as f:
                relevant_skills.append(f.read())
    return "\n\n".join(relevant_skills)
```

### 8.3 推荐技术栈组合

| 层级 | 推荐方案 | 替代方案 |
|------|----------|----------|
| **前端** | Next.js 14 + shadcn/ui + TailwindCSS | Vite + React |
| **LLM** | Claude API (Tool Use) | OpenAI API / 本地 Ollama + Qwen |
| **AI SDK** | Vercel AI SDK | LangChain / LlamaIndex |
| **沙盒** | E2B SDK (生产) / Docker (开发) | sandbox-runtime / Firecracker |
| **Artifacts** | iframe sandboxed + React 动态渲染 | 参考 E2B Fragments |
| **文件生成** | docx-js, pptxgenjs, jsPDF | LibreOffice headless |
| **部署** | Vercel + E2B Cloud | 自托管 Docker Compose |

### 8.4 最快上手路径

如果你只想尽快体验和复刻，最快的路径是：

1. **克隆 E2B Fragments** → `git clone https://github.com/e2b-dev/fragments`
2. **配置 API Keys** → Anthropic API Key + E2B API Key
3. **运行** → `npm install && npm run dev`
4. 你就拥有了一个类似 Claude Artifacts 的应用

如果你想要更完整的体验（包括多模型、历史记录、文件管理），使用 **LibreChat**：

```bash
git clone https://github.com/danny-avila/LibreChat
cd LibreChat
cp .env.example .env  # 配置 API keys
docker compose up -d
```

---

## 九、总结

### 9.1 "魔法"背后的真相

Claude.ai 的这些炫酷功能，**核心并没有对大模型本身做什么特殊改造**。它的"秘密"是：

1. **精心设计的 System Prompt** → 数千字的工具定义、使用规则、最佳实践
2. **丰富的 Tool 注册** → 20+ 种工具覆盖 bash、文件、搜索、日历、地图等
3. **完整的沙盒环境** → 一台受控的 Linux 虚拟机，支持安装包和执行代码
4. **优秀的前端工程** → Artifact 渲染、分步展示、思考过程折叠
5. **Skills 知识库** → 领域专业的提示词模板，提升输出质量

### 9.2 为什么 ChatGPT / Gemini 没有完全做到？

- ChatGPT 有 Code Interpreter，但沙盒受限（无法 npm install、无法持久化文件）
- ChatGPT 没有 Artifacts 的实时预览/交互能力（GPT Canvas 是类似的尝试）
- Gemini 有代码执行，但工具链完整度和前端体验不如 Claude.ai
- **这更多是产品设计和工程投入的差异，而非模型能力的本质差异**

### 9.3 关键开源资源汇总

| 资源 | 链接 |
|------|------|
| Anthropic sandbox-runtime (开源) | https://github.com/anthropic-experimental/sandbox-runtime |
| E2B Fragments (Artifacts 克隆) | https://github.com/e2b-dev/fragments |
| E2B Code Interpreter SDK | https://github.com/e2b-dev/code-interpreter |
| LibreChat (多功能 AI 界面) | https://github.com/danny-avila/LibreChat |
| Cline (VS Code Agent) | https://github.com/cline/cline |
| OpenCode (终端 Agent, 100K+ Stars) | https://github.com/sst/opencode |
| OpenHands (自主 Agent) | https://github.com/All-Hands-AI/OpenHands |
| Open Interpreter | https://github.com/OpenInterpreter/open-interpreter |
| Claude Code (闭源，含插件) | https://github.com/anthropics/claude-code |
| bolt.new (浏览器全栈开发) | https://github.com/stackblitz/bolt.new |

---

*文档创建时间: 2026-02-20 | 基于 Claude.ai 运行时配置和公开技术文档整理*
