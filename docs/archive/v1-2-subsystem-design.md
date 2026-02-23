# 自进化智能体系统：核心子系统设计

> **文档版本**: v1.0  
> **文档性质**: 子系统详细设计文档  
> **配套文档**: [系统架构概览](doc1) | [动态工作流与行为模式](doc3)

---

## 一、上下文引擎：详细设计

上下文引擎是整个系统的心脏。它的核心问题是：在有限的 token 预算内，为模型组装最优的决策信息。

### 1.1 上下文组装流水线

每次 Agent 需要做推理时，上下文引擎执行以下流水线：

```
步骤 1：计算 token 预算
  输入：模型的上下文窗口大小、预留给模型输出的 token 数
  输出：可用 token 预算
  规则：预算 = 窗口大小 × 0.75 - 预留输出 token
         (保留 25% 作为安全边际，避免截断)

步骤 2：组装固定区（System Prompt）
  内容：系统身份定义 + 当前生效的策略规则 + 安全边界
  特征：这部分在一个 session 内基本不变，KV-cache 命中率接近 100%
  预算占用：约 10-15%
  关键原则：固定区的内容只追加不修改（append-only），保证 KV-cache 有效

步骤 3：组装任务锚点（Task Anchor）
  内容：当前任务的描述 + 当前进度 + 待完成步骤列表
  类比：Manus 的 todo.md。每次推理都重复插入，防止模型"忘记自己在做什么"
  预算占用：约 5%
  实现方式：
    task_anchor = f"""
    ## 当前任务
    {task_description}
    
    ## 进度
    已完成: {completed_steps}
    当前步骤: {current_step}
    待完成: {remaining_steps}
    
    ## 注意事项
    {active_warnings}
    """

步骤 4：注入用户偏好摘要
  内容：从用户模型中提取的、与当前任务相关的偏好
  预算占用：约 2-3%
  实现方式：只注入与当前任务类型相关的偏好，不全量注入
  示例："用户偏好：输出格式-对比表格优先于长段落；详细程度-中等；语言-中文"

步骤 5：注入相关记忆
  内容：从记忆系统中检索出的、与当前任务相关的信息
  预算占用：约 10-20%（动态调整）
  检索策略：
    a. 用当前任务描述作为 query，在语义记忆中做混合搜索
    b. 检查是否有与当前任务类型匹配的程序性记忆（技能）
    c. 如果任务涉及特定用户/项目，检索相关情节记忆
    d. 按相关性评分排序，从高到低装载直到预算用完

步骤 6：注入近期对话历史
  内容：当前 session 的近期消息
  预算占用：约 20-30%
  关键设计：
    a. 最近 3-5 轮对话保持完整（保持上下文连贯性）
    b. 更早的对话用摘要替代（Compaction 结果）
    c. 工具调用结果只保留关键信息，不保留完整原始输出

步骤 7：注入错误轨迹
  内容：如果之前的步骤中有错误，保留错误信息及处理方式
  预算占用：约 5%（仅在有错误时）
  关键原则（来自 Manus）：不删除错误，而是显式保留，让模型看到
  "之前尝试了 X 但失败了，原因是 Y"——这比什么都不说更有价值

步骤 8：注入工具描述
  内容：与当前任务相关的工具的描述
  预算占用：约 5-10%
  关键设计（来自 Manus 的 RAG 驱动策略）：
    a. 不全量注入所有工具（可能有数十个）
    b. 用任务描述在工具描述的向量索引中检索最相关的 3-7 个
    c. 工具描述使用精简版本（名称 + 一句话描述 + 关键参数）

步骤 9：预算检查与裁剪
  如果总 token 超出预算：
    a. 首先裁剪"相关记忆"中相关性最低的条目
    b. 然后压缩"对话历史"（对更早的内容做进一步摘要）
    c. 最后减少工具描述数量
  绝不裁剪：系统 prompt、任务锚点、最近 2 轮对话
```

### 1.2 Compaction（压缩）机制

当 session 的累计 token 接近上下文窗口的限制时，触发 Compaction。

**触发条件**：

```
soft_threshold = context_window - reserve_tokens - safety_margin
当 session_tokens > soft_threshold 时触发
```

**Compaction 流程**（五步）：

```
步骤 1：Pre-Compaction Memory Flush（关键步骤）
  目的：在压缩之前，确保重要信息不会丢失
  实现：向当前 Agent 发送一个静默指令：
    "你即将失去对历史对话的直接访问。请将以下信息
     写入持久化记忆文件：
     - 当前任务的关键发现
     - 用户表达的重要偏好或要求
     - 任何未完成的承诺或待办事项
     - 可能在未来有用的关键事实"
  来源：OpenClaw 的 pre-compaction flush 设计
  要求：这个指令使用 NO_REPLY 标记，用户看不到这个过程

步骤 2：生成压缩摘要
  输入：要被压缩的历史对话
  输出：一段简洁的摘要（约为原内容的 10-20%）
  使用模型：快速模型（如 Haiku），不需要最强模型
  摘要格式：
    """
    [会话摘要 - 截至 {timestamp}]
    用户目标：{goal}
    关键决策：{decisions}
    已完成：{completed}
    待完成：{pending}
    重要约束：{constraints}
    """

步骤 3：替换历史内容
  将被压缩的原始对话替换为步骤 2 生成的摘要
  保留最近 N 轮对话不做压缩（默认 N=5）

步骤 4：持久化压缩记录
  将压缩摘要写入 compaction/summaries.jsonl
  如果未来需要恢复细节，可以从原始 session 文件中重新加载

步骤 5：索引更新
  将新的摘要内容同步到向量索引和全文索引
  确保压缩后的信息仍然可以被检索到
```

### 1.3 KV-Cache 优化策略

为了最大化 KV-cache 命中率（减少重复计算、降低延迟和成本），系统遵循以下规则：

```
规则 1：System Prompt 在 session 内只追加不修改
  原因：修改前面的内容会使整个 KV-cache 失效
  实现：新的策略指令追加到 system prompt 末尾

规则 2：工具名称使用结构化前缀
  原因：前缀触发模型在特定 token 范围内采样（logit masking），
        而不需要改变上下文结构
  实现：browser_*, shell_*, file_*, search_*, human_*

规则 3：对话历史采用 append-only 结构
  原因：只在末尾追加新消息，不修改或删除已有消息
  Compaction 时的处理：不修改原始消息，而是在开头插入摘要块，
  后续推理从摘要块+最近消息开始（跳过已压缩的中间部分）
```

---

## 二、记忆系统：详细设计

### 2.1 四层记忆的读写规则

**工作记忆（Working Memory）**

```
位置：仅存在于上下文窗口内，不单独持久化
写入时机：每次上下文组装时自动构建
读取时机：模型推理时自动可见
容量：由上下文引擎的 token 预算决定
特点：最快（零延迟）、最小（受限于 token 预算）、最短命（每次推理重建）
```

**情节记忆（Episodic Memory）**

```
位置：memory/daily/YYYY-MM-DD.md + sessions/*.jsonl
写入时机：
  - 每次工具调用后，记录调用和结果摘要
  - 每次用户交互后，记录用户的输入和系统的输出摘要
  - 每次任务完成后，记录任务报告
写入格式（daily log）：
  ## 10:30 - 竞品分析任务
  - 用户请求分析竞品 X 的产品策略
  - 搜索了竞品官网、应用商店、行业报告
  - 搜索用户评价时遇到困难，改为使用应用商店评分
  - 生成对比表格，用户满意
  - 总用时 15 分钟，12 次工具调用
  
读取时机：
  - 上下文组装时，加载今日和昨日的 daily log
  - 搜索相关记忆时，在所有 daily log 中做混合搜索
  
容量：无限制（磁盘存储）
保留策略：最近 30 天保留完整日志，更早的日志只保留摘要
```

**语义记忆（Semantic Memory）**

```
位置：memory/MEMORY.md
写入时机：
  - Compaction 时的 pre-flush（模型主动写入重要信息）
  - 反思引擎提取的通用规律
  - 进化引擎确认的新规则
  - 用户模型的关键更新
写入格式：
  ## 用户相关
  - Michael 是超脑 AI 孵化器的创始人，关注 AI 教育
  - 偏好中文交流，文风倾向启发性而非说教性
  
  ## 领域知识
  - Manus 的核心优势是 Context Engineering，不是模型本身
  - OpenClaw 的 Gateway 架构支持真正的异步中断
  
  ## 策略经验
  - 竞品分析任务：先查官方渠道，再查第三方评价
  - 长文档生成：先大纲后逐段，比一次性生成效果好
  
读取时机：
  - 每次上下文组装时，用混合搜索检索相关条目
  
更新规则：
  - 新信息不覆盖旧信息，而是追加或标注更新
  - 矛盾信息会被标记，等待确认后再解决
  - 定期做去重和合并（由进化引擎触发）
  
容量：建议控制在 50KB 以内（约 12000 token）
超出处理：触发语义记忆压缩——合并相近条目、删除过时条目
```

**程序性记忆（Procedural Memory）**

```
位置：skills/learned/*.yaml
写入时机：
  - 反思引擎从成功任务中提炼出可复用策略
  - 进化引擎确认突变后的改进策略
  - 用户显式教授系统一个新流程
写入格式（单个技能文件）：
  # skills/learned/competitive_analysis.yaml
  skill_id: "competitive_analysis_v3"
  name: "竞品分析"
  description: "系统化的竞品分析流程"
  trigger_conditions:
    - "用户请求分析竞品或竞争对手"
    - "需要对比多个产品或服务"
  steps:
    - action: "确认分析维度"
      details: "与用户确认关注哪些方面（产品功能、定价、市场定位、用户评价）"
    - action: "官方信息收集"
      details: "搜索竞品官网、产品页面、定价页面"
      tools: ["browser_navigate", "browser_extract"]
    - action: "第三方评价收集"
      details: "搜索应用商店评分、行业报告、用户论坛"
      tools: ["search_web", "browser_navigate"]
    - action: "生成对比分析"
      details: "用表格形式呈现（用户偏好），标注信息来源和时效性"
  learned_from: ["reflection_042", "reflection_056"]
  success_rate: 0.88
  last_updated: "2026-02-14"
  version_history:
    - v1: "基础版本"
    - v2: "添加了'先官方后第三方'的顺序策略"
    - v3: "添加了信息时效性验证步骤"
  
读取时机：
  - 上下文组装时，如果当前任务匹配某个技能的 trigger_conditions，
    将该技能的步骤注入上下文
  
匹配方式：
  - trigger_conditions 与当前任务描述做语义相似度计算
  - 相似度 > 0.8 时自动注入
  - 0.6 < 相似度 < 0.8 时作为"参考"注入（模型可以选择是否遵循）
```

### 2.2 混合搜索算法

记忆检索使用向量搜索 + BM25 关键词搜索的混合策略。

```
输入：query（自然语言查询字符串）
输出：ranked_results（按相关性排序的记忆条目列表）

算法：
  1. 向量搜索
     query_embedding = embed(query)
     vector_results = vector_db.search(query_embedding, top_k=20)
     # 返回 [(chunk, cosine_similarity_score), ...]
     
  2. BM25 关键词搜索
     keyword_results = fts_db.search(query, top_k=20)
     # 返回 [(chunk, bm25_rank), ...]
     # bm25_score = 1 / (1 + rank)，rank 0 → 1.0，rank 9 → 0.1
     
  3. 分数融合（Reciprocal Rank Fusion 变体）
     for each unique chunk across both result sets:
       vector_score = vector_results.get(chunk, 0)
       keyword_score = keyword_results.get(chunk, 0)
       # 默认权重：向量 70%，关键词 30%
       final_score = 0.7 * vector_score + 0.3 * keyword_score
     
  4. 使用 UNION（非 INTERSECTION）
     # 只在一个搜索中出现的结果也会被包含
     # 这确保了召回率——宁可多返回一些不太相关的，也不漏掉重要的
     
  5. 按 final_score 降序排列
     return top_k results with score > min_threshold
```

**为什么使用两种搜索**：

- 向量搜索擅长语义匹配："Mac Studio 上运行的 Gateway" 能匹配 "gateway 主机"
- BM25 擅长精确匹配：错误代码、函数名、特定 ID 等精确 token
- 单独使用任何一种都会有盲点

### 2.3 记忆生命周期管理

```
新信息进入
    │
    ▼
┌──────────────┐
│   工作记忆    │ ◄── 当次推理可见
│  (上下文窗口) │
└──────┬───────┘
       │ 任务完成 / Compaction
       ▼
┌──────────────┐
│   情节记忆    │ ◄── 完整记录，按日期存储
│ (daily logs)  │
└──────┬───────┘
       │ 反思引擎提炼（每次任务完成后）
       ▼
┌──────────────┐
│   语义记忆    │ ◄── 提炼后的规律和知识
│ (MEMORY.md)   │
└──────┬───────┘
       │ 进化引擎确认（成功率达标后）
       ▼
┌──────────────┐
│  程序性记忆   │ ◄── 结构化的可复用技能
│  (skills/)    │
└──────────────┘

垃圾回收：
  - 情节记忆：30 天后只保留摘要
  - 语义记忆：定期去重合并，删除被标记为过时的条目
  - 程序性记忆：连续 5 次被评估为无效的技能自动归档到 deprecated
```

---

## 三、反思引擎：详细设计

### 3.1 反思触发条件

反思不只是在"任务完成后"触发，而是有多种触发条件：

```
触发条件 1：任务完成（Post-Task Reflection）
  时机：每次任务完成后（无论成败）
  深度：完整五维反思
  使用模型：主推理模型

触发条件 2：错误发生（Error Reflection）
  时机：工具调用失败、模型输出被用户否定、执行超时
  深度：仅做错误诊断和策略提取
  使用模型：快速模型
  紧迫性：立即执行（结果注入当前上下文，帮助后续步骤避免重复错误）

触发条件 3：定期回顾（Periodic Review）
  时机：每天结束时（可配置）
  深度：回顾今日所有任务，做跨任务的模式识别
  使用模型：主推理模型
  目的：发现单任务反思无法发现的系统性问题
  
  示例输出："今天 5 个任务中有 3 个在网页搜索步骤耗时过长，
           可能需要优化搜索策略或增加搜索结果缓存"

触发条件 4：用户反馈（User Feedback Reflection）
  时机：用户给出明确的评价、修改系统输出、追问或抱怨
  深度：分析用户反馈与系统行为之间的差距
  使用模型：用户建模专用模型
```

### 3.2 反思 Prompt 模板

给反思 Agent 的 prompt 结构如下：

```
你是一个专注于自我改进的反思分析师。你的任务是分析以下任务的执行过程，
提取可以改进系统未来表现的洞察。

## 任务信息
- 原始请求：{original_request}
- 最终结果：{final_output}
- 用户反应：{user_reaction}  // 满意/修改了输出/追问了/无反应

## 执行轨迹
{execution_trace}
// 包含每个步骤的 Agent、行动、工具调用、结果、耗时、token 用量

## 当前系统规则
{active_rules}
// 系统当前遵循的策略规则

## 请分析以下五个维度：

### 1. 结果评估
任务是否成功完成了用户的原始意图？输出质量如何？
（不只看表面完成度，要判断用户的深层需求是否被满足）

### 2. 效率分析
哪些步骤是高效的？哪些步骤浪费了时间或 token？
有没有不必要的工具调用？有没有可以合并的步骤？

### 3. 错误诊断
如果有错误或困难：根本原因是什么？
属于以下哪类：
  A. 信息不足（需要更好的研究策略）
  B. 策略不当（需要更新规则）
  C. 工具误用（需要优化工具选择）
  D. 模型能力限制（需要更强模型或拆分任务）

### 4. 策略建议
从这次经验中，提炼出 1-3 条具体的、可执行的策略建议。
格式：
  - 策略：{具体策略}
  - 适用场景：{什么时候使用}
  - 预期效果：{使用后会改善什么}
  - 置信度：{HIGH/MEDIUM/LOW}

### 5. 能力缺口
这次任务暴露了系统在哪些方面的不足？
需要什么新工具、新知识或新技能？

请以 YAML 格式输出分析结果。
```

### 3.3 从反思到进化的传递

反思引擎的输出通过以下规则传递给进化引擎：

```
规则 1：置信度过滤
  只有 confidence >= MEDIUM 的策略建议才传递给进化引擎
  LOW 置信度的建议仅记录在反思报告中，不触发进化

规则 2：重复验证
  一条策略建议需要在至少 3 次独立反思中被提出，才升级为候选规则
  这避免了单次经验导致的过度反应

规则 3：矛盾检测
  如果新的策略建议与已有规则矛盾，不自动替换
  而是生成一个"矛盾报告"，由进化引擎做更深入的分析
  或者（如果矛盾涉及重要决策）升级给人类判断

规则 4：紧急通道
  如果某个错误被标记为 HIGH 严重性且 HIGH 置信度
  （如"安全相关的问题"），跳过重复验证，直接生效
```

---

## 四、进化引擎：详细设计

### 4.1 规则沉淀（Crystallization）流程

```
输入：反思引擎传来的策略建议（已通过置信度和重复验证）
输出：新的程序性记忆（skill 文件）或对现有规则的更新

流程：
  1. 检查是否已存在类似规则
     使用语义搜索在 active_rules.yaml 和 skills/ 中查找
     
  2. 如果无类似规则 → 创建新规则
     a. 生成规则草案
     b. 标记为 status: probation（试用期）
     c. 设定验证目标：在接下来 N 次相关任务中追踪效果
     d. N 次任务后评估：成功率 > 阈值 → status: active
                        成功率 < 阈值 → status: deprecated
     
  3. 如果存在类似规则 → 更新现有规则
     a. 合并新信息（如添加新的适用场景、调整参数）
     b. 更新版本号和 last_updated
     c. 保留版本历史，方便回滚
     
  4. 持久化
     写入 evolution/rules/active_rules.yaml
     写入 evolution/strategy_log.jsonl（审计日志）
```

### 4.2 基因突变（Mutation）流程

```
前提条件：
  目标技能的 success_rate >= 0.85（在近 20 次使用中）
  且至少已使用 10 次（有足够样本）
  
突变类型和实现：

突变类型 A：参数微调
  描述：对现有规则中的数值参数进行小范围调整
  示例：将"搜索结果取 top 5"改为"取 top 3"
  生成方法：让模型分析现有规则的参数，提出 2-3 个微调方案
  风险等级：LOW（自动执行，无需人类批准）

突变类型 B：顺序重组
  描述：改变现有步骤的执行顺序
  示例：将"先搜索后规划"改为"先规划后搜索"
  生成方法：让模型分析执行轨迹，识别可能的顺序优化
  风险等级：MEDIUM（自动执行，但标记为实验性）

突变类型 C：步骤替换
  描述：用不同的工具或方法替换某个步骤
  示例：将"使用网页搜索获取信息"替换为"使用 API 直接查询"
  生成方法：让模型分析步骤的弱点，结合工具注册表提出替代方案
  风险等级：MEDIUM

突变类型 D：全新策略
  描述：引入一个完全新的策略或步骤
  示例：在分析任务中增加"先列出自己不知道什么"的元认知步骤
  生成方法：让主推理模型基于多次反思报告，创造性地提出新方法
  风险等级：HIGH（需要人类批准，除非系统处于"自主实验"模式）

突变 Prompt 模板：

  你是一个系统进化工程师。以下是一个已经表现良好的技能
  （成功率 {success_rate}%），请提出改进方案。
  
  当前技能：{current_skill}
  
  近期执行数据：
  - 成功案例的共同特征：{success_patterns}
  - 失败案例的共同特征：{failure_patterns}
  - 用户反馈趋势：{feedback_trends}
  
  请提出 1-3 个突变方案，每个方案说明：
  1. 具体改变什么
  2. 为什么认为这会更好
  3. 可能的风险
  4. 如何验证效果

突变评估（A/B 测试）：
  
  1. 创建突变版本 → 保存为 skills/mutations/skill_XXX_v2.yaml
  2. 接下来 N 次相关任务中，交替使用原版和突变版
     （奇数次用原版，偶数次用突变版）
  3. N 次后比较：
     if mutated.success_rate > original.success_rate + min_improvement:
       KEEP mutation → 替换原版，更新版本号
     elif mutated.success_rate < original.success_rate - tolerance:
       DISCARD mutation → 删除突变文件，记录失败原因
     else:
       INCONCLUSIVE → 继续测试更多次，或保持原版
  4. 所有结果记录到 evolution/mutation_tests.jsonl
```

### 4.3 用户适应（User Adaptation）流程

```
信号来源：
  
  1. 显式反馈
     - 用户说"我更喜欢X"、"不要用这种方式"
     - 信号强度：HIGH
     - 处理：直接更新用户模型的对应维度
     
  2. 选择行为
     - 用户在多个方案中选择了某一个
     - 信号强度：MEDIUM
     - 处理：记录选择，当同一维度累计 3 次以上一致选择时更新模型
     
  3. 修改行为
     - 用户修改了系统的输出（如重写了某段文字、调整了格式）
     - 信号强度：MEDIUM-HIGH
     - 处理：分析修改前后的差异，提取偏好信号
     
  4. 追问行为
     - 用户对某个方面追问，说明系统的回答不够深入或偏离了兴趣点
     - 信号强度：LOW-MEDIUM
     - 处理：记录追问主题，用于调整未来回答的详细程度和方向
     
  5. 沉默信号
     - 用户没有修改也没有评价 → 可能满意，也可能没仔细看
     - 信号强度：VERY LOW
     - 处理：不做更新，但记录任务完成

用户模型更新算法：

  每个偏好维度维护一个信念分数 (belief_score)：
  
  belief = {
    "value": "简洁风格",        // 当前信念值
    "confidence": 0.72,          // 置信度 (0-1)
    "evidence_count": 8,         // 支持证据数量
    "last_updated": "2026-02-14",
    "contradictions": 1          // 矛盾证据数量
  }
  
  更新规则：
    new_confidence = (old_confidence * evidence_count + signal_strength) 
                     / (evidence_count + 1)
    
    如果新信号与当前信念一致 → confidence 增加
    如果新信号与当前信念矛盾 → contradictions++
    如果 contradictions / evidence_count > 0.3 → 标记为"需要确认"
    
    只有 confidence > 0.6 的信念才会被注入上下文
    confidence > 0.9 的信念被视为"已确认偏好"
```

---

## 五、好奇心引擎：详细设计

### 5.1 缺口检测算法

```
在每次 Agent 推理前和推理后都运行缺口检测：

推理前检测（Pre-Inference Gap Detection）：
  输入：当前任务描述 + 已有信息
  检查项：
    a. 任务需要哪些信息？（让模型列出）
    b. 这些信息中，哪些已经在记忆/上下文中？
    c. 哪些缺失的信息可以通过自主研究获取？
    d. 哪些缺失的信息只能从人类那里获取？
  如果 (d) 非空 → 触发好奇心

推理后检测（Post-Inference Gap Detection）：
  输入：模型的推理输出
  检查项：
    a. 模型的输出中是否有不确定的表述？（如"可能"、"大概"、"不确定"）
    b. 模型是否在多个选项间犹豫不决？
    c. 模型的输出是否与用户模型中的已知偏好不一致？（可能意味着偏好发生了变化）
  如果检测到显著不确定性 → 触发好奇心

能力边界检测（Capability Boundary Detection）：
  输入：当前任务 + 工具注册表
  检查项：
    a. 任务是否需要物理世界的行动？（去某个地方、拍照、打电话）
    b. 任务是否需要访问受限系统？（内部网络、付费数据库）
    c. 任务是否需要主观判断？（"这个设计好看吗？"）
  如果 (a) 或 (b) → 请求人类行动
  如果 (c) → 请求人类判断
```

### 5.2 提问策略

好奇心引擎不是简单地把问题抛给用户，而是精心设计每个提问：

```
提问设计原则：

原则 1：最小化打扰
  一次只问一个问题（不要一次性抛出 5 个问题）
  优先使用选择题而非开放题（降低用户回答成本）
  标注紧急度（让用户知道是否需要立即回复）

原则 2：提供上下文
  告诉用户为什么需要这个信息
  说明如果不提供，系统会采用什么替代方案
  
原则 3：智能时机
  不在用户可能忙碌的时间提问（可从用户行为模式推断）
  紧急问题立即发送，非紧急问题积攒后批量发送
  如果用户超时未回复，自动使用 fallback 策略继续执行

提问模板：

  对知识缺口：
    "我在处理[任务描述]时，需要了解[具体信息]。
     你能告诉我[精确问题]吗？
     如果你现在不方便，我会先用[替代方案]继续。"
     
  对决策不确定：
    "关于[决策点]，我整理了两个方案：
     A. [方案A] — 优点是[X]，缺点是[Y]
     B. [方案B] — 优点是[P]，缺点是[Q]
     你更倾向哪个？"
     
  对能力边界：
    "这个任务中有一步我无法完成：[具体步骤]。
     需要你帮我[具体行动]。
     完成后，请把结果[以什么方式]发给我。"
```

### 5.3 人类响应的整合

```
收到人类响应后的处理流程：

1. 将响应作为事件注入事件总线
   event_type: HUMAN_RESPONSE
   包含原始问题 ID + 响应内容

2. 上下文引擎将响应注入当前上下文
   位置：紧接在任务锚点之后（高优先级位置）

3. 记忆系统记录这次交互
   情节记忆：记录提问和响应
   语义记忆（如果响应包含可复用信息）：提炼后写入

4. 用户模型更新
   如果响应体现了偏好（如在方案中做了选择），更新用户模型

5. 继续执行被暂停的任务
   Agent 从事件流中获取 HUMAN_RESPONSE 事件
   结合新信息重新评估当前步骤
   继续执行
```

---

## 六、研究模块：详细设计

### 6.1 研究任务分类与策略

```
研究类型 1：事实查证（Fact Verification）
  目的：验证一个具体事实是否正确
  策略：
    a. 先在记忆系统中搜索（可能之前已经验证过）
    b. 搜索 2-3 个权威来源（官方网站 > 维基百科 > 新闻）
    c. 如果来源一致 → 确认事实
    d. 如果来源矛盾 → 标记为"有争议"并呈现多方观点
  工具调用上限：5 次

研究类型 2：主题调研（Topic Research）
  目的：全面了解一个主题
  策略：
    a. 先生成调研大纲（需要了解哪些方面？）
    b. 对每个方面执行搜索
    c. 优先使用权威来源（学术论文 > 官方博客 > 行业报告 > 新闻）
    d. 将结果结构化整理，标注来源和时效性
    e. 识别信息缺口，决定是否需要进一步搜索或询问人类
  工具调用上限：20 次
  
研究类型 3：开源项目探索（Repository Exploration）
  目的：了解一个开源项目的架构、特点、适用场景
  策略：
    a. 读取 README.md
    b. 分析项目结构（关键目录和文件）
    c. 读取核心代码文件（入口文件、配置文件、核心模块）
    d. 搜索相关的技术博客和讨论
    e. 将发现整理为结构化分析
  工具调用上限：15 次

研究类型 4：深度研究（Deep Research）
  目的：对复杂问题做全面、深入的分析
  策略：
    a. 启动 Planner Agent 分解研究问题
    b. 为每个子问题启动独立的 Researcher Agent（可并行）
    c. 汇总所有子研究结果
    d. Critic Agent 检查一致性和完整性
    e. 生成综合报告
  特殊要求：每个子研究的 Agent 有独立的上下文（避免跨研究的信息污染）
  工具调用上限：50 次
```

### 6.2 研究结果的处理

```
研究结果不直接全量注入上下文，而是经过压缩处理：

1. 原始结果存入情节记忆（完整保留，供未来参考）

2. 生成压缩摘要用于上下文注入
   使用快速模型对原始结果做摘要
   摘要需保留：关键数据点、核心结论、信息来源、时效性标注
   摘要丢弃：冗余描述、不相关细节、重复信息

3. 如果研究发现了重要的通用知识 → 写入语义记忆

4. 如果研究发现了新的工具或方法 → 通知进化引擎评估
```

---

## 七、Agent Loop：统一执行模型

所有 Agent（无论角色）都遵循统一的执行循环：

```
async function agentLoop(agent, initialEvent):
  while not terminated:
    # 步骤 1：收集事件
    events = eventBus.getEventStream(agent.sessionId)
    newEvents = events.since(agent.lastProcessedEventId)
    
    # 步骤 2：组装上下文
    context = contextEngine.assembleContext(
      sessionId = agent.sessionId,
      currentTask = agent.currentTask,
      newEvents = newEvents,
      tokenBudget = agent.model.contextWindow * 0.75
    )
    
    # 步骤 3：模型推理
    response = await llm.generate(
      model = modelRouter.selectModel(agent.currentTask.type),
      context = context
    )
    
    # 步骤 4：解析响应
    if response.hasToolCall:
      # 执行工具调用
      toolResult = await toolRegistry.execute(
        response.toolCall.name,
        response.toolCall.params
      )
      # 将工具结果作为事件发回事件总线
      eventBus.emit(Event(
        type = TOOL_RESULT,
        payload = toolResult
      ))
      
    elif response.hasHumanQuery:
      # 需要人类帮助
      curiosityEngine.sendQuery(response.humanQuery)
      # 继续循环，等待 HUMAN_RESPONSE 事件
      
    elif response.isComplete:
      # 任务完成
      eventBus.emit(Event(
        type = AGENT_OUTPUT,
        payload = response.output
      ))
      # 触发反思
      reflectionEngine.reflect(agent.generateTaskReport())
      terminated = true
      
    elif response.needsPlanning:
      # 需要分解为子任务
      subTasks = response.subTasks
      for task in subTasks:
        subAgent = orchestrator.spawnAgent(task)
        # 子 Agent 有独立的上下文和事件流
        
    # 步骤 5：检查是否有新的用户中断
    if eventBus.hasNewUserMessage(agent.sessionId):
      # 用户发了新消息！在下一轮循环中处理
      # 不需要特殊逻辑——事件驱动架构天然支持
      
    # 步骤 6：检查资源限制
    if agent.toolCallCount > maxToolCalls:
      # 防止无限循环
      agent.forceComplete("达到工具调用上限")
      
    if agent.tokenUsage > maxTokenBudget:
      # 触发 Compaction 或结束
      contextEngine.triggerCompaction(agent.sessionId)
      
    # 更新最后处理的事件 ID
    agent.lastProcessedEventId = events.lastId
```

这个统一模型的关键特征：

1. **事件驱动**：不是请求-响应，而是持续的事件流处理
2. **天然可中断**：用户的新消息只是事件流中的新事件，下一轮循环自动处理
3. **自我监控**：内置资源限制检查，防止失控
4. **反思集成**：任务完成后自动触发反思，不需要额外调度

---

> **下一篇文档**：《动态工作流与行为模式》——展示系统在典型场景下的完整运行流程，以及各种行为模式的触发和执行细节。
