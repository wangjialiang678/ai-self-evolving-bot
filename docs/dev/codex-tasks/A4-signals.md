# 任务 A4：信号系统

> **优先级**: P1（Observer 和 Architect 依赖信号数据）
> **预计工作量**: 2-3 天
> **类型**: Python 模块开发

---

## 项目背景

你在参与一个「自进化 AI 智能体系统」的开发。系统通过「信号」连接日常运行和系统进化——每次任务完成后，反思引擎提取教训，信号检测器从中识别值得进化系统关注的模式。

信号是 Observer 和 Architect 的输入源。没有信号系统，进化就没有数据驱动的依据。

详细背景见 `docs/design/v3-2-system-design.md` 第 5.6 节

---

## 你要做什么

实现两个类：
1. `SignalStore` — 信号的持久化存储（JSONL 读写）
2. `SignalDetector` — 从反思输出和任务上下文中检测信号

---

## 接口定义

```python
# extensions/signals/store.py

class SignalStore:
    """信号持久化存储，使用 JSONL 文件。"""

    def __init__(self, signals_dir: str):
        """
        Args:
            signals_dir: workspace/signals/ 目录路径
            内含 active.jsonl 和 archive.jsonl
        """

    def add(self, signal: dict):
        """
        写入一条信号到 active.jsonl。

        signal 格式：
        {"signal_id": "sig_001", "signal_type": "user_correction",
         "priority": "MEDIUM", "source": "reflection:task_042",
         "description": "...", "related_tasks": ["task_042"],
         "timestamp": "2026-02-25T10:16:00", "status": "active"}

        自动生成 signal_id（如果未提供）。
        自动添加 timestamp（如果未提供）。
        """

    def get_active(self, priority: str | None = None,
                   signal_type: str | None = None) -> list[dict]:
        """
        获取未处理的信号。

        Args:
            priority: 按优先级过滤（"LOW"|"MEDIUM"|"HIGH"|"CRITICAL"）
            signal_type: 按类型过滤

        Returns:
            匹配的信号列表，按时间倒序。
        """

    def mark_handled(self, signal_ids: list[str], handler: str):
        """
        标记信号为已处理。

        行为：
        - 从 active.jsonl 中移除匹配的信号
        - 追加到 archive.jsonl，加上 handler 和 handled_at 字段
        """

    def count_recent(self, signal_type: str | None = None,
                     priority: str | None = None,
                     hours: int = 24) -> int:
        """
        统计最近 N 小时内的信号数量。

        只统计 active 中的信号。
        """
```

```python
# extensions/signals/detector.py

class SignalDetector:
    """从反思输出和任务上下文中检测信号。"""

    def __init__(self, signal_store: SignalStore):
        pass

    def detect(self, reflection_output: dict, task_context: dict) -> list[dict]:
        """
        从单次反思输出中检测信号。

        Args:
            reflection_output:
                {"task_id": "task_042", "type": "ERROR"|"PREFERENCE"|"NONE",
                 "outcome": "SUCCESS"|"PARTIAL"|"FAILURE",
                 "lesson": "...", "root_cause": "..."|None}

            task_context:
                {"tokens_used": 3200, "model": "opus", "duration_ms": 15000,
                 "user_corrections": 1, "task_type": "analysis"}

        Returns:
            检测到的信号列表（已自动写入 store）。

        检测规则：
        1. user_corrections > 0 → user_correction (MEDIUM)
        2. type == "ERROR" 且 outcome == "FAILURE" → task_failure (HIGH)
        3. type == "NONE" 且 outcome == "SUCCESS" → 检查是否有规则被使用，
           是则 rule_validated (LOW)
        4. tokens_used > 10000 → efficiency_opportunity (LOW)
        """

    def detect_patterns(self, lookback_hours: int = 168) -> list[dict]:
        """
        从历史信号中检测跨任务模式。

        Args:
            lookback_hours: 回看时间窗口，默认 7 天（168 小时）

        Returns:
            检测到的模式信号列表。

        检测规则：
        1. 同类 task_failure 在 lookback 内 ≥ 2 次 → repeated_error (HIGH)
        2. 从 task 事件统计：3 天成功率下降 >15% → performance_degradation (CRITICAL)
           （注意：此规则需要读取 metrics/events.jsonl，如果不可用则跳过）
        3. user_pattern 类型信号在 lookback 内 ≥ 3 次 → 提升为 MEDIUM
        """
```

---

## 信号类型定义

| 信号类型 | 触发条件 | 默认优先级 | 分类 |
|---------|---------|:--------:|:----:|
| `user_correction` | 用户纠正了系统输出 | MEDIUM | 错误 |
| `task_failure` | 任务执行失败 | HIGH | 错误 |
| `repeated_error` | 同类错误 7天内 ≥2 次 | HIGH | 错误 |
| `performance_degradation` | 3天成功率下降 >15% | CRITICAL | 元信号 |
| `rule_unused` | 规则 14天未触发 | LOW | 机会 |
| `capability_gap` | 任务因能力不足失败 | MEDIUM | 机会 |
| `efficiency_opportunity` | token 消耗异常高 | LOW | 机会 |
| `user_pattern` | 用户行为重复出现 | MEDIUM | 机会 |
| `rule_validated` | 规则被使用且效果良好 | LOW | 机会 |

---

## 技术约束

- Python 3.11+
- 只使用标准库（json, pathlib, datetime, logging, uuid）
- JSONL 读写：每行一个 JSON，追加写入
- 读取 JSONL 时容忍空行和格式错误行
- mark_handled 需要重写 active.jsonl（读取全部→过滤→重写）
- signal_id 自动生成格式：`sig_{uuid4 前 8 位}`
- 时间戳格式：ISO 8601

---

## 测试要求

```python
# tests/test_signals.py

import pytest
import json
from datetime import datetime, timedelta

# from extensions.signals.store import SignalStore
# from extensions.signals.detector import SignalDetector


class TestSignalStore:
    def test_add_and_get(self, tmp_path):
        """添加信号后能读取。"""
        signals_dir = _setup_signals(tmp_path)
        store = SignalStore(str(signals_dir))

        store.add({
            "signal_type": "user_correction",
            "priority": "MEDIUM",
            "source": "reflection:task_042",
            "description": "用户纠正",
            "related_tasks": ["task_042"],
        })

        active = store.get_active()
        assert len(active) == 1
        assert active[0]["signal_type"] == "user_correction"
        assert "signal_id" in active[0]  # 自动生成
        assert "timestamp" in active[0]  # 自动生成

    def test_filter_by_priority(self, tmp_path):
        """按优先级过滤。"""
        signals_dir = _setup_signals(tmp_path)
        store = SignalStore(str(signals_dir))

        store.add({"signal_type": "user_correction", "priority": "MEDIUM",
                    "source": "s1", "description": "d1", "related_tasks": []})
        store.add({"signal_type": "task_failure", "priority": "HIGH",
                    "source": "s2", "description": "d2", "related_tasks": []})

        medium = store.get_active(priority="MEDIUM")
        assert len(medium) == 1
        assert medium[0]["signal_type"] == "user_correction"

    def test_filter_by_type(self, tmp_path):
        """按类型过滤。"""
        signals_dir = _setup_signals(tmp_path)
        store = SignalStore(str(signals_dir))

        store.add({"signal_type": "user_correction", "priority": "MEDIUM",
                    "source": "s1", "description": "d1", "related_tasks": []})
        store.add({"signal_type": "task_failure", "priority": "HIGH",
                    "source": "s2", "description": "d2", "related_tasks": []})

        failures = store.get_active(signal_type="task_failure")
        assert len(failures) == 1

    def test_mark_handled(self, tmp_path):
        """标记处理后从 active 移到 archive。"""
        signals_dir = _setup_signals(tmp_path)
        store = SignalStore(str(signals_dir))

        store.add({"signal_type": "user_correction", "priority": "MEDIUM",
                    "source": "s1", "description": "d1", "related_tasks": []})

        active = store.get_active()
        signal_id = active[0]["signal_id"]

        store.mark_handled([signal_id], handler="architect")

        assert len(store.get_active()) == 0

        # 验证写入 archive
        archive = (signals_dir / "archive.jsonl").read_text().strip()
        assert signal_id in archive

    def test_count_recent(self, tmp_path):
        """统计最近时间窗口内的信号。"""
        signals_dir = _setup_signals(tmp_path)
        store = SignalStore(str(signals_dir))

        store.add({"signal_type": "user_correction", "priority": "MEDIUM",
                    "source": "s1", "description": "d1", "related_tasks": []})
        store.add({"signal_type": "user_correction", "priority": "MEDIUM",
                    "source": "s2", "description": "d2", "related_tasks": []})

        count = store.count_recent(signal_type="user_correction", hours=1)
        assert count == 2


class TestSignalDetector:
    def test_detect_user_correction(self, tmp_path):
        """用户纠正触发 user_correction 信号。"""
        signals_dir = _setup_signals(tmp_path)
        store = SignalStore(str(signals_dir))
        detector = SignalDetector(store)

        reflection = {
            "task_id": "task_042", "type": "PREFERENCE",
            "outcome": "PARTIAL", "lesson": "用户要简短",
            "root_cause": None,
        }
        context = {"tokens_used": 3200, "model": "opus",
                   "duration_ms": 15000, "user_corrections": 1}

        signals = detector.detect(reflection, context)
        assert any(s["signal_type"] == "user_correction" for s in signals)

    def test_detect_task_failure(self, tmp_path):
        """ERROR + FAILURE 触发 task_failure。"""
        signals_dir = _setup_signals(tmp_path)
        store = SignalStore(str(signals_dir))
        detector = SignalDetector(store)

        reflection = {
            "task_id": "task_035", "type": "ERROR",
            "outcome": "FAILURE", "lesson": "错误假设",
            "root_cause": "wrong_assumption",
        }
        context = {"tokens_used": 2000, "model": "opus",
                   "duration_ms": 10000, "user_corrections": 0}

        signals = detector.detect(reflection, context)
        assert any(s["signal_type"] == "task_failure" for s in signals)
        assert any(s["priority"] == "HIGH" for s in signals)

    def test_detect_efficiency_opportunity(self, tmp_path):
        """高 token 消耗触发 efficiency_opportunity。"""
        signals_dir = _setup_signals(tmp_path)
        store = SignalStore(str(signals_dir))
        detector = SignalDetector(store)

        reflection = {
            "task_id": "task_050", "type": "NONE",
            "outcome": "SUCCESS", "lesson": "正常完成",
            "root_cause": None,
        }
        context = {"tokens_used": 15000, "model": "opus",
                   "duration_ms": 30000, "user_corrections": 0}

        signals = detector.detect(reflection, context)
        assert any(s["signal_type"] == "efficiency_opportunity" for s in signals)

    def test_no_signal_on_clean_success(self, tmp_path):
        """正常成功且 token 正常时不生成高优先级信号。"""
        signals_dir = _setup_signals(tmp_path)
        store = SignalStore(str(signals_dir))
        detector = SignalDetector(store)

        reflection = {
            "task_id": "task_060", "type": "NONE",
            "outcome": "SUCCESS", "lesson": "正常",
            "root_cause": None,
        }
        context = {"tokens_used": 2000, "model": "opus",
                   "duration_ms": 5000, "user_corrections": 0}

        signals = detector.detect(reflection, context)
        high_signals = [s for s in signals if s["priority"] in ("HIGH", "CRITICAL")]
        assert len(high_signals) == 0

    def test_detect_repeated_error(self, tmp_path):
        """7天内同类错误 ≥2 次触发 repeated_error。"""
        signals_dir = _setup_signals(tmp_path)
        store = SignalStore(str(signals_dir))
        detector = SignalDetector(store)

        # 先添加一个历史 task_failure
        store.add({"signal_type": "task_failure", "priority": "HIGH",
                    "source": "reflection:task_030", "description": "错误假设",
                    "related_tasks": ["task_030"]})

        # 再检测第二个失败
        reflection = {
            "task_id": "task_035", "type": "ERROR",
            "outcome": "FAILURE", "lesson": "错误假设",
            "root_cause": "wrong_assumption",
        }
        context = {"tokens_used": 2000, "model": "opus",
                   "duration_ms": 10000, "user_corrections": 0}

        # detect 后调用 detect_patterns
        detector.detect(reflection, context)
        patterns = detector.detect_patterns(lookback_hours=168)
        assert any(s["signal_type"] == "repeated_error" for s in patterns)


def _setup_signals(tmp_path):
    signals_dir = tmp_path / "signals"
    signals_dir.mkdir()
    (signals_dir / "active.jsonl").touch()
    (signals_dir / "archive.jsonl").touch()
    return signals_dir
```

---

## 交付物

```
extensions/signals/store.py
extensions/signals/detector.py
extensions/signals/__init__.py   # 空文件（如不存在）
tests/test_signals.py
```

---

## 验收标准

- [ ] SignalStore 的 JSONL 读写正确
- [ ] add() 自动生成 signal_id 和 timestamp
- [ ] get_active() 支持按 priority 和 signal_type 过滤
- [ ] mark_handled 正确将信号从 active 移到 archive
- [ ] count_recent 正确统计时间窗口内的信号
- [ ] SignalDetector.detect() 根据规则表正确检测信号
- [ ] detect_patterns() 能检测 repeated_error（7天内同类 ≥2）
- [ ] 检测到的信号自动写入 store
- [ ] 以上测试全部通过

---

## 参考文档

- 信号系统：`docs/design/v3-2-system-design.md` 第 5.6 节
- 模块计划：`docs/dev/mvp-module-plan.md` A4 节
- 接口规范：`docs/dev/mvp-dev-guide.md` 第 2 节（接口 I2、I3）
