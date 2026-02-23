# Self-Evolving Agent System: Implementation Roadmap

> **Version**: v2.0  
> **Date**: 2026-02-17  
> **Covers**: MVP 分层 | 迭代计划 | 测试框架 | AI 自迭代闭环 | 设计风格  
> **Companion docs**: [Architecture v2.1](doc1_architecture_v2.md) | [Research Topics](doc3_research_topics.md)

---

## 一、MVP 分层：什么先做、什么后做、什么暂不考虑

### 1.1 三层优先级划分

```
━━━ MVP 层（必须实现，系统才能跑起来）━━━

  ✅ 上下文引擎（Context Engine）
     - token 预算管理
     - 上下文组装流水线
     - 基础 Compaction（简化版，无验证步骤）
     - 注意力锚点
     
  ✅ 记忆系统（Memory System）
     - 工作记忆（上下文窗口内）
     - 语义记忆（MEMORY.md + 基础检索）
     - 情节记忆（daily log）
     - 种子记忆加载
     
  ✅ Agent 编排器 + 基础 Agent Loop
     - EXECUTOR Agent（核心执行者）
     - CODER Agent（代码即交互语言）
     - 统一 Agent Loop（事件收集→上下文组装→推理→解析）
     
  ✅ 反思引擎（Reflection Engine）
     - 任务完成后反思（五维度）
     - 错误发生时立即反思
     - 反思结果写入语义记忆
     
  ✅ 基础工具集（硬编码，非动态注入）
     - code_execute（沙盒内 Python 执行）
     - file_read / file_write
     - web_search
     - shell_exec

  ✅ 验证基准框架
     - 指标收集管道
     - 基础测试用例
     
━━━ V1.5 层（MVP 验证后加入，需先调研设计）━━━

  📋 进化引擎
     - 规则沉淀（从反思报告积累中提炼规则）
     - 程序性记忆（skills/learned/）
     - 代码→技能自动提炼

  📋 用户模型
     - 显式偏好即时生效
     - 推断偏好（简化版：基于频率统计，非复杂算法）
     - 通知确认机制

  📋 混合搜索升级
     - 向量搜索（sqlite-vec）
     - BM25 全文搜索（FTS5）
     - 分数融合

  📋 难度路由器
     - 任务难度评估
     - 简单/中等/困难三档路由
     
  📋 Compaction 质量保障
     - 关键信息锁定
     - 压缩验证
     - 认知层级转化

  📋 多 Agent 协作
     - PLANNER Agent
     - RESEARCHER Agent
     - CRITIC Agent

━━━ V2 层（V1.5 稳定后加入，部分需独立调研）━━━

  🔬 好奇心引擎 v2（意图池 + AI 自主探索）
  🔬 基因突变（A/B 测试框架）
  🔬 每日回顾反思
  🔬 进化可视化（"本周我学到了什么"）
  🔬 事件总线完整实现
  🔬 动态工具注入（RAG 驱动）
  🔬 垂直领域适配层
  🔬 Scattered-and-Stacked 完整流程

━━━ 暂不考虑 ━━━

  ⏸️ 多用户支持（低优先级）
  ⏸️ 多通道支持（Telegram/WhatsApp）
  ⏸️ 性能优化（KV-cache 命中率优化等）
  ⏸️ 持久化 Gateway / session 管理
```

### 1.2 核心判断逻辑

| 组件 | 为什么在这个层级 |
|------|----------------|
| 上下文引擎 | 系统的心脏，没有它一切都是裸 LLM |
| 记忆系统 | 没有记忆就没有进化的基础数据 |
| 反思引擎 | 区别于 chatbot 的最小差异化——系统能从经验中学习 |
| CODER Agent | 代码即交互语言，比注册一堆工具更直接 |
| 验证框架 | 原则 9：尽早被现实检验。没有度量就没有进化 |
| 进化引擎（V1.5） | 需要反思报告积累（≥20次任务）后才有意义 |
| 好奇心引擎（V2） | 需要其他组件都稳定后才能判断"什么时候该探索" |

---

## 二、逐步迭代方案

每个迭代周期：**设计 → 实现 → 测试 → 度量 → 反思 → 下一轮**

### Iteration 0：骨架（预计 3-5 天）

**目标**：系统能接收任务、调用 LLM、返回结果、记录日志。

**实现内容**：
```
项目结构建立
├── evo/
│   ├── __init__.py
│   ├── main.py              # 入口
│   ├── config.py             # 配置加载（system.yaml）
│   ├── agent/
│   │   ├── base.py           # Agent 基类 + Agent Loop
│   │   └── executor.py       # EXECUTOR Agent
│   ├── context/
│   │   └── engine.py         # 上下文引擎（简化版：固定模板）
│   ├── memory/
│   │   ├── working.py        # 工作记忆（上下文内）
│   │   └── episodic.py       # 情节记忆（daily log 写入）
│   ├── tools/
│   │   ├── registry.py       # 工具注册表（硬编码）
│   │   └── builtins.py       # 内置工具
│   └── llm/
│       └── client.py         # LLM 调用封装
└── workspace/                 # 运行时数据目录
```

**交互方式**：命令行 REPL
```python
# 用法
python -m evo
> 帮我搜索 AI 教育市场的最新趋势
[Agent 执行... 记录到 daily log...]
> 结果呈现
```

**验证标准**：
- [ ] 能接收自然语言任务
- [ ] 能调用 LLM 生成响应
- [ ] 能调用至少 1 个工具（web_search 或 code_execute）
- [ ] Daily log 正确记录每次交互
- [ ] 配置文件能正常加载

**度量指标**：
- 任务完成率（手动评估 10 个简单任务）
- 端到端延迟

---

### Iteration 1：上下文工程（预计 5-7 天）

**目标**：上下文引擎从固定模板升级为动态组装，加入语义记忆和种子知识。

**新增/升级**：
```
evo/
├── context/
│   └── engine.py         # 升级：token 预算 + 动态组装流水线
│                          #   步骤 1-9 全部实现
├── memory/
│   ├── semantic.py       # 语义记忆（MEMORY.md 读写）
│   ├── search.py         # 基础搜索（先用关键词匹配，后续升级向量）
│   └── seeds.py          # 种子记忆加载
└── workspace/
    └── memory/
        ├── MEMORY.md
        └── seeds/seed_memory.md
```

**验证标准**：
- [ ] 上下文组装包含：系统 prompt + 任务锚点 + 相关记忆 + 历史 + 工具描述
- [ ] Token 预算控制生效（不超过窗口的 75%）
- [ ] 种子记忆在首次启动时正确加载
- [ ] 语义记忆能写入和读出

**度量指标**：
- 对比 Iteration 0 的固定模板 vs 动态组装：同 10 个任务的质量对比
- Token 使用效率（实际使用 / 预算）

---

### Iteration 2：反思引擎（预计 5-7 天）

**目标**：系统能从每次任务中学习，反思结果写入记忆。

**新增**：
```
evo/
├── agent/
│   └── reflector.py      # REFLECTOR Agent
├── reflection/
│   ├── engine.py         # 反思引擎
│   ├── prompts.py        # 反思 prompt 模板
│   └── report.py         # ReflectionReport 数据结构
└── workspace/
    └── reflections/       # 反思报告存储
```

**关键机制**：
- 每次任务完成后自动触发反思
- 反思报告写入 `reflections/` 目录
- 反思中提取的策略建议写入语义记忆（MEMORY.md）
- 错误发生时立即触发快速反思

**验证标准**：
- [ ] 成功任务生成完整五维反思报告
- [ ] 失败任务能正确诊断错误类型
- [ ] 反思提取的策略建议被写入 MEMORY.md
- [ ] 后续同类任务的上下文中能检索到相关反思

**度量指标（核心）**：
- **反思价值测试**：跑 20 次同类任务，前 10 次清空反思，后 10 次保留
  → 对比成功率和质量差异
- 反思报告中策略建议的数量和质量（人工评估）

---

### Iteration 3：CODER Agent + 代码即交互（预计 5-7 天）

**目标**：系统能直接写代码解决问题，不限于预注册工具。

**新增**：
```
evo/
├── agent/
│   └── coder.py          # CODER Agent
├── tools/
│   └── sandbox.py        # 代码沙盒执行环境
└── skills/
    └── auto_extract.py   # 代码→技能自动提炼逻辑
```

**关键机制**：
- CODER Agent 能生成 Python 代码并在沙盒中执行
- 失败时自动读取错误、修正代码（最多 3 次）
- 反思引擎追踪代码片段的复用频率

**验证标准**：
- [ ] 能解决"没有对应工具"的任务（如数据转换、文件处理）
- [ ] 代码执行在沙盒内，不影响宿主环境
- [ ] 错误时能自动修正并重试

**度量指标**：
- 代码执行成功率
- 对比"有 CODER"vs"无 CODER"时的任务覆盖范围

---

### Iteration 4：Compaction + 长对话支持（预计 4-5 天）

**目标**：系统能处理长对话而不丢失关键信息。

**新增/升级**：
```
evo/
├── context/
│   ├── compaction.py     # Compaction 机制
│   └── engine.py         # 升级：触发 Compaction
└── workspace/
    └── memory/
        └── compaction/
            ├── summaries.jsonl
            └── archives/
```

**验证标准**：
- [ ] 当 token 超过阈值时自动触发 Compaction
- [ ] Compaction 后关键信息未丢失（人工检查 5 个长对话案例）
- [ ] 原始内容正确归档到 archives/
- [ ] Compaction 后系统能继续正常工作

**度量指标**：
- **Compaction 质量测试**：Compaction 后基于摘要回答关于原始内容的 10 个问题
  → 正确率目标 > 90%
- 压缩率（摘要 tokens / 原始 tokens）

---

### Iteration 5：进化引擎——规则沉淀（预计 5-7 天）

**前提**：此时系统已积累了足够的反思报告（≥20 次任务）

**新增**：
```
evo/
├── evolution/
│   ├── engine.py         # 进化引擎
│   ├── crystallize.py    # 规则沉淀逻辑
│   └── skill_writer.py   # 技能文件生成
├── skills/
│   ├── loader.py         # 技能加载和匹配
│   └── learned/          # 学习到的技能存储
└── workspace/
    └── evolution/
        ├── strategy_log.jsonl
        └── rules/active_rules.yaml
```

**关键机制**：
- 扫描反思报告，识别重复出现的策略建议
- 达到阈值（3 次）后沉淀为正式规则
- 新规则进入 probation 状态，验证后升级为 active
- 技能文件自动生成并注入上下文

**验证标准**：
- [ ] 重复出现的策略建议能被识别和合并
- [ ] 沉淀出的规则能在后续任务的上下文中出现
- [ ] probation→active 的晋升机制正常工作

**度量指标（核心）**：
- **进化速率测试**：追踪第 1/10/30/50 次执行同类任务的表现
  → 是否呈现出明显的学习曲线
- 沉淀出的规则数量 vs 被实际使用的规则数量

---

### Iteration 6：用户模型（预计 4-5 天）

**新增**：
```
evo/
├── user_model/
│   ├── model.py          # 用户模型管理
│   ├── explicit.py       # 显式偏好处理
│   └── inferred.py       # 推断偏好处理（简化版：频率统计）
└── workspace/
    └── user_model/
        ├── profile.yaml
        ├── explicit_prefs.yaml
        └── inferred_prefs.yaml
```

**关键机制**：
- 显式偏好：用户声明 → 即时写入 → 即时生效
- 推断偏好：行为信号累积 → 置信度计算 → 通知用户确认
- 用户模型注入上下文的步骤 4

**验证标准**：
- [ ] 用户说"我喜欢简洁的回答"后，下一次回答风格立即改变
- [ ] 推断偏好达到阈值后，以非阻断方式通知用户
- [ ] 用户可以查看和修改 profile.yaml

**度量指标**：
- 用户模型准确度：预测偏好 vs 实际选择的一致性

---

### Iteration 7+：V1.5 其余组件

按需实现：混合搜索、难度路由器、PLANNER/RESEARCHER/CRITIC Agent、Compaction 质量保障升级。每个组件独立迭代，独立验证。

---

## 三、测试方案

### 3.1 三层测试体系

```
层次 1：单元测试（确保组件输出正确）
  工具：pytest
  覆盖：每个模块的核心函数
  执行：每次代码变更后自动运行
  
层次 2：集成测试（确保组件协作正确）
  工具：pytest + 预定义场景脚本
  覆盖：典型任务的端到端执行
  执行：每个 iteration 完成后运行
  
层次 3：效能验证（评估有效性，不只是正确性）
  工具：自定义评估脚本 + LLM-as-Judge
  覆盖：每个组件的验证基准
  执行：每个 iteration 完成后运行，结果写入 metrics.jsonl
```

### 3.2 具体测试用例

**单元测试示例**：

```python
# test_context_engine.py

def test_token_budget_not_exceeded():
    """上下文组装不超过 token 预算"""
    engine = ContextEngine(budget_ratio=0.75)
    ctx = engine.assemble(task="分析竞品", model_window=128000)
    assert ctx.total_tokens <= 128000 * 0.75

def test_task_anchor_always_present():
    """任务锚点始终在上下文中"""
    engine = ContextEngine()
    ctx = engine.assemble(task="写技术文档")
    assert "当前任务" in ctx.rendered
    assert "写技术文档" in ctx.rendered

def test_seed_memory_loaded():
    """种子记忆在冷启动时正确加载"""
    memory = MemorySystem(workspace="./test_workspace")
    memory.cold_start()
    entries = memory.search("竞品分析")
    assert len(entries) > 0  # 种子记忆中应有竞品分析相关内容

def test_compaction_preserves_locked_info():
    """Compaction 保留被锁定的关键信息"""
    compactor = Compactor()
    original = "用户要求：必须用中文。分析了三个竞品..."
    locked = ["必须用中文"]
    summary = compactor.compact(original, locked_info=locked)
    assert "中文" in summary
```

**集成测试示例**：

```python
# test_scenarios.py

async def test_simple_task_e2e():
    """简单任务端到端执行"""
    system = EvoSystem(config="test_config.yaml")
    result = await system.run("今天天气怎么样")
    assert result.status == "SUCCESS"
    assert len(result.output) > 0
    # 检查 daily log 已写入
    assert Path("workspace/memory/daily/").glob("*.md")

async def test_reflection_after_task():
    """任务完成后触发反思"""
    system = EvoSystem(config="test_config.yaml")
    result = await system.run("帮我写一段 Python 排序代码")
    # 检查反思报告已生成
    reflections = list(Path("workspace/reflections/").glob("*.yaml"))
    assert len(reflections) > 0

async def test_learning_from_failure():
    """失败后反思并在重试中应用教训"""
    system = EvoSystem(config="test_config.yaml")
    # 第一次故意给一个容易失败的任务
    r1 = await system.run("用已弃用的 API 发送邮件")
    # 第二次同类任务
    r2 = await system.run("用 Python 发送邮件")
    # 第二次应该能看到第一次的错误教训在上下文中
    assert "错误" in r2.context_snapshot or "注意" in r2.context_snapshot
```

**效能验证示例**：

```python
# test_effectiveness.py

async def test_memory_effectiveness():
    """验证记忆系统的有效性"""
    system = EvoSystem(config="test_config.yaml")
    
    # Phase 1: 无记忆基线
    system.disable_memory()
    baseline_scores = []
    for task in BENCHMARK_TASKS[:10]:
        result = await system.run(task)
        score = await llm_judge(task, result.output)  # LLM 评分
        baseline_scores.append(score)
    
    # Phase 2: 启用记忆
    system.enable_memory()
    memory_scores = []
    for task in BENCHMARK_TASKS[:10]:
        result = await system.run(task)
        score = await llm_judge(task, result.output)
        memory_scores.append(score)
    
    improvement = mean(memory_scores) - mean(baseline_scores)
    log_metric("memory_effectiveness", improvement)
    assert improvement > 0.15  # 目标：>15% 提升

async def test_evolution_learning_curve():
    """验证进化引擎的学习曲线"""
    system = EvoSystem(config="test_config.yaml")
    
    # 同类任务跑 30 次
    scores_over_time = []
    for i in range(30):
        task = generate_similar_task("competitive_analysis")
        result = await system.run(task)
        score = await llm_judge(task, result.output)
        scores_over_time.append(score)
    
    # 检查是否有上升趋势
    first_10_avg = mean(scores_over_time[:10])
    last_10_avg = mean(scores_over_time[-10:])
    log_metric("evolution_learning_curve", last_10_avg - first_10_avg)
    assert last_10_avg > first_10_avg  # 应该有改进
```

### 3.3 LLM-as-Judge 评估框架

```python
async def llm_judge(task: str, output: str, criteria: list = None) -> float:
    """用 LLM 评估任务输出质量"""
    if criteria is None:
        criteria = ["准确性", "完整性", "有用性", "格式规范"]
    
    prompt = f"""
    请评估以下 AI 助手对任务的完成质量。
    
    任务：{task}
    输出：{output}
    
    评估维度：{criteria}
    
    请给出 0-1 的总分，并简要说明理由。
    返回 JSON：{{"score": 0.85, "reason": "..."}}
    """
    
    # 使用独立模型做评估（避免自我评估偏差）
    result = await llm_call(model="judge_model", prompt=prompt)
    return json.loads(result)["score"]
```

---

## 四、AI 自迭代闭环

### 4.1 人类参与 vs AI 自主参与

```
━━━ 必须人类参与 ━━━

  🧑 架构设计决策（哪些组件、什么接口）
  🧑 设计原则和价值观定义
  🧑 评估标准和验证基准的制定
  🧑 测试结果的最终判断（"这算不算改进"）
  🧑 安全边界的定义
  🧑 用户体验的主观评估
  🧑 调研议题的方向选择

━━━ AI 可以自主完成 ━━━

  🤖 根据架构文档生成代码
  🤖 编写单元测试和集成测试
  🤖 运行测试并收集度量数据
  🤖 分析测试结果，生成改进建议
  🤖 根据改进建议修改代码
  🤖 反思"这次迭代做了什么、效果如何"
  🤖 生成每个 iteration 的总结报告

━━━ 人类审核，AI 执行 ━━━

  🧑🤖 效能验证的评估标准（人类定，AI 执行评估）
  🧑🤖 新组件的接口设计（人类确认，AI 实现）
  🧑🤖 测试基准任务集的选择（人类确认，AI 准备数据）
```

### 4.2 AI 自迭代工作流

```
每个 Iteration 的 AI 自主工作流：

Step 1: 阅读当前 iteration 的目标和规格
  输入：本文档中对应 iteration 的描述
  输出：实现计划（文件列表 + 每个文件的职责）

Step 2: 编写代码
  输入：架构文档 + 实现计划
  输出：代码文件
  约束：遵循设计风格约束（极简、< 300 行/模块）

Step 3: 编写测试
  输入：代码 + 本文档中对应的测试用例
  输出：测试文件
  
Step 4: 运行测试
  输入：代码 + 测试
  输出：测试报告（通过/失败/度量数据）

Step 5: 分析结果
  输入：测试报告
  输出：分析报告
    - 哪些测试通过了
    - 哪些测试失败了，为什么
    - 度量指标是否达标
    - 改进建议

Step 6: 修正（如果有测试失败）
  循环 Step 2-5 直到所有测试通过
  最多循环 3 次，超过则标记为"需要人类介入"

Step 7: 生成 iteration 报告
  输出：
    - 本次迭代做了什么
    - 度量数据对比（vs 上一个 iteration）
    - 发现的问题和改进建议
    - 下一个 iteration 的建议调整
```

### 4.3 "用自己的锤子打自己的钉子"

```
自举测试（Bootstrapping Test）原则：

系统在开发到一定程度后，应该用自身来辅助开发自身：

Phase 1（Iteration 0-2）：
  系统太原始，无法自举
  所有开发和测试由 AI（Claude）直接完成

Phase 2（Iteration 3-4）：
  系统有了基本的 CODER Agent 和记忆系统
  开始用系统自己来：
  - 生成部分测试代码
  - 分析测试结果
  - 记住之前的修改和教训

Phase 3（Iteration 5+）：
  系统有了反思引擎和进化引擎
  开始用系统自己来：
  - 反思"我在开发自己的过程中遇到了什么问题"
  - 提炼"代码开发"领域的技能
  - 进化代码生成的策略

自举成功标志：
  系统在帮助开发自身新功能时的效率和质量
  应该随着 iteration 递增而提升。
  如果没有提升 → 说明进化机制没有生效。
```

---

## 五、设计风格详述

### 5.1 技术选型

```yaml
language: Python 3.11+
package_manager: pip (requirements.txt, no poetry/pipenv for simplicity)

核心依赖（尽量少）:
  - pydantic          # 数据结构定义和验证
  - httpx             # HTTP 客户端（LLM API 调用）
  - pyyaml            # YAML 读写
  - tiktoken          # Token 计数
  - pytest            # 测试

后续按需引入:
  - sqlite-vec        # 向量搜索（Iteration 7+）
  - rich              # 终端美化（可选）

不使用:
  - LangChain / LlamaIndex  # 太重，自己写更可控
  - 任何 ORM                 # 直接用文件系统
  - 任何消息队列             # 先用内存 list
  - Docker（开发期）         # 先用 subprocess 做沙盒
```

### 5.2 代码风格规范

```python
# ✅ 好的风格：简洁、自解释

@dataclass
class ReflectionReport:
    task_id: str
    outcome: Literal["SUCCESS", "PARTIAL", "FAILURE"]
    quality_score: float
    strategies: list[str]
    errors: list[str]

class ReflectionEngine:
    def __init__(self, llm: LLMClient, memory: MemorySystem):
        self.llm = llm
        self.memory = memory
    
    async def reflect(self, report: TaskReport) -> ReflectionReport:
        prompt = self._build_prompt(report)
        response = await self.llm.generate(prompt)
        reflection = self._parse(response)
        self.memory.write_semantic(reflection.strategies)
        return reflection

# ❌ 不好的风格：过度抽象、过度配置

class AbstractReflectionStrategyFactory(ABC):  # 不需要
    ...
class ReflectionPluginManager:  # 不需要
    ...
```

### 5.3 文件和目录命名

```
文件名：全英文，snake_case
  context_engine.py ✅
  上下文引擎.py ❌

类名：PascalCase
  ContextEngine ✅

函数/变量名：snake_case
  assemble_context() ✅

配置文件：YAML
  system.yaml ✅

数据文件：
  结构化数据 → JSONL (每行一个 JSON)
  人类可读内容 → Markdown
  配置和模型 → YAML
```

---

## 六、Iteration 间的度量跟踪

```yaml
# workspace/validation/metrics.jsonl
# 每条记录追踪一个 iteration 的关键指标

{"iteration": 0, "date": "2026-02-20", "metrics": {
  "task_completion_rate": 0.7,
  "avg_quality_score": 0.65,
  "avg_latency_ms": 5000,
  "total_test_pass": 12,
  "total_test_fail": 3
}}

{"iteration": 1, "date": "2026-02-25", "metrics": {
  "task_completion_rate": 0.75,
  "avg_quality_score": 0.72,
  "memory_effectiveness_lift": 0.10,
  "token_efficiency": 0.68,
  "total_test_pass": 20,
  "total_test_fail": 1
}}

# 每个新 iteration 的指标应该 >= 上一个 iteration
# 如果出现下降，需要分析原因
```

---

## 七、风险和缓解

| 风险 | 影响 | 缓解策略 |
|------|------|---------|
| LLM API 调用成本过高 | 开发期 token 消耗大 | 效能验证用小样本；日常测试用快速模型 |
| 反思质量不稳定 | 垃圾策略进入记忆 | 置信度门槛 + 人工抽查前几次反思 |
| Compaction 信息丢失 | 系统"忘记"重要内容 | 归档不删除 + 压缩验证 |
| 进化方向错误 | 系统越来越差 | 保守期策略 + 自动回滚 |
| 代码沙盒逃逸 | 安全风险 | 开发期用 subprocess + 限时限资源 |

---

> **下一份文档**：[Research Topics](doc3_research_topics.md) — 独立调研议题清单
