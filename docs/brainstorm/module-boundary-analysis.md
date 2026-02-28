# 模块边界分析：哪些模块可以直接复用？

> 日期：2026-02-25
> 核心问题：哪些模块有清晰边界，可以直接调用开源库（pip install + 调 API）？哪些耦合度高必须自研？
> 策略：确定独立性 → 划清边界 → 直接调用，不做改造
> 前置阅读：[reuse-strategy.md](reuse-strategy.md)（复用策略分类与模块耦合分析）、[architect-insights.md](architect-insights.md)（架构师综合洞察）

---

## 背景

### 项目是什么

AI 自进化系统是一个基于 Telegram 的 AI Agent，核心特点是具备**自进化能力**——通过 Observer（观察）→ Signal（信号）→ Architect（提案）→ Council（审议）→ Rollback（回滚）闭环，Agent 能观察自身表现、发现改进机会、自主生成和执行改进方案。

系统当前约 3000 行 Python 核心代码，已有完整的进化闭环实现，但基础设施能力（工具调用、记忆搜索、多 LLM Provider）仍处于 MVP 阶段。

### 我们在讨论什么

我们调研了 6 个开源 AI Agent 项目（OpenClaw、Nanobot、Bub、Pi、Letta/MemGPT、Mem0），发现：

- **基础设施层**（Agent Loop、Tool Use、Telegram 集成、记忆管理、LLM 调用）在开源世界已是成熟的已解决问题
- **自进化闭环**是我们独有的核心差异化，没有任何开源项目有类似设计
- 把 80% 精力花在基础设施上是战略浪费，应该聚焦核心差异化

由此产生一个关键问题：**哪些模块可以直接拿来用，哪些必须自己写？**

### 五种复用策略（详见 [reuse-strategy.md](reuse-strategy.md)）

| 策略 | 简称 | 做法 | 适用场景 |
|------|------|------|---------|
| **策略 A** | 参考自研 | 学习设计思路，但代码从零写 | 核心差异化模块、对安全/可控性要求高 |
| **策略 B** | Fork 修改 | Fork 开源项目，保留基础设施，替换核心逻辑 | 架构高度匹配（>70%）、需要快速出原型 |
| **策略 C** | 库集成 | `pip install` 作为依赖，通过公开 API 调用 | 成熟稳定的通用库、无需修改其核心逻辑 |
| **策略 D** | 混合提取 | 从多个项目中提取特定设计模式或代码片段 | 需要特定功能但不需要整个框架 |
| **策略 E** | 协议复用 | 复用通信协议/接口标准（如 OpenAI Function Calling） | 需要对接外部生态 |

### 本文的核心策略

本文聚焦于**策略 C（库集成）的可行性边界**：对系统中的每个模块，判断它是否有足够清晰的接口边界，可以直接用外部库替换（`pip install` + 写一个薄 adapter），而不需要对现有代码做大规模改造。

判断标准：
1. **模块独立性**：如果模块相对独立，就划清边界
2. **直接调用**：有成熟外部库的，直接调用已有代码，不做改造
3. **耦合度**：识别哪些模块耦合度太高，不适合外部化

---

## 一、分类标准

| Tier | 定义 | 策略 | 改造工作量 |
|------|------|------|-----------|
| **Tier 1** | 有成熟库、接口清晰、可直接 `pip install` | 策略 C（库集成） | 写 Adapter ≤50 行 |
| **Tier 2** | 设计模式可借鉴、但无可直接调用的库 | 策略 D（概念提取，代码自写） | 参考实现，自研 100-300 行 |
| **Tier 3** | 高耦合或核心差异化，必须自研 | 策略 A（自研） | 完全自主 |

---

## 二、Tier 1 — 可直接调用外部库的模块

### 2.1 记忆管理（部分）→ Mem0

**当前实现**：`core/memory.py` — `MemoryStore` 类，455 行，基于文件系统 + bigram 关键词搜索。

**耦合分析**：

```
MemoryStore 被引用的地方（仅 2 处）：
  core/agent_loop.py:58  → self.memory = MemoryStore(self.workspace)
  core/agent_loop.py:145 → self.memory.get_relevant_memories(query)
  core/agent_loop.py:148 → self.memory.get_user_preferences()

间接使用（通过 ReflectionEngine）：
  extensions/memory/reflection.py → 调用 memory.append_error_pattern()
  extensions/memory/reflection.py → 调用 memory.append_preference()
```

**耦合度：低。** 只有 AgentLoop 直接依赖，且只调用 3 个方法。

**Mem0 的 API**：

```python
from mem0 import Memory

m = Memory(config={
    "vector_store": {"provider": "qdrant", "config": {"collection_name": "evo_agent"}},
    "llm": {"provider": "openai", "config": {"model": "gpt-4o-mini"}},
    "embedder": {"provider": "openai", "config": {"model": "text-embedding-3-small"}},
})

# 写入 — 自动提取事实、去重、合并
m.add(messages=[{"role": "user", "content": "我喜欢简洁的回复"}], user_id="michael")

# 搜索 — 向量语义搜索
results = m.search("用户偏好", user_id="michael", limit=5)
# → [{"id": "xxx", "memory": "喜欢简洁的回复", "score": 0.92}]

# 全量 — 列出所有记忆
all_memories = m.get_all(user_id="michael")

# 更新/删除 — 直接操作
m.update(memory_id, data="更新后的记忆")
m.delete(memory_id)

# 审计 — 完整变更历史
history = m.history(memory_id)
```

**关键发现 — 不能完全替换，但可以替换一半**：

我们的 MemoryStore 有两种职责：

| 职责 | 当前实现 | Mem0 能覆盖？ |
|------|---------|-------------|
| **文档存储** — profile.md, preferences.md, error_patterns.md | 文件读写 | **否** — Mem0 是 fact-based，不是 document-based |
| **事实管理** — 从对话中提取事实、去重、更新 | 无（append-only） | **是** — 这正是 Mem0 的核心能力 |
| **语义搜索** — 按语义查找相关记忆 | bigram 关键词匹配 | **是** — 向量搜索远优于 bigram |
| **审计追踪** — 记忆变更历史 | 无 | **是** — SQLite history 表 |

**推荐边界设计**：

```
MemoryStore（我们的代码）
├── DocumentLayer（保持自研）
│   ├── save/read profile.md, preferences.md, error_patterns.md
│   ├── save/read conversations/*.json
│   └── save/read daily_summaries/*.md
│
├── SmartMemoryLayer（委托给 Mem0）
│   ├── 事实提取：每次对话结束后 → mem0.add(messages)
│   ├── 事实去重：Mem0 自动 ADD/UPDATE/DELETE/NONE
│   ├── 语义搜索：mem0.search(query) 替代 bigram
│   └── 审计追踪：mem0.history()
│
└── 统一搜索 API
    ├── search(query) → 先查 Mem0 向量，再查文档关键词，合并排序
    └── get_relevant_memories(query) → 给 ContextEngine 用
```

**Adapter 代码量预估**：~40 行（一个 `Mem0Adapter` 类包装 `Memory` 实例）。

**依赖成本**：
- `pip install mem0ai` — 会带入 Qdrant client, OpenAI SDK, Pydantic
- 需要 embedding API 调用（每次 add/search 消耗少量 token）
- 本地模式可用 Qdrant in-memory（无需外部服务）

**分阶段引入**：
1. **Phase 1**：保持现有 DocumentLayer 不变，新增 `Mem0Adapter`，`search()` 方法优先查 Mem0
2. **Phase 2**：ReflectionEngine 产出的 error_pattern/preference 同步写入 Mem0
3. **Phase 3**：对话记录全量灌入 Mem0，替代 conversations/*.json 的 bigram 搜索

---

### 2.2 LLM 客户端 → LiteLLM

**当前实现**：`core/llm_client.py` — `LLMClient` 类，206 行，支持 Anthropic + OpenAI 兼容。

**耦合分析**：

```
BaseLLMClient 被引用的地方（18+ 处）：
  core/agent_loop.py       → self.llm.complete(system_prompt, user_message, model, max_tokens)
  core/architect.py        → self.llm_client.complete(...)
  core/council.py          → llm_client.complete(...)
  extensions/observer/     → self.llm_client.complete(...)
  extensions/memory/       → self.llm_client.complete(...)
  extensions/context/      → self.llm_client.complete(...)
```

**耦合度：极低。** 所有模块只调用一个方法：`complete(system_prompt, user_message, model, max_tokens) → str`。这是一个极简接口。

**LiteLLM 的 API**：

```python
import litellm

# 一行调用任何模型
response = await litellm.acompletion(
    model="anthropic/claude-opus-4-6",   # 统一 provider/model 格式
    messages=[
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_message},
    ],
    max_tokens=2000,
)
text = response.choices[0].message.content

# Tool Use 支持（未来需要）
response = await litellm.acompletion(
    model="anthropic/claude-opus-4-6",
    messages=messages,
    tools=tool_schemas,       # OpenAI function calling 格式
    tool_choice="auto",
)
# response.choices[0].message.tool_calls → [ToolCall(...)]
```

**Adapter 代码**：

```python
import litellm
from core.llm_client import BaseLLMClient

MODEL_MAP = {
    "opus": "anthropic/claude-opus-4-6",
    "qwen": "nvidia_nim/qwen/qwen3-235b-a22b",
}

class LiteLLMClient(BaseLLMClient):
    async def complete(self, system_prompt, user_message, model="opus", max_tokens=2000):
        try:
            model_id = MODEL_MAP.get(model, model)
            response = await litellm.acompletion(
                model=model_id,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_message},
                ],
                max_tokens=max_tokens,
            )
            return response.choices[0].message.content or ""
        except Exception as e:
            logger.error(f"LiteLLM call failed: {e}")
            return ""
```

**Adapter 代码量**：~20 行。完美实现 `BaseLLMClient` 接口。

**核心价值**：
- 100+ Provider 开箱即用（现在只有 2 个）
- **Tool Use 支持**：`tool_calls` 解析、`json_repair` 容错 — 这是我们未来必须做的
- Prompt Caching（Anthropic 特有）、模型故障转移、成本追踪
- 不改变任何现有代码 — 只需在 `main.py` 中把 `LLMClient()` 换成 `LiteLLMClient()`

**依赖成本**：`pip install litellm` — 纯 Python，依赖 httpx + tiktoken

**风险**：LiteLLM 是重依赖（1000+ 行核心代码），版本更新频繁。但社区活跃（12K+ stars），生产验证充分。

---

### 2.3 向量搜索 → sqlite-vec 或 ChromaDB

**当前实现**：无。`MemoryStore.search()` 用 bigram 关键词匹配。

**如果用 Mem0**：向量搜索已内置，无需单独集成。

**如果不用 Mem0，独立集成**：

| 库 | API | 依赖 | 适合场景 |
|---|---|---|---|
| **sqlite-vec** | `pip install sqlite-vec`，纯 SQLite 扩展 | 零外部依赖 | 最轻量，适合 MVP |
| **ChromaDB** | `pip install chromadb`，本地嵌入式 | 较重 | 功能完整，支持 metadata 过滤 |
| **Qdrant** (in-memory) | `pip install qdrant-client` | 中等 | Mem0 默认后端 |

**推荐**：如果走 Mem0 路线，向量搜索自动解决。如果不用 Mem0，`sqlite-vec` 最轻量。

---

## 三、Tier 2 — 概念可借鉴但需自己实现的模块

### 3.1 Tool Registry → 参考 Nanobot 的模式

**Nanobot 的设计**（可提取的模式）：

```python
# Nanobot 的 Tool 抽象
class Tool(ABC):
    name: str                    # 工具名
    description: str             # 给 LLM 的描述
    parameters: dict             # JSON Schema
    async execute(**kwargs) → str  # 执行

# Nanobot 的 ToolRegistry
class ToolRegistry:
    tools: dict[str, Tool]
    register(tool: Tool)         # 注册
    get_tools_schema() → list    # 生成 OpenAI function calling schema
    execute(name, params) → str  # 执行 + _HINT 错误引导
```

**为什么不能直接用（不是 Tier 1）**：
- Nanobot 的 `ToolRegistry` 没有发布为独立包
- 工具实现（filesystem.py, shell.py）与 Nanobot 的安全模型（`allowed_dir`, `deny_patterns`）紧耦合
- `_HINT` 错误引导机制与 Agent Loop 的重试逻辑配合

**推荐**：参考 Nanobot 的 `Tool` 抽象 + `ToolRegistry` 模式，用我们的代码风格重新实现。模式很简洁（Tool 基类 ~30 行，Registry ~50 行），不值得为此引入外部依赖。

### 3.2 记忆 Block 机制 → 参考 Letta

**Letta 的设计**（可提取的概念）：

```python
# Letta Block = 有字符上限的记忆单元
class Block:
    label: str              # "human", "persona", "error_patterns"
    value: str              # 内容
    limit: int              # 字符上限（如 2000）

    def update(self, new_value):
        if len(new_value) > self.limit:
            raise ValueError("Block exceeds limit")
        self.value = new_value
```

**为什么不是 Tier 1**：Letta 是 Server 架构（需要运行 `letta server`），没有独立的 Block 库可以 pip install。

**推荐**：在我们的 MemoryStore 中引入 Block 概念。~30 行代码，给 profile/preferences/error_patterns 各设一个字符上限，防止无限膨胀。

### 3.3 记忆决策（ADD/UPDATE/DELETE）→ 参考 Mem0 的 Prompt

**如果走 Mem0 路线**：这个自动获得，不需要自己实现。

**如果不用 Mem0**：可以提取 Mem0 的 `DEFAULT_UPDATE_MEMORY_PROMPT`，让我们的 LLM 做同样的决策。核心是一段 prompt engineering，不是代码问题。

### 3.4 Compaction 部分驱逐 → 参考 Letta Summarizer

**Letta 的策略**：保留最近 70% 消息不动，对最旧的 30% 做 LLM 摘要，摘要作为 `user` role 消息注入。

**当前实现**：`extensions/context/compaction.py` 已有 LLM 摘要能力。

**推荐**：将 Letta 的"部分驱逐"比例策略引入我们的 CompactionEngine。改动量 ~20 行。

---

## 四、Tier 3 — 必须自研的模块（高耦合或核心差异化）

### 4.1 Agent Loop（核心调度器）

```
依赖图：
AgentLoop
  ├── LLMClient (BaseLLMClient)
  ├── ContextEngine
  │   └── RulesInterpreter
  ├── MemoryStore
  ├── ReflectionEngine
  ├── SignalDetector
  ├── ObserverEngine
  ├── MetricsTracker
  └── CompactionEngine
```

**为什么不能外部化**：它是所有模块的粘合层。每次消息处理都要协调 8 个子系统。

### 4.2 Context Engine（上下文组装器）

```
依赖图：
ContextEngine
  ├── RulesInterpreter (读取宪法规则 + 经验规则)
  ├── TokenBudget (token 预算分配)
  └── 记忆注入 (来自 MemoryStore)
```

**为什么不能外部化**：Token 预算分配逻辑是我们独有的——不同于 Letta（按 Block 分配）或 Nanobot（无预算管理）。

### 4.3 进化模块群（核心差异化）

| 模块 | 独立性 | 原因 |
|------|--------|------|
| Observer Engine | 高 | 只依赖 LLMClient + 文件系统 |
| Signal Detector + Store | 高 | 只依赖文件系统 |
| Reflection Engine | 高 | 只依赖 LLMClient + 文件系统 |
| Architect Engine | 中 | 依赖 LLMClient + Council + Rollback + Telegram |
| Council | 高 | 只依赖 LLMClient |
| Rollback Manager | 高 | 只依赖文件系统 |
| Metrics Tracker | 高 | 只依赖文件系统 |

**注意**：虽然这些模块独立性高（大多数只依赖 LLMClient + 文件系统），但它们是**核心差异化能力**，必须自研。好消息是：高独立性意味着它们很容易移植到其他项目（如 Fork Nanobot 的双轨策略 Track B）。

---

## 五、完整模块分类总结

```
┌─────────────────────────────────────────────────────────────────┐
│  Tier 1 — 直接调用外部库（pip install + adapter）                   │
│                                                                 │
│  ┌───────────────┐  ┌───────────────┐  ┌──────────────────┐    │
│  │ LLM Client    │  │ 记忆·事实管理  │  │ 向量搜索          │    │
│  │ → LiteLLM     │  │ → Mem0        │  │ → (Mem0 自带)    │    │
│  │ adapter ~20行  │  │ adapter ~40行  │  │ 或 sqlite-vec   │    │
│  └───────────────┘  └───────────────┘  └──────────────────┘    │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│  Tier 2 — 借鉴模式，代码自写                                       │
│                                                                 │
│  ┌───────────────┐  ┌───────────────┐  ┌──────────────────┐    │
│  │ Tool Registry │  │ Block 记忆机制  │  │ Compaction 策略   │    │
│  │ 参考 Nanobot   │  │ 参考 Letta     │  │ 参考 Letta       │    │
│  │ ~80行自研      │  │ ~30行自研      │  │ ~20行改造        │    │
│  └───────────────┘  └───────────────┘  └──────────────────┘    │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│  Tier 3 — 必须自研（高耦合 或 核心差异化）                            │
│                                                                 │
│  高耦合：                                                        │
│  ┌───────────────┐  ┌───────────────┐                           │
│  │ Agent Loop    │  │ Context Engine│                           │
│  │ (粘合层)      │  │ (组装层)      │                           │
│  └───────────────┘  └───────────────┘                           │
│                                                                 │
│  核心差异化（高独立性，但必须自研）：                                   │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐          │
│  │Observer  │ │Signal    │ │Architect │ │Council   │          │
│  │Engine    │ │Detector  │ │Engine    │ │          │          │
│  └──────────┘ └──────────┘ └──────────┘ └──────────┘          │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐                       │
│  │Reflection│ │Rollback  │ │Metrics   │                       │
│  │Engine    │ │Manager   │ │Tracker   │                       │
│  └──────────┘ └──────────┘ └──────────┘                       │
│                                                                 │
│  保持现状不变（已完成且够用）：                                       │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐          │
│  │Config    │ │Bootstrap │ │Rules     │ │Channel   │          │
│  │          │ │          │ │Interpret.│ │System    │          │
│  └──────────┘ └──────────┘ └──────────┘ └──────────┘          │
└─────────────────────────────────────────────────────────────────┘
```

---

## 六、关键边界接口定义

为了让外部库可以无缝替换，需要明确的接口边界：

### 6.1 LLM 边界（已有）

```python
class BaseLLMClient(ABC):
    async def complete(self, system_prompt, user_message, model, max_tokens) -> str
```

当前接口已经足够干净。LiteLLM 直接实现此接口即可。
未来扩展 Tool Use 时，需要新增：

```python
    async def complete_with_tools(self, messages, tools, model, max_tokens) -> LLMResponse
```

### 6.2 记忆边界（需要定义）

```python
class BaseMemoryBackend(ABC):
    """语义记忆后端接口 — Mem0 或自研都实现此接口"""

    async def add_facts(self, messages: list[dict], user_id: str) -> list[str]:
        """从对话中提取事实并存储。返回新增/更新的 fact IDs。"""

    async def search(self, query: str, user_id: str, limit: int = 5) -> list[dict]:
        """语义搜索。返回 [{"id": ..., "content": ..., "score": ...}]"""

    async def get_all(self, user_id: str) -> list[dict]:
        """列出所有记忆。"""

    async def delete(self, memory_id: str) -> None:
        """删除一条记忆。"""
```

MemoryStore 变为组合模式：

```python
class MemoryStore:
    def __init__(self, workspace_path, backend: BaseMemoryBackend | None = None):
        self.documents = DocumentLayer(workspace_path)   # 文件读写（保持不变）
        self.backend = backend                            # Mem0 或 None

    def search(self, query, ...):
        # 如果有 backend → 先查 backend（语义），再查 documents（关键词）
        # 如果没有 → 退回到 bigram（向后兼容）
```

### 6.3 Tool 边界（待建）

```python
class BaseTool(ABC):
    name: str
    description: str
    parameters: dict              # JSON Schema
    async def execute(**kwargs) -> str

class ToolRegistry:
    def register(self, tool: BaseTool) -> None
    def get_schemas(self) -> list[dict]   # OpenAI function calling 格式
    async def execute(self, name: str, params: dict) -> str
```

---

## 七、实施优先级建议

| 优先级 | 模块 | 动作 | 工作量 | 价值 |
|--------|------|------|--------|------|
| **P0** | LLM Client | 集成 LiteLLM（为 Tool Use 铺路） | 1 天 | 高 — 解锁 Tool Use + 100+ Provider |
| **P1** | Memory 事实层 | 集成 Mem0（替代 bigram 搜索） | 2 天 | 高 — 智能去重 + 语义搜索 |
| **P2** | Tool Registry | 参考 Nanobot 自研 | 2 天 | 高 — Agent Loop 核心升级 |
| **P3** | Block 机制 | 参考 Letta 自研 | 0.5 天 | 中 — 防止记忆膨胀 |
| **P4** | Compaction 策略 | 参考 Letta 改进 | 0.5 天 | 中 — 压缩效率提升 |

---

## 八、与双轨策略的关系

这些边界定义对双轨策略（Track A 自研 + Track B Fork Nanobot）有直接价值：

- **Track A（当前项目）**：
  - 集成 LiteLLM → 替换 `LLMClient`
  - 集成 Mem0 → 增强 `MemoryStore`
  - 参考 Nanobot 自研 Tool Registry

- **Track B（Fork Nanobot）**：
  - Nanobot 已自带 LiteLLM → 不需要动
  - Nanobot 记忆系统（MEMORY.md + HISTORY.md）→ 替换为我们的 MemoryStore + Mem0 backend
  - Nanobot 已自带 ToolRegistry → 不需要动
  - 移植我们的进化模块（高独立性，容易移植）

**共享层**：`BaseMemoryBackend` 接口在两个 Track 间通用，Mem0 adapter 写一次两边用。

---

## 九、核心结论

1. **Tier 1 模块只有 2 个**：LLM Client（→ LiteLLM）和 Memory 事实管理（→ Mem0）。这两个模块边界最清晰、外部库最成熟、adapter 工作量最小。

2. **Mem0 不能完全替代 MemoryStore**，只能替代"事实管理 + 语义搜索"部分。我们的文档层（profile.md、preferences.md、conversations/）仍需自研代码管理。正确做法是组合模式：DocumentLayer（自研）+ Mem0 Backend（外部）。

3. **LiteLLM 是最值得优先集成的**。不仅解决了当前的多 Provider 支持问题，更关键的是为 Tool Use 铺路——LiteLLM 的 `tool_calls` 解析已经处理了各 Provider 的格式差异和容错。

4. **进化模块群虽然是 Tier 3（自研），但独立性极高**。这是好消息：Observer、Signal、Reflection、Council、Rollback、Metrics 都只依赖 `BaseLLMClient` + 文件系统，不依赖任何其他内部模块。意味着它们可以轻松移植。

5. **真正耦合度高的只有 2 个模块**：AgentLoop（粘合 8 个子系统）和 ContextEngine（融合 Rules + Memory + TokenBudget）。这两个无法外部化，也不应该外部化——它们是系统的"大脑"。
