# 调研任务：为 Telegram Bot 添加工具调用能力

> 供新 Agent 接手调研。
> 日期：2026-02-25

---

## 一、背景

AI自进化系统是一个通过 Telegram 与用户交互的自进化 AI Agent。

**当前架构（纯对话模式）：**
```
用户消息 → 规则解释器 → 记忆检索 → 上下文组装 → LLM 推理 → 纯文本回复
  → 异步后处理链：反思 → 信号检测 → Observer → 指标记录
```

**LLM 调用接口：**
```python
# core/llm_client.py
class BaseLLMClient(ABC):
    async def complete(self, system_prompt, user_message, model, max_tokens) -> str
```
- 只返回纯文本，没有 tool use 协议
- 支持两种后端：Anthropic SDK（Claude）和 OpenAI 兼容（Qwen 等）
- 通过 provider 注册表路由：`LLMClient(providers=config.providers, aliases=config.aliases)`

**触发此调研的问题：**
用户向 bot 发送"你帮我看一下 projects/AI自我进化系统/docs 下面有哪些文件"，bot 回复了假的 `<tool_call>` XML 和 bash 命令（幻觉），因为模型没有工具但试图扮演有工具的角色。

临时修复：在 `workspace/rules/constitution/identity.md` 添加了"能力边界"声明，禁止输出任何伪工具调用格式。

**用户诉求：** bot 应该能访问本机文件系统、执行操作，否则"很多事情做不了"。

---

## 二、需要调研的问题

### 1. Tool Use 协议选型

**Anthropic Claude 原生 tool use：**
- 当前已用 Anthropic SDK（`client.messages.create`），天然支持 `tools` 参数
- 参考：https://docs.anthropic.com/en/docs/build-with-claude/tool-use
- 需要评估：消息格式、多轮工具调用、streaming 兼容性

**OpenAI 兼容 function calling：**
- 当前也用 openai 兼容后端（qwen via NVIDIA），需要两种后端都能支持工具调用
- 需要评估：qwen 的 function calling 支持程度

**核心问题：** `BaseLLMClient.complete()` 接口如何改造？返回值从 `str` 变成什么？

### 2. 工具集设计

建议分级评估：

| 级别 | 工具 | 风险 |
|------|------|------|
| 只读 | `list_files(path)`, `read_file(path)`, `search_files(pattern)` | 低 |
| 读写 | `write_file(path, content)`, `edit_file(path, old, new)` | 中 |
| 执行 | `run_command(cmd)` | 高 |
| 系统 | `get_system_status()`, `manage_rules(action)` | 中 |

### 3. Agent Loop 改造方案

当前流程（`core/agent_loop.py` 的 `process_message()`）：
```
user_message → LLM.complete() → response(str) → 返回
```

需要改为：
```
user_message → LLM.complete_with_tools() → response
  ├─ 如果是 text → 返回
  └─ 如果是 tool_call → 执行工具 → 结果送回 LLM → 循环直到 text
```

需要评估：
- 最大循环次数限制
- 每次循环的 token 消耗
- 超时处理

### 4. 安全机制

- **目录沙箱**：限制可访问路径（如只能访问 workspace/ 和指定项目目录）
- **命令白名单/黑名单**：run_command 的安全边界
- **审批集成**：高风险操作走现有 approval 机制（`config.py` 已有 level 0-3）
- **Token 预算**：工具循环可能消耗大量 token，需要上限

### 5. 业界方案参考

- Claude Code 的工具调用机制
- OpenAI Agents SDK 的工具设计
- LangChain / LlamaIndex 的 tool 抽象
- 其他开源 Telegram AI bot 的工具实现

---

## 三、关键文件清单

| 文件 | 作用 | 与本任务的关系 |
|------|------|---------------|
| `core/agent_loop.py` | 核心执行循环 | **主要改造对象**，`process_message()` 需要支持工具循环 |
| `core/llm_client.py` | LLM 调用接口 | 需要扩展支持 tool use（当前只返回 str） |
| `core/context.py` | 上下文组装 | 工具描述需纳入 token 预算 |
| `core/config.py` | 配置加载器 | 新增工具相关配置项 |
| `config/evo_config.yaml` | 配置文件 | 新增 tools 配置段 |
| `workspace/rules/constitution/identity.md` | 身份与能力边界 | 需要从"无工具"更新为"有受限工具" |
| `main.py` | 入口 + bus 桥接 | 工具执行可能需要改桥接逻辑 |

---

## 四、技术约束

- **Python >= 3.11**，全异步架构（async/await）
- **LLM 后端**：Anthropic SDK + OpenAI 兼容，通过 provider 注册表路由
- **部署环境**：macOS 本机运行，bot 与项目代码在同一台机器
- **测试要求**：现有 499 个测试，新功能需有测试覆盖，LLM 全 mock
- **venv 路径**：`.venv/`

---

## 五、期望调研产出

1. **技术方案文档**：选型结论 + 架构设计 + 接口定义
2. **分阶段实施计划**：建议先做只读工具，验证后再加读写和执行
3. **安全评估**：风险点 + 防护措施
4. **代码改造 diff 预览**：关键接口变更的伪代码示意
