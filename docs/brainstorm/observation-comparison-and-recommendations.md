# 观察-复盘-迭代机制对比分析与改进建议

> **日期**：2026-02-24
> **对比项目**：AI自进化系统 vs 长时间运行智能体
> **分析目标**：从"长时间运行智能体"的五层上下文体系中提取可借鉴的设计，改进我们系统的观察、错误识别、复盘和迭代能力。

---

## 一、两套系统的架构对比

### 长时间运行智能体：五层上下文金字塔

```
L4 综合洞察      ← 每日复盘 + 跨会话记忆（MEMORY.md）
L3 知识库        ← 14 个已验证模式 + 学习规则 + 修复脚本
L2 研究文档      ← 7 篇深度报告 + 8 份会话统计
L1 结构化日志    ← Observer 诊断报告 + 日记 + 决策反馈 JSONL
L0 运行时产物    ← 原始日志（backend/frontend/MCP）+ 信号文件 + 进度文件
```

**核心特点**：
- **数据驱动**：从真实的 HTTP 请求日志、浏览器操作日志、HMR 事件等原始数据出发
- **Hook 实时采集**：`on_tool_result.py` 每次工具调用后自动写入信号（字符串匹配，无 LLM 开销）
- **模式即规则**：14 个 verified pattern 用精确的 `match_rule`（如 `tool_result contains 'detached Frame'`）秒级匹配
- **丰富的中间层**：Observer 日记（L1）是人可读的叙事形式，连接原始日志和高层复盘

### AI自进化系统：LLM 驱动的闭环流水线

```
Architect 提案/执行/回滚  ← 读 Observer 报告 → 设计方案 → 修改规则
Observer 深度分析          ← 每日 02:00 聚合轻量日志 + 信号 → LLM 综合分析
Observer 轻量观察          ← 每次任务后 Gemini Flash 写 1 行笔记
信号检测                   ← 从反思结果中按规则提取信号（7 种类型）
反思引擎                   ← 每次任务后 LLM 分类（ERROR/PREFERENCE/NONE + root_cause）
任务执行                   ← user_message → context assembly → LLM → response
```

**核心特点**：
- **LLM 判断为核心**：反思和观察都依赖 LLM 分类，灵活但成本高
- **闭环自动化**：Architect 可自主提案 → 执行 → 验证 → 回滚
- **规则即程序**：所有行为存在 .md 规则文件中，Architect 通过修改文件改变系统行为
- **四层记忆**：working / episodic / semantic / procedural 分层管理

---

## 二、关键差距分析

### 差距 1：原始可观测性数据严重不足（L0 缺失）

**长时间运行智能体有什么**：
- `backend.log`：每个 HTTP 请求/响应（精确到端口号，可见双连接模式）
- `frontend.log`：每次 HMR 热更新（可重建代码修改节奏）
- `mcp-puppeteer.log`：每次浏览器操作的精确时间戳
- `claude-progress.txt`：Agent 自述的进度快照
- `feature_list.json`：功能清单（跨会话唯一真相源）

**我们缺什么**：
- `task_trace` 中 `tools_used` 始终为空列表 `[]`（`agent_loop.py:218`）
- 没有原始的 LLM 请求/响应日志（只记录了 token 数和时长）
- 没有系统运行日志的结构化采集（Python logging 输出到 stderr，未持久化）
- 没有跨会话的进度文件

**影响**：Observer 和 Architect 做分析时，**看不到原始数据**，只能看到 LLM 二次加工后的摘要。这相当于医生只能看到护士的诊断报告，看不到原始化验单。

### 差距 2：错误识别完全依赖 LLM 判断，缺乏确定性检测

**长时间运行智能体的做法**：
```json
{
  "pattern_id": "detached-frame",
  "match_rule": "tool_result contains 'detached Frame' OR 'Detached Frame'",
  "fix_type": "IMMEDIATE+RULE",
  "confidence": 0.95
}
```
- 14 个 verified pattern，每个都有**精确的字符串匹配规则**
- 匹配后**秒级触发**自动干预（重启 MCP、清理锁文件等）
- 置信度基于实际出现次数，不是 LLM 猜测

**我们的做法**：
```python
# reflection.py - 每次都要调 LLM
llm_raw = await self.llm_client.complete(
    system_prompt=_SYSTEM_PROMPT,
    user_message=user_prompt,
    model="gemini-flash", max_tokens=500,
)
```
- 每次错误识别都需要一次 LLM 调用（Gemini Flash，~200-500 tokens）
- LLM 可能误分类（特别是区分 ERROR vs PREFERENCE 的边界模糊）
- 没有确定性的模式匹配作为"快速通道"
- `error_patterns.md` 是给人看的叙述文本，不是机器可执行的匹配规则

### 差距 3：信号检测规则偏简单，缺少时间损失和频率维度

**长时间运行智能体额外追踪的**：
- **时间损失估算**：每个问题类型的累计时间损失（如"安全钩子 ~75 分钟"）
- **Agent 自愈率**：30 个问题中 25 个自行恢复（83%）
- **七维分类**：发现时机 / 修复形态 / 泛化程度 / 自主程度 / 紧急程度 / 时间成本 / 证据数量
- **问题频率统计**：`problem_frequency.json`

**我们的 `SignalDetector` 只有 4+3 条规则**：
1. `user_corrections > 0` → user_correction (MEDIUM)
2. `type==ERROR && outcome==FAILURE` → task_failure (HIGH)
3. `root_cause==knowledge_gap` → capability_gap (MEDIUM)
4. `tokens > 10000` → efficiency_opportunity (LOW)
5. 跨任务：2+ task_failure → repeated_error (HIGH)
6. 跨任务：3+ user_pattern → promoted user_pattern (MEDIUM)
7. 跨任务：14天无 rule_validated → rule_unused (LOW)

**缺少的维度**：
- 没有追踪每个错误类型的**时间成本**（duration_ms 记录了但没分析）
- 没有追踪**同类错误的连续出现模式**（只看绝对数量，不看密度）
- 没有追踪**用户纠正的具体内容**（只知道"纠正了 1 次"，不知道纠正了什么）

### 差距 4：缺乏"Observer 日记"这样的中间叙事层

**长时间运行智能体的 Observer 日记**（`observer/diary/2026-02-24.md`）：
```markdown
## 会话概况
| 项目 | 值 |
|------|-----|
| 目标项目 | AI自进化系统（补齐 12 个未完成 feature） |
| 运行模式 | CC寄生模式 Path B |
| 持续时间 | ~3 小时 |
| 最终成果 | 30/30 features 完成，499 个测试通过 |
| 人工干预 | 5 次角色纠偏 |

## 检测到的模式
### P1: 子代理工具调用不可见（新发现 - CRITICAL）
```

这是一层**人可读的叙事摘要**，介于原始日志和深度分析报告之间。它的价值：
- 人可以快速理解"今天发生了什么"
- 可以作为复盘的直接素材
- 保留了关键事件的时间线和因果关系

**我们的 Observer 轻量日志**只是 JSONL 格式的单行笔记（`light_logs/{date}.jsonl`），缺乏叙事性和时间线组织。深度报告（`deep_reports/{date}.md`）虽然是 Markdown，但是**纯 LLM 生成**的分析，不是基于原始事实的叙事。

### 差距 5：反思引擎的输入信息密度不够

**当前 task_trace 传给反思引擎的信息**：
```python
user_prompt = (
    f"任务ID: {task_id}\n"
    f"用户消息: {user_message}\n"
    f"系统回复: {system_response[:500]}\n"      # 截断到 500 字符
    f"用户反馈: {user_feedback if ... else '无'}\n"
    f"使用工具: {tools_used}\n"                   # 始终为 []
    f"消耗 token: {tokens_used}\n"
    f"耗时: {duration_ms}ms"
)
```

**问题**：
- `system_response` 被截断到 500 字符，反思引擎看不到完整回复
- `tools_used` 始终为空，无法分析工具使用模式
- 没有**错误堆栈**信息（如果 LLM 调用出错，只记录了兜底回复）
- 没有**上下文组装详情**（用了哪些规则、注入了哪些记忆）

---

## 三、改进建议

### 建议 1（P0）：补齐 L0 原始日志层

**目标**：让 Observer 和 Architect 能看到原始数据，而不仅仅是 LLM 加工后的摘要。

**具体措施**：

1. **丰富 task_trace**：在 `agent_loop.py` 中记录更多原始数据
   ```python
   task_trace = {
       # ...现有字段...
       "rules_injected": assembled.sections_used,          # 注入了哪些规则区段
       "context_budget_usage": assembled.budget_usage,     # token 预算使用详情
       "memories_retrieved": [m[:100] for m in memories],  # 检索到的记忆摘要
       "full_response_length": len(response),              # 完整回复长度
       "llm_raw_tokens": ...,                              # LLM 实际消耗 token
   }
   ```

2. **持久化原始日志**：新增 `workspace/logs/` 目录
   ```
   workspace/logs/
   ├── tasks/{date}.jsonl        # 完整 task_trace（含完整 response）
   ├── llm_calls/{date}.jsonl    # 每次 LLM 调用的输入/输出/耗时/token
   ├── errors/{date}.jsonl       # 所有 try/except 捕获的异常
   └── system/{date}.log         # Python logging 输出的持久化
   ```

3. **添加 LLM 调用审计日志**：在 `llm_client.py` 中记录每次 complete() 调用
   ```python
   # 每次 LLM 调用自动写审计记录
   {
       "timestamp": "...",
       "caller": "reflection_engine",  # 调用者
       "model": "gemini-flash",
       "system_prompt_tokens": 150,
       "user_message_tokens": 200,
       "response_tokens": 80,
       "duration_ms": 1200,
       "success": true
   }
   ```

### 建议 2（P0）：添加确定性模式匹配层

**目标**：对已知的错误模式实现零成本、秒级检测，不依赖 LLM。

**具体措施**：

新增 `extensions/signals/pattern_matcher.py`：
```python
class PatternMatcher:
    """确定性模式匹配器，零 LLM 开销。"""

    def __init__(self, patterns_path: str):
        self.patterns = self._load_patterns(patterns_path)

    def match(self, task_trace: dict) -> list[dict]:
        """在 task_trace 中匹配已知模式。"""
        matches = []
        response = str(task_trace.get("system_response", ""))
        error_text = str(task_trace.get("error_text", ""))

        for pattern in self.patterns:
            rule = pattern["match_rule"]
            if self._check_rule(rule, response, error_text):
                matches.append({
                    "pattern_id": pattern["pattern_id"],
                    "severity": pattern["severity"],
                    "fix_type": pattern["fix_type"],
                    "auto_action": pattern.get("auto_action"),
                })
        return matches
```

**存储格式**（复用长时间运行智能体的 verified.json 结构）：
```json
[
  {
    "pattern_id": "llm-empty-response",
    "match_rule": "response == '' OR response == null",
    "severity": "high",
    "fix_type": "IMMEDIATE",
    "auto_action": "retry_with_fallback_model",
    "confidence": 0.9,
    "evidence_count": 0,
    "time_cost_minutes": 0
  }
]
```

**与现有系统的集成**：在 `_post_task_pipeline` 中，PatternMatcher 在 ReflectionEngine **之前**运行。如果匹配到 IMMEDIATE 级别的模式，直接触发自动修复，无需等 LLM 反思。

### 建议 3（P1）：添加 Observer 日记层

**目标**：在 JSONL 轻量日志和 LLM 深度报告之间，增加一个人可读的、基于事实的叙事层。

**具体措施**：

新增 `extensions/observer/diary.py`：
```python
class ObserverDiary:
    """每日观察日记：基于事实的叙事摘要。"""

    async def write_daily_entry(self, light_logs, signals, metrics_summary):
        """
        从原始数据生成日记（不依赖 LLM，纯模板渲染）。

        输出格式：
        # Observer 日记 — 2026-02-25

        ## 会话概况
        | 项目 | 值 |
        |------|-----|
        | 处理任务数 | 12 |
        | 成功率 | 83.3% |
        | 总 token | 45000 |
        | 用户纠正 | 2 次 |

        ## 事件时间线
        - 10:15 task_001 SUCCESS (2800 tokens, 正常完成)
        - 10:32 task_002 FAILURE (5200 tokens, 错误假设)
          → 信号: task_failure (HIGH)
        - 10:45 task_003 SUCCESS (1200 tokens, 正常完成)
          → 用户纠正 1 次

        ## 检测到的信号
        - [HIGH] task_failure: task_002 因 wrong_assumption 失败
        - [MEDIUM] user_correction: task_003 被用户纠正 1 次
        """
```

**关键设计**：
- **不调 LLM**，纯模板渲染 + 数据聚合
- **保留时间线**，可以追溯因果关系
- **每日自动生成**，可作为人工复盘的起点

### 建议 4（P1）：增强反思引擎的输入和输出

**目标**：让反思引擎有更多原始信息可分析，输出更结构化的可追溯信息。

**具体措施**：

1. **扩大 system_response 截断阈值**：从 500 字符提高到 2000
2. **传入上下文组装详情**：
   ```python
   f"注入规则区段: {assembled.sections_used}\n"
   f"Token 预算使用: {assembled.budget_usage}\n"
   ```
3. **反思输出增加字段**：
   ```json
   {
     "type": "ERROR",
     "outcome": "FAILURE",
     "root_cause": "wrong_assumption",
     "lesson": "...",
     "what_was_wrong": "具体错在哪里",
     "what_should_have_been": "正确做法是什么",
     "prevention_rule": "可直接转化为规则的一句话"
   }
   ```

### 建议 5（P1）：追踪时间成本和错误频率

**目标**：知道哪些错误类型最"贵"（时间消耗最多），优先修复高 ROI 的问题。

**具体措施**：

在 `MetricsTracker` 中新增：
```python
def get_error_cost_analysis(self, days: int = 30) -> list[dict]:
    """
    按错误类型聚合时间成本。

    返回：
    [
        {
            "root_cause": "wrong_assumption",
            "count": 5,
            "total_duration_ms": 85000,
            "avg_duration_ms": 17000,
            "total_tokens": 42000,
            "latest_occurrence": "2026-02-25T10:15:30"
        },
        ...
    ]
    """
```

这直接借鉴了长时间运行智能体的"时间损失估算"表：
```
| 问题类型 | 累计损失 |
|---------|---------|
| 安全钩子阻断 + 绕过 | ~75 分钟 |
| Puppeteer detached frame | 17 分钟 |
| 合计 | ~139 分钟 |
```

让 Architect 在决定优先级时，有**量化的 ROI 依据**。

### 建议 6（P2）：引入"已验证/待验证/已否定"三态模式库

**目标**：让系统的错误知识有明确的生命周期，避免误报固化。

**具体措施**：

```
workspace/patterns/
├── verified.json      # 已验证（evidence_count >= 2，可信）
├── hypotheses.json    # 待验证（首次发现，需要更多证据）
└── rejected.json      # 已否定（验证无效，保留为反例）
```

**生命周期**：
```
首次检测 → hypotheses.json (evidence_count=1)
            │
            ├── 再次出现 → evidence_count++ → if count >= 2 → verified.json
            │
            └── 14 天无复现 → rejected.json（保留反例，防止重复假设）
```

当前 `error_patterns.md` 是 append-only 的文本文件，没有验证/否定机制。长时间运行智能体的三态设计更科学。

### 建议 7（P2）：用户纠正的内容化追踪

**目标**：不只知道"用户纠正了"，还要知道"纠正了什么"，为规则学习提供精确素材。

**当前问题**：`user_corrections` 只是一个计数器（0 或 1），`user_feedback` 是原始文本但没有结构化分析。

**改进**：在反思引擎中增加对 user_feedback 的专门分析：
```json
{
  "correction_type": "factual_error | style_mismatch | missing_info | wrong_approach",
  "correction_detail": "用户希望回复更简洁，当前回复过于冗长",
  "actionable_rule": "当用户问简单问题时，回复控制在 3 句以内"
}
```

---

## 四、优先级排序与实施路径

| 优先级 | 建议 | 预期 ROI | 实施难度 | 依赖 |
|--------|------|---------|---------|------|
| **P0** | 1. 补齐 L0 原始日志 | 极高（所有后续改进的基础） | 低 | 无 |
| **P0** | 2. 确定性模式匹配 | 高（零 LLM 开销的错误检测） | 低 | 建议 1 |
| **P1** | 3. Observer 日记 | 中（提升复盘效率） | 低 | 建议 1 |
| **P1** | 4. 反思引擎增强 | 中（提升错误识别精度） | 低 | 无 |
| **P1** | 5. 时间成本追踪 | 中（量化 ROI 决策） | 低 | 无 |
| **P2** | 6. 三态模式库 | 中（知识生命周期管理） | 中 | 建议 2 |
| **P2** | 7. 纠正内容化追踪 | 中（精确规则学习） | 低 | 建议 4 |

**实施路径**：
```
Phase 1 (P0): 补数据基础
  → 丰富 task_trace 字段
  → 添加 LLM 调用审计日志
  → 实现 PatternMatcher + 初始 verified.json

Phase 2 (P1): 增强分析能力
  → Observer 日记模板渲染器
  → 反思引擎输入/输出扩展
  → MetricsTracker 时间成本分析

Phase 3 (P2): 精细化知识管理
  → 三态模式库 + 自动升降级
  → 用户纠正结构化分析
```

---

## 五、核心洞察总结

### 长时间运行智能体教会我们的三件事

1. **原始数据 > LLM 摘要**
   所有好的分析都建立在丰富的原始数据之上。长时间运行智能体有 5 种原始日志、14 个精确匹配规则、每个问题的时间成本。我们目前的观察链过度依赖 LLM 判断，原始数据层（L0）几乎是空的。

2. **确定性检测 + LLM 分析 = 最佳组合**
   对已知模式用字符串匹配（零成本、零延迟、零误判），对未知模式用 LLM 分析。两者不是互斥的，而是互补的。我们目前只有后者。

3. **人可读的中间层是复盘的关键**
   JSONL 日志给机器看，深度报告给决策者看，Observer 日记给"回顾今天发生了什么"的人看。三者服务不同受众，缺一不可。我们目前缺少日记这个中间层。

### 我们做得好的地方

1. **自动化闭环**：Architect → 提案 → 执行 → 验证 → 回滚 的自动化程度比长时间运行智能体更高
2. **规则即程序**：所有行为存在 .md 文件中，Architect 通过修改文件改变行为，这个设计优于硬编码
3. **Council 审议**：多视角审查机制在长时间运行智能体中没有对应物
4. **Token 预算管理**：精确的上下文预算分配（12% 身份 + 8% 经验 + 15% 记忆 + 25% 历史）是成熟的设计

### 一句话总结

> **我们的执行链（反思 → 信号 → 提案 → 执行 → 回滚）设计得很好，但"眼睛"（原始可观测数据）不够锐利。补齐 L0 数据层和确定性匹配能力，是投入产出比最高的改进方向。**
