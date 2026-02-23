# 代码审核修复任务（已复核）

> **优先级**: P0
> **基于**: A1-A7 代码审核 + 人工复核
> **分支**: 在 `main` 上直接修复

---

## 审核代理误报说明

初次审核中发现的以下问题经人工复核确认为**误报**，代码已正确实现：

- ~~FIX-1: A2 backup_id 缺少 `backup_` 前缀~~ → 实际第 231 行已有前缀
- ~~FIX-2: A6 compact() 字段名不匹配~~ → 实际同时提供了 `compressed_history` 和 `stats` 嵌套结构（兼容写法）
- ~~FIX-4: A4 缺失 capability_gap / rule_unused~~ → 实际都已实现（第 75、171、177 行）
- ~~FIX-5: A2 backup() 静默返回~~ → 实际第 39 行已 `raise RuntimeError`
- ~~FIX-6: A2 cleanup() 不删 active 备份~~ → 实际没有跳过逻辑

**以下各模块审核通过，无需修改：A1、A2、A3、A4、A5、A6**

---

## 唯一需修复的问题

### FIX-3: A7 `lightweight_observe()` 返回值不符合规格

**文件**: `extensions/observer/engine.py`，`lightweight_observe` 方法（第 86-148 行）

**现状**: 返回日志记录结构：
```python
{
    "timestamp": "...",
    "task_id": "...",
    "outcome": "SUCCESS",
    "tokens": 3200,
    "model": "opus",
    "signals": [...],
    "error_type": None,
    "note": "正常完成"
}
```

**规格要求返回**:
```python
{
    "patterns_noticed": [...],   # 注意到的模式列表
    "suggestions": [...],        # 建议列表
    "urgency": "none"|"low"|"high"  # 紧急度
}
```

**修复方式**:

方案 A（推荐）：在现有 LLM 调用的 prompt 中要求返回 JSON，解析出三个字段：
```python
# 现有代码已调用 LLM（第 123-128 行），改 prompt 让它返回 JSON
# 解析出 patterns_noticed, suggestions, urgency
# 日志写入保留（内部副作用），但返回值换成规格格式
```

方案 B：基于 reflection_output 推导（无需额外 LLM 调用）：
```python
patterns = []
suggestions = []
urgency = "none"

if reflection_output:
    if reflection_output.get("type") == "ERROR":
        patterns.append(reflection_output.get("lesson", ""))
        suggestions.append(f"关注 root_cause: {reflection_output.get('root_cause')}")
        urgency = "high" if reflection_output.get("root_cause") == "wrong_assumption" else "low"
    elif reflection_output.get("type") == "PREFERENCE":
        patterns.append("用户偏好偏差")
        urgency = "low"

return {"patterns_noticed": patterns, "suggestions": suggestions, "urgency": urgency}
```

两种方案都可以。日志写入（第 146-147 行的 JSONL 追加）应保留作为内部行为。

**测试影响**: `tests/test_observer.py` 中 `lightweight_observe` 相关断言需改为验证 `patterns_noticed`、`suggestions`、`urgency` 字段。

---

## 验收标准

- [ ] `lightweight_observe()` 返回包含 `patterns_noticed`（list）、`suggestions`（list）、`urgency`（"none"|"low"|"high"）
- [ ] 日志写入行为保留（JSONL 文件继续追加）
- [ ] 全量测试通过（`python -m pytest tests/ -q`）
- [ ] 不引入新的 A 类模块间 import

---

## 可选改进（P2，不要求在此轮修）

以下问题已记录，不阻塞交付：

- A2: `rollback()` 非原子操作；路径遍历防护（`../` 可逃出 workspace）
- A2/A3: `datetime.now()` 无时区信息
- A3: `get_trend()` O(N*D) 性能（MVP 可接受）
- A3: events.jsonl 无文件锁（单进程场景可接受）
- A3: 缺少 `flush_daily(target_date=...)` 和 `PARTIAL` 状态的测试
- A4: `mark_handled` 非原子文件重写
- A5: 多写了 `error_log.jsonl`（无害兼容）
- A7: 深度报告同日覆盖风险
- A7: Scheduler 跨日窗口边界

---

## 参考文件

- 规格书: `docs/dev/codex-tasks/A7-observer.md`
- 接口定义: `docs/dev/mvp-module-plan.md`（第 530-560 行）
- Codex 指南: `codex/CODEX-GUIDE.md`
