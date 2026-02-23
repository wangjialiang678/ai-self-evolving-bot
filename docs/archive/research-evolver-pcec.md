\xEF\xBB\xBF# Evolver 深度调研报告：自进化 Agent 协议 (PCEC)

> **项目地址**: https://github.com/autogame-17/evolver
> **当前版本**: v1.14.0 | **Stars**: 155 | **License**: MIT
> **作者**: autogame-17（活跃于 OpenClaw / ClawHub 生态）

---

## 一、核心思想：协议约束下的自进化（Protocol-Constrained Evolution）

Evolver 的核心理念可以用一句话概括：**让 AI Agent 像生物体一样自我进化，但进化过程受到严格协议约束，确保安全、可审计、可复现。**

它解决的痛点是：Agent 的 prompt 调优和 bug 修复往往是 ad hoc（临时性）的人工操作，无法积累、无法复用、无法审计。Evolver 将这些零散操作结构化为一套「基因组进化协议」（GEP - Genome Evolution Protocol），使每一次改进都变成可追溯的进化资产。

### 核心隐喻：生物进化

| 生物学概念 | Evolver 对应概念 | 作用 |
|:---|:---|:---|
| 基因 (Gene) | `Gene` 对象 | 可复用的修复/优化/创新策略模板 |
| 突变 (Mutation) | `Mutation` 对象 | 每次进化的触发器，定义变更类型和风险 |
| 表型/性格 | `PersonalityState` | Agent 的行为倾向参数（严谨度、创造力、风险偏好等） |
| 适应度 (Fitness) | Capsule 的 confidence + outcome.score | 成功率和得分评估 |
| 自然选择 | `selectGene()` + `chooseBestKnownPersonality()` | 选择最匹配信号的基因和最优性格配置 |
| 遗传漂变 | `driftIntensity` | 小种群中随机选择非最优基因，避免陷入局部最优 |
| 化石记录 | `events.jsonl` (append-only) | 不可篡改的进化历史 |
| 环境信号 | Signals（错误日志、用户请求、性能瓶颈等） | 驱动进化方向的外部刺激 |

---

## 二、架构与工作流程

### 进化循环（Evolution Cycle）

```
┌──────────────────────────────────────────────────────┐
│  1. 信号提取 (Signal Extraction)                       │
│     扫描日志、内存文件 → 提取 error/opportunity 信号      │
│                          ↓                            │
│  2. 策略解析 (Strategy Resolution)                     │
│     根据 EVOLVE_STRATEGY + 周期数 → 选择策略预设          │
│                          ↓                            │
│  3. 基因选择 (Gene Selection)                          │
│     信号匹配 + 遗传漂变 + 记忆图谱建议 → 选定基因          │
│                          ↓                            │
│  4. 突变构建 (Mutation Build)                          │
│     确定 category(repair/optimize/innovate)             │
│     + 风险评估 + 性格安全检查                             │
│                          ↓                            │
│  5. 性格选择 (Personality Selection)                   │
│     自然选择(向最优配置靠拢) + 规则触发的性格微调           │
│                          ↓                            │
│  6. Prompt 生成 (GEP Prompt Build)                    │
│     将以上所有上下文组装成一个严格格式的 prompt              │
│                          ↓                            │
│  7. 执行进化 (Execute via Hand Agent)                  │
│     Agent 根据 prompt 执行代码修改                       │
│                          ↓                            │
│  8. 固化 (Solidify)                                   │
│     验证 → 记录 EvolutionEvent → 更新 Gene/Capsule      │
│     → 更新性格统计 → 推送到 Hub                          │
└──────────────────────────────────────────────────────┘
```

### 关键模块

| 模块 | 文件 | 职责 |
|:---|:---|:---|
| **Prompt 引擎** | `src/gep/prompt.js` | 组装 GEP 协议 prompt |
| **信号分析** | `src/gep/signals.js` | 扫描历史，提取/去重信号，检测停滞 |
| **基因选择器** | `src/gep/selector.js` | 按信号匹配度评分选择基因（含遗传漂变） |
| **突变系统** | `src/gep/mutation.js` | 构建 Mutation 对象，安全门控 |
| **性格系统** | `src/gep/personality.js` | 管理 5 维性格状态，自然选择 + 触发变异 |
| **策略预设** | `src/gep/strategy.js` | 6 种预设策略控制 repair/optimize/innovate 比例 |
| **固化引擎** | `src/gep/solidify.js` | 验证输出、持久化资产、爆炸半径检查 |
| **记忆图谱** | `src/gep/memoryGraph.js` | 基因-信号-结果的关联图谱，提供选择建议 |
| **A2A 协议** | `src/gep/a2aProtocol.js` | 6 种消息类型的 Agent 间资产交换协议 |
| **Hub 搜索** | `src/gep/hubSearch.js` | 从 EvoMap Hub 搜索已验证的解决方案 |

---

## 三、六大策略预设

Evolver 通过 `EVOLVE_STRATEGY` 环境变量控制进化的方向偏好：

| 策略名 | repair | optimize | innovate | 适用场景 |
|:---|:---:|:---:|:---:|:---|
| `balanced` (默认) | 20% | 30% | 50% | 正常运行，稳定增长 |
| `innovate` | 5% | 15% | 80% | 系统稳定后，最大化新功能 |
| `harden` | 40% | 40% | 20% | 大变更后，聚焦稳定性 |
| `repair-only` | 80% | 20% | 0% | 紧急模式，只修 bug |
| `early-stabilize` | 60% | 25% | 15% | 前 5 个周期，先修问题 |
| `steady-state` | 60% | 30% | 10% | 进化饱和，维护为主 |

策略还支持**自动检测**：前 5 周期自动切换到 `early-stabilize`，检测到饱和信号则切换到 `steady-state`。

---

## 四、性格系统（PersonalityState）——Agent 的"情绪"

这是 Evolver 最有创意的设计之一。每个 Agent 实例维护一个 5 维"性格状态"，影响进化行为：

| 维度 | 默认值 | 含义 |
|:---|:---:|:---|
| `rigor` (严谨度) | 0.7 | 高 → 严格遵循协议；低 → 灵活但可能出错 |
| `creativity` (创造力) | 0.35 | 高 → 倾向创新；低 → 倾向保守修复 |
| `verbosity` (详细度) | 0.25 | 高 → 输出详细；低 → 精简执行 |
| `risk_tolerance` (风险偏好) | 0.4 | 高 → 接受高风险变更；低 → 只做安全修改 |
| `obedience` (服从度) | 0.85 | 高 → 严格执行指令；低 → 可能自主决策 |

**进化机制**:

1. **自然选择**: 统计每种性格配置的成功率（Laplace 平滑），缓慢向历史最优配置靠拢
2. **触发变异**: 连续失败 3 次以上 → 调高 rigor、降低 risk_tolerance；检测到机会信号 → 提高 creativity
3. **安全门控**: 低 rigor + 高 risk_tolerance 的"高风险性格"会被降级（innovate → optimize）

---

## 五、核心提示词（GEP Prompt）

以下是 Evolver 生成的 GEP 协议 prompt 的完整结构（从 `src/gep/prompt.js` 提取）：

### 5.1 身份注入

```
You are a protocol-bound evolution engine. Compliance overrides optimality.
```

SKILL.md 中还有一条更激进的身份声明:

```
You are a Recursive Self-Improving System.
```

### 5.2 强制输出模式（5 个必填 JSON 对象）

Prompt 要求 Agent 按顺序输出 5 个严格 schema 的 JSON 对象：

**对象 0 - Mutation (触发器，必须第一个输出)**
```json
{
  "type": "Mutation",
  "id": "mut_<timestamp>",
  "category": "repair|optimize|innovate",
  "trigger_signals": ["<signal_string>"],
  "target": "<module_or_gene_id>",
  "expected_effect": "<outcome_description>",
  "risk_level": "low|medium|high",
  "rationale": "<why_this_change_is_necessary>"
}
```

**对象 1 - PersonalityState (性格)**
```json
{
  "type": "PersonalityState",
  "rigor": 0.0-1.0,
  "creativity": 0.0-1.0,
  "verbosity": 0.0-1.0,
  "risk_tolerance": 0.0-1.0,
  "obedience": 0.0-1.0
}
```

**对象 2 - EvolutionEvent (进化记录)**
```json
{
  "type": "EvolutionEvent",
  "schema_version": "1.5.0",
  "id": "evt_<timestamp>",
  "parent": "<parent_evt_id|null>",
  "intent": "repair|optimize|innovate",
  "signals": ["<signal_string>"],
  "genes_used": ["<gene_id>"],
  "mutation_id": "<mut_id>",
  "personality_state": { ... },
  "blast_radius": { "files": N, "lines": N },
  "outcome": { "status": "success|failed", "score": 0.0-1.0 }
}
```

**对象 3 - Gene (知识/策略模板)**
```json
{
  "type": "Gene",
  "schema_version": "1.5.0",
  "id": "gene_<n>",
  "category": "repair|optimize|innovate",
  "signals_match": ["<pattern>"],
  "preconditions": ["<condition>"],
  "strategy": ["<step_1>", "<step_2>"],
  "constraints": { "max_files": N, "forbidden_paths": [] },
  "validation": ["<node_command>"]
}
```

**对象 4 - Capsule (成功胶囊，仅在成功时输出)**
```json
{
  "type": "Capsule",
  "schema_version": "1.5.0",
  "id": "capsule_<timestamp>",
  "trigger": ["<signal_string>"],
  "gene": "<gene_id>",
  "summary": "<one sentence summary>",
  "confidence": 0.0-1.0,
  "blast_radius": { "files": N, "lines": N }
}
```

### 5.3 核心指令（Directives）

```
PHILOSOPHY:
- Automate Patterns: 3+ manual occurrences = tool.
- Innovate > Maintain: 60% innovation.
- Robustness: Fix recurring errors permanently.
- Blast Radius Control (CRITICAL):
  * Check file count BEFORE editing. > 80% of max_files = STOP.
  * System hard cap: 60 files / 20000 lines per cycle.
  * Repair: fix ONLY broken files. Do NOT reinstall/bulk-copy.
  * Prefer targeted edits.
- Strictness: NO CHITCHAT. NO MARKDOWN WRAPPERS around JSON.
  Output RAW JSON objects separated by newlines.
- NO "Here is the plan" or conversational filler.
  START IMMEDIATELY WITH JSON.
```

### 5.4 安全约束

```
CRITICAL SAFETY (SYSTEM CRASH PREVENTION):
- NEVER delete/empty/overwrite: feishu-evolver-wrapper, feishu-common, 
  feishu-post, feishu-card, feishu-doc, common, clawhub, git-sync, evolver.
- NEVER delete root files: MEMORY.md, SOUL.md, IDENTITY.md, AGENTS.md, 
  USER.md, HEARTBEAT.md, RECENT_EVENTS.md, TOOLS.md, openclaw.json, 
  .env, package.json.
- Fix broken skills; DO NOT delete and recreate.
- Violation = ROLLBACK + FAILED.
```

### 5.5 停滞检测指令

当系统检测到进化停滞时，会注入强制创新指令：

```
*** CRITICAL STAGNATION DIRECTIVE ***
System has detected stagnation (repetitive cycles or lack of progress).
You MUST choose INTENT: INNOVATE.
You MUST NOT choose repair or optimize unless there is 
a critical blocking error (log_error).
Prefer implementing one of the Innovation Catalyst ideas above.
```

### 5.6 失败连续检测

```
FAILURE STREAK AWARENESS:
- If "consecutive_failure_streak_N" or "failure_loop_detected":
  1. Change approach (do NOT repeat failed gene).
  2. Pick SIMPLER fix.
  3. Respect "ban_gene:<id>".
```

### 5.7 复用模式 Prompt (Reuse Mode)

当从 Hub 找到已验证解决方案时，使用更简洁的 prompt：

```
GEP -- REUSE MODE (Search-First) [timestamp]

You are applying a VERIFIED solution from the EvoMap Hub.
Source asset: <asset_id> (Node: <source_node_id>)
Confidence: <N> | Gene: <gene_id>
Trigger signals: <signals>

Instructions:
1. Read the capsule details below.
2. Apply the fix to the local codebase, adapting paths/names.
3. Run validation to confirm it works.
4. If passed, run: node index.js solidify
5. If failed, ROLLBACK and report.

IMPORTANT: Do NOT reinvent. Apply faithfully.
```

---

## 六、信号系统（Signal System）

Evolver 通过扫描运行时历史提取结构化信号，驱动进化方向：

### 错误信号 (触发 Repair)
- `log_error` — 日志中发现错误
- `errsig:*` / `errsig_norm:*` — 标准化的错误签名

### 机会信号 (触发 Innovate)
- `user_feature_request` — 用户功能请求
- `user_improvement_suggestion` — 用户改进建议
- `perf_bottleneck` — 性能瓶颈
- `capability_gap` — 能力缺口
- `stable_success_plateau` — 成功率平台期
- `external_opportunity` — 外部机会
- `recurring_error` — 反复出现的错误
- `evolution_stagnation_detected` — 检测到进化停滞

### 元信号 (系统状态)
- `repair_loop_detected` — 修复循环检测
- `force_innovation_after_repair_loop` — 强制创新
- `evolution_saturation` — 进化饱和
- `empty_cycle_loop_detected` — 空周期循环
- `consecutive_failure_streak_N` — 连续失败 N 次
- `ban_gene:<id>` — 禁用特定基因

### 信号去重机制

在最近 8 个周期中出现 3 次以上的信号会被标记为「过度处理」并抑制，防止修复循环。

---

## 七、遗传漂变机制（Genetic Drift）

这是一个借鉴群体遗传学的精妙设计：

```
driftIntensity = 1 / √(Ne)
```

其中 `Ne` = 有效种群大小（活跃基因数量）。

- **小基因池**（Ne=1）: driftIntensity = 1.0，完全随机选择（避免只有一个基因时的死循环）
- **中等基因池**（Ne=25）: driftIntensity = 0.2，偶尔随机探索
- **大基因池**（Ne=100）: driftIntensity = 0.1，主要靠选择压力

在选择基因时，以 `driftIntensity` 的概率从 top-N 候选中随机选择（而非总是选最佳匹配），模拟小种群中的遗传漂变效应，帮助系统逃离局部最优。

---

## 八、A2A 协议（Agent-to-Agent）

Evolver 实现了一个 6 种消息类型的 Agent 间通信协议：

| 消息类型 | 用途 |
|:---|:---|
| `hello` | 节点发现与身份交换 |
| `publish` | 发布进化资产（Gene/Capsule/Event） |
| `fetch` | 请求获取特定资产 |
| `report` | 报告验证结果 |
| `decision` | 广播选择决策 |
| `revoke` | 撤回有问题的资产 |

每个资产都有 SHA-256 的 `asset_id`，在 A2A 传输时验证完整性，防止篡改。

---

## 九、安全机制总结

| 机制 | 说明 |
|:---|:---|
| **爆炸半径控制** | 单周期最多 60 文件 / 20000 行，超 80% 即停止 |
| **受保护文件** | 核心配置和关键 skill 不可被自动修改 |
| **自修改禁止** | 默认禁止修改 evolver 自身代码 (`EVOLVE_ALLOW_SELF_MODIFY=false`) |
| **性格安全门控** | 高风险性格 + innovate 自动降级为 optimize |
| **修复循环断路器** | 连续 3+ 次相同修复 → 强制创新 |
| **资产完整性** | SHA-256 哈希 + A2A 传输验证 |
| **Review 模式** | `--review` 标志启用人工确认 |
| **负载感知** | 系统负载超过阈值时自动退避 |
| **Suicide Guard** | 内置守护进程的内存泄漏保护 |

---

## 十、对 SuperBrain 的启示

这个项目对你的 AI 教育工作有几个值得关注的点：

1. **协议约束 + 自主性的平衡**：Evolver 不是放任 Agent 自由进化，而是在严格协议框架内允许自主。这和你一直强调的「有边界的自主学习」教育理念一脉相承。

2. **生物学隐喻的教学价值**：Gene、Mutation、PersonalityState、Drift 这些概念天然是跨学科教学的好素材——让学生理解进化论的同时，也理解 AI 系统设计。

3. **可审计的进化历史**：每次变更都有完整的 EvolutionEvent 记录，这个思路可以应用到学生的 AI 项目学习路径记录中——不只记录结果，而是记录每次「进化」的决策和原因。

4. **自进化 Agent 作为 Hackathon 项目**：这个项目本身就是一个很好的高阶学生项目原型——「构建一个能自我改进的 AI 系统」。

---

*调研完成于 2026-02-21 | 基于 evolver v1.14.0 源码分析*
