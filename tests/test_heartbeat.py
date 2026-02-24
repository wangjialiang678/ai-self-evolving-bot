"""HeartbeatService 测试。"""

import asyncio
from pathlib import Path

import pytest

from core.channels.heartbeat import HeartbeatService, _is_heartbeat_empty


# ──────────────────────────────────────
#  _is_heartbeat_empty 单元测试
# ──────────────────────────────────────


class TestIsHeartbeatEmpty:
    def test_none_is_empty(self):
        assert _is_heartbeat_empty(None) is True

    def test_empty_string_is_empty(self):
        assert _is_heartbeat_empty("") is True

    def test_only_headers_is_empty(self):
        assert _is_heartbeat_empty("# Title\n## Section\n") is True

    def test_only_html_comment_is_empty(self):
        assert _is_heartbeat_empty("<!-- comment -->") is True

    def test_only_empty_checkboxes_is_empty(self):
        content = "- [ ] \n* [ ] \n- [x] \n* [x] \n"
        assert _is_heartbeat_empty(content) is True

    def test_checkbox_with_label_is_empty(self):
        """勾选框后跟文字标签，仍视为空（无需 agent 行动）。"""
        content = "- [ ] pending task\n- [x] done task\n"
        assert _is_heartbeat_empty(content) is True

    def test_actionable_text_is_not_empty(self):
        assert _is_heartbeat_empty("Do something important\n") is False

    def test_mixed_with_actionable_is_not_empty(self):
        content = "# Tasks\n- [ ] unchecked\nPlease fix the bug\n"
        assert _is_heartbeat_empty(content) is False


# ──────────────────────────────────────
#  HeartbeatService 生命周期测试
# ──────────────────────────────────────


class TestHeartbeatLifecycle:
    @pytest.mark.asyncio
    async def test_is_running_false_before_start(self, tmp_path):
        svc = HeartbeatService(tmp_path, on_heartbeat=_noop, interval_s=9999)
        assert svc.is_running is False

    @pytest.mark.asyncio
    async def test_is_running_true_after_start(self, tmp_path):
        svc = HeartbeatService(tmp_path, on_heartbeat=_noop, interval_s=9999)
        await svc.start()
        try:
            assert svc.is_running is True
        finally:
            await svc.stop()

    @pytest.mark.asyncio
    async def test_is_running_false_after_stop(self, tmp_path):
        svc = HeartbeatService(tmp_path, on_heartbeat=_noop, interval_s=9999)
        await svc.start()
        await svc.stop()
        assert svc.is_running is False

    @pytest.mark.asyncio
    async def test_double_start_is_idempotent(self, tmp_path):
        svc = HeartbeatService(tmp_path, on_heartbeat=_noop, interval_s=9999)
        await svc.start()
        task_first = svc._task
        await svc.start()  # second start should be a no-op
        assert svc._task is task_first
        await svc.stop()

    @pytest.mark.asyncio
    async def test_stop_without_start_is_safe(self, tmp_path):
        svc = HeartbeatService(tmp_path, on_heartbeat=_noop, interval_s=9999)
        await svc.stop()  # should not raise
        assert svc.is_running is False


# ──────────────────────────────────────
#  回调触发测试
# ──────────────────────────────────────


class TestHeartbeatCallback:
    @pytest.mark.asyncio
    async def test_callback_triggered_when_heartbeat_file_exists(self, tmp_path):
        """HEARTBEAT.md 存在且有内容时，回调应被触发。"""
        received: list[str] = []

        async def capture(text: str) -> None:
            received.append(text)

        heartbeat_file = tmp_path / "HEARTBEAT.md"
        heartbeat_file.write_text("Fix the login bug\n", encoding="utf-8")

        svc = HeartbeatService(tmp_path, on_heartbeat=capture, interval_s=1)
        await svc.start()
        # Wait slightly longer than one interval
        await asyncio.sleep(1.1)
        await svc.stop()

        assert len(received) >= 1
        assert "Fix the login bug" in received[0]

    @pytest.mark.asyncio
    async def test_callback_not_triggered_when_file_missing(self, tmp_path):
        """HEARTBEAT.md 不存在时不应触发回调。"""
        received: list[str] = []

        async def capture(text: str) -> None:
            received.append(text)

        # Ensure no HEARTBEAT.md
        heartbeat_file = tmp_path / "HEARTBEAT.md"
        assert not heartbeat_file.exists()

        svc = HeartbeatService(tmp_path, on_heartbeat=capture, interval_s=1)
        await svc.start()
        await asyncio.sleep(1.1)
        await svc.stop()

        assert received == []

    @pytest.mark.asyncio
    async def test_callback_not_triggered_when_file_empty(self, tmp_path):
        """HEARTBEAT.md 为空时不应触发回调。"""
        received: list[str] = []

        async def capture(text: str) -> None:
            received.append(text)

        heartbeat_file = tmp_path / "HEARTBEAT.md"
        heartbeat_file.write_text("# Tasks\n- [ ] pending\n", encoding="utf-8")

        svc = HeartbeatService(tmp_path, on_heartbeat=capture, interval_s=1)
        await svc.start()
        await asyncio.sleep(1.1)
        await svc.stop()

        assert received == []

    @pytest.mark.asyncio
    async def test_callback_not_triggered_after_stop(self, tmp_path):
        """stop 后不应再触发回调。"""
        received: list[str] = []

        async def capture(text: str) -> None:
            received.append(text)

        heartbeat_file = tmp_path / "HEARTBEAT.md"
        heartbeat_file.write_text("Do something\n", encoding="utf-8")

        svc = HeartbeatService(tmp_path, on_heartbeat=capture, interval_s=1)
        await svc.start()
        await asyncio.sleep(1.1)
        await svc.stop()

        count_at_stop = len(received)

        # Wait another interval and verify count does not increase
        await asyncio.sleep(1.1)
        assert len(received) == count_at_stop


# ──────────────────────────────────────
#  interval 控制测试
# ──────────────────────────────────────


class TestHeartbeatInterval:
    @pytest.mark.asyncio
    async def test_interval_controls_tick_frequency(self, tmp_path):
        """短 interval 内触发多次，长 interval 内只触发少次。"""
        received: list[str] = []

        async def capture(text: str) -> None:
            received.append(text)

        heartbeat_file = tmp_path / "HEARTBEAT.md"
        heartbeat_file.write_text("Task\n", encoding="utf-8")

        # interval=1s, wait 3.2s → expect at least 3 ticks
        svc = HeartbeatService(tmp_path, on_heartbeat=capture, interval_s=1)
        await svc.start()
        await asyncio.sleep(3.2)
        await svc.stop()

        assert len(received) >= 3

    @pytest.mark.asyncio
    async def test_large_interval_does_not_tick_early(self, tmp_path):
        """interval 很大时，短时间内不应触发。"""
        received: list[str] = []

        async def capture(text: str) -> None:
            received.append(text)

        heartbeat_file = tmp_path / "HEARTBEAT.md"
        heartbeat_file.write_text("Task\n", encoding="utf-8")

        svc = HeartbeatService(tmp_path, on_heartbeat=capture, interval_s=9999)
        await svc.start()
        await asyncio.sleep(0.1)
        await svc.stop()

        assert received == []


# ──────────────────────────────────────
#  helpers
# ──────────────────────────────────────


async def _noop(text: str) -> None:
    """No-op heartbeat callback."""
