# 代码审核修复任务

> **优先级**: P0（阻塞集成）
> **基于**: A1-A7 代码审核结果
> **分支**: 在 `main` 上直接修复

---

## P0 阻塞级（必须修复，否则模块间集成会崩溃）

### FIX-1: A2 backup_id 缺少 `backup_` 前缀

**文件**: `extensions/evolution/rollback.py`，`_make_backup_id` 方法（约 229 行）

**现状**:
```python
return f"{now.strftime('%Y%m%d_%H%M%S')}_{proposal_id}"
```

**应改为**:
```python
return f"backup_{now.strftime('%Y%m%d_%H%M%S')}_{proposal_id}"
```

**原因**: 规格书约定 backup_id 格式为 `backup_{datetime}_{proposal_id}`，其他模块（A3 auto_rollback_check）会依赖此格式。

**测试影响**: `tests/test_rollback.py` 中所有断言 backup_id 的测试需同步更新。

---

### FIX-2: A6 `compact()` 返回字段名不匹配规格

**文件**: `extensions/context/compaction.py`，`compact` 方法返回值（约 109-118 行）

**现状**:
```python
{
    "compacted_history": [...],
    "summary": "...",
    "original_tokens": N,
    "compacted_tokens": N,
    "compression_ratio": N,
    "flushed_to_memory": [...],
    "key_decisions_preserved": N,
    "key_decisions_total": N
}
```

**应改为**:
```python
{
    "compressed_history": [...],
    "summary": "...",
    "stats": {
        "original_tokens": N,
        "compressed_tokens": N,
        "ratio": N
    }
}
```

**具体改动**:
1. `compacted_history` → `compressed_history`
2. `compacted_tokens` → `compressed_tokens`
3. `compression_ratio` → `ratio`
4. 将 `original_tokens`、`compressed_tokens`、`ratio` 嵌套到 `stats` 子字典中
5. `flushed_to_memory`、`key_decisions_preserved`、`key_decisions_total` 可保留为额外字段（不影响契约），也可删除

**测试影响**: `tests/test_compaction.py` 中所有引用上述字段名的断言需同步更新。

---

### FIX-3: A7 `lightweight_observe()` 返回值完全不符合规格

**文件**: `extensions/observer/engine.py`，`lightweight_observe` 方法（约 86-148 行）

**现状**: 返回一个日志记录结构（timestamp, task_id, outcome, tokens, model, signals, error_type, note）

**规格要求返回**:
```python
{
    "patterns_noticed": [...],   # 注意到的模式列表
    "suggestions": [...],        # 建议列表
    "urgency": "none"|"low"|"high"  # 紧急度
}
```

**修复思路**:
- 调用 LLM（gemini-flash/qwen）分析 task_trace + reflection_output
- 从 LLM 返回中提取 patterns_noticed、suggestions、urgency
- 或者基于 reflection_output 中的信息（type、root_cause）推导这三个字段
- 现有的日志写入逻辑可以保留（作为内部副作用），但 **返回值必须符合规格**

**测试影响**: `tests/test_observer.py` 中 `lightweight_observe` 相关的断言需更新为验证新字段。

---

## P1 需修复（不阻塞集成，但应在此轮一起修）

### FIX-4: A4 缺失 `capability_gap` 和 `rule_unused` 信号检测

**文件**: `extensions/signals/detector.py`

**现状**: 规格要求 8 种信号类型，代码只实现了 6 种（`user_correction`, `task_failure`, `repeated_error`, `performance_degradation`, `efficiency_opportunity`, `user_pattern`）+ `rule_validated`。`capability_gap` 和 `rule_unused` 完全未实现。

**修复要求**:
- **`capability_gap`**: 在 `detect()` 中检测——当 reflection_output 的 root_cause 为 `knowledge_gap` 时生成
- **`rule_unused`**: 在 `detect_patterns()` 中检测——查看 lookback 窗口内未被任何任务 trace 引用的规则

如果 `rule_unused` 的检测依赖规则系统（当前 A4 无法访问规则列表），可以暂时只实现框架 + 注释说明依赖，在集成阶段补全。但 `capability_gap` 必须实现。

**测试**: 为两种新信号类型各添加至少 1 个测试用例。

---

### FIX-5: A2 `backup()` 目录创建失败时不应静默返回

**文件**: `extensions/evolution/rollback.py`，`backup` 方法（约 35-39 行）

**现状**: `mkdir` 异常被 catch 后仍返回 backup_id，导致调用者拿到一个无效的 backup。

**应改为**: 让异常向上抛出（移除该处的 try-catch），或者 raise 一个自定义异常。

**测试**: 添加一个测试用例验证目录创建失败时抛出异常。

---

### FIX-6: A2 `cleanup()` 应删除过期的 active 备份

**文件**: `extensions/evolution/rollback.py`，`cleanup` 方法（约 183 行）

**现状**: `if metadata.get("status") == "active": continue` 导致 active 状态的备份永不过期。

**应改为**: 删除该跳过逻辑。所有超过 `retention_days` 的备份都应被清理，无论 status。

**测试**: 确认现有 cleanup 测试覆盖了 active 备份的过期删除。

---

## 可选改进（P2，不要求在此轮修）

以下问题已记录，不阻塞交付：

- A2/A3: `datetime.now()` 无时区信息
- A2: `rollback()` 非原子操作
- A3: `get_trend()` O(N*D) 性能（MVP 可接受）
- A3: events.jsonl 无文件锁（单进程场景可接受）
- A4: `mark_handled` 非原子文件重写
- A5: 多写了 `error_log.jsonl`（无害）
- A7: 深度报告同日覆盖风险
- A7: Scheduler 跨日窗口边界

---

## 验收标准

- [ ] FIX-1: backup_id 以 `backup_` 开头
- [ ] FIX-2: `compact()` 返回 `compressed_history` + `stats` 嵌套结构
- [ ] FIX-3: `lightweight_observe()` 返回 `patterns_noticed`、`suggestions`、`urgency`
- [ ] FIX-4: `detect()` 能生成 `capability_gap` 信号；`detect_patterns()` 至少有 `rule_unused` 框架
- [ ] FIX-5: `backup()` 目录创建失败时抛异常
- [ ] FIX-6: `cleanup()` 删除所有过期备份
- [ ] 全量测试通过（`python -m pytest tests/ -q`）
- [ ] 不引入新的 A 类模块间 import

---

## 参考文件

- 规格书: `docs/dev/codex-tasks/A2-rollback.md`, `A4-signals.md`, `A6-compaction.md`, `A7-observer.md`
- 接口定义: `docs/dev/mvp-module-plan.md`
- Codex 指南: `codex/CODEX-GUIDE.md`
