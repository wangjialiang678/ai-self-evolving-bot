"""Tests for EvoConfig configuration loader."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from core.config import EvoConfig


class TestEvoConfigLoad:
    def test_load_from_yaml(self, tmp_path):
        """从 YAML 文件加载配置。"""
        config_file = tmp_path / "evo_config.yaml"
        data = {
            "observer": {
                "deep_mode": {"schedule": "03:00", "model": "opus"},
            },
            "architect": {"schedule": "04:00"},
        }
        config_file.write_text(yaml.safe_dump(data), encoding="utf-8")

        cfg = EvoConfig(config_file)
        assert cfg.get("observer.deep_mode.schedule") == "03:00"
        assert cfg.get("architect.schedule") == "04:00"

    def test_default_config_no_file(self):
        """无文件时使用默认配置。"""
        cfg = EvoConfig()
        assert cfg.get("observer.deep_mode.schedule") == "02:00"
        assert cfg.get("architect.schedule") == "03:00"
        assert cfg.get("evolution_strategy.initial") == "cautious"

    def test_default_config_missing_path(self, tmp_path):
        """路径不存在时回退到默认配置。"""
        cfg = EvoConfig(tmp_path / "nonexistent.yaml")
        assert cfg.get("observer.deep_mode.schedule") == "02:00"

    def test_load_real_workspace_config(self):
        """加载项目 workspace/evo_config.yaml（若存在）。"""
        workspace_cfg = Path(__file__).parent.parent / "workspace" / "evo_config.yaml"
        if not workspace_cfg.exists():
            pytest.skip("workspace/evo_config.yaml not found")
        cfg = EvoConfig(workspace_cfg)
        assert cfg.observer_schedule == "02:00"
        assert cfg.architect_schedule == "03:00"


class TestEvoConfigGet:
    def test_dot_path_access(self, tmp_path):
        """点分路径访问嵌套配置。"""
        config_file = tmp_path / "cfg.yaml"
        config_file.write_text(
            yaml.safe_dump({"a": {"b": {"c": "deep_value"}}}),
            encoding="utf-8",
        )
        cfg = EvoConfig(config_file)
        assert cfg.get("a.b.c") == "deep_value"

    def test_missing_key_returns_default(self):
        """不存在的 key 返回 default。"""
        cfg = EvoConfig()
        assert cfg.get("nonexistent.key") is None
        assert cfg.get("nonexistent.key", "fallback") == "fallback"

    def test_partial_path_returns_dict(self):
        """中间路径返回子 dict。"""
        cfg = EvoConfig()
        result = cfg.get("observer.light_mode")
        assert isinstance(result, dict)
        assert result.get("enabled") is True

    def test_top_level_key(self):
        """访问顶层 key。"""
        cfg = EvoConfig()
        result = cfg.get("rollback")
        assert isinstance(result, dict)
        assert result["auto_threshold"] == pytest.approx(0.20)

    def test_missing_intermediate_returns_default(self):
        """中间节点不存在时返回 default。"""
        cfg = EvoConfig()
        assert cfg.get("observer.nonexistent.key", 42) == 42


class TestEvoConfigProperties:
    def test_observer_schedule(self):
        """observer_schedule 返回正确时间字符串。"""
        cfg = EvoConfig()
        assert cfg.observer_schedule == "02:00"

    def test_architect_schedule(self):
        """architect_schedule 返回正确时间字符串。"""
        cfg = EvoConfig()
        assert cfg.architect_schedule == "03:00"

    def test_quiet_hours(self):
        """quiet_hours 返回 (start, end) 元组。"""
        cfg = EvoConfig()
        start, end = cfg.quiet_hours
        assert start == "22:00"
        assert end == "08:00"

    def test_evolution_strategy(self):
        """evolution_strategy 返回策略名称字符串。"""
        cfg = EvoConfig()
        assert cfg.evolution_strategy == "cautious"

    def test_properties_from_yaml(self, tmp_path):
        """properties 从 YAML 读取正确覆盖默认值。"""
        config_file = tmp_path / "cfg.yaml"
        data = {
            "observer": {"deep_mode": {"schedule": "01:30"}},
            "architect": {"schedule": "02:30"},
            "communication": {
                "quiet_hours_start": "23:00",
                "quiet_hours_end": "07:00",
            },
            "evolution_strategy": {"initial": "balanced"},
        }
        config_file.write_text(yaml.safe_dump(data), encoding="utf-8")
        cfg = EvoConfig(config_file)

        assert cfg.observer_schedule == "01:30"
        assert cfg.architect_schedule == "02:30"
        assert cfg.quiet_hours == ("23:00", "07:00")
        assert cfg.evolution_strategy == "balanced"


class TestEvoConfigApprovalLevels:
    def test_level_0(self):
        """级别 0: auto_execute, not notify, max_files=1。"""
        cfg = EvoConfig()
        level_cfg = cfg.get_approval_level_config(0)
        assert level_cfg["action"] == "auto_execute"
        assert level_cfg["notify"] is False
        assert level_cfg["max_files"] == 1

    def test_level_1(self):
        """级别 1: execute_then_notify, notify=True, max_files=3。"""
        cfg = EvoConfig()
        level_cfg = cfg.get_approval_level_config(1)
        assert level_cfg["action"] == "execute_then_notify"
        assert level_cfg["notify"] is True
        assert level_cfg["max_files"] == 3

    def test_level_2(self):
        """级别 2: propose_then_wait, notify=True, max_files=5。"""
        cfg = EvoConfig()
        level_cfg = cfg.get_approval_level_config(2)
        assert level_cfg["action"] == "propose_then_wait"
        assert level_cfg["notify"] is True
        assert level_cfg["max_files"] == 5

    def test_level_3(self):
        """级别 3: discuss, notify=True, max_files=999。"""
        cfg = EvoConfig()
        level_cfg = cfg.get_approval_level_config(3)
        assert level_cfg["action"] == "discuss"
        assert level_cfg["notify"] is True
        assert level_cfg["max_files"] == 999

    def test_nonexistent_level_returns_empty(self):
        """不存在的级别返回空 dict。"""
        cfg = EvoConfig()
        assert cfg.get_approval_level_config(99) == {}

    def test_returns_copy_not_reference(self):
        """返回值是独立副本，不影响内部状态。"""
        cfg = EvoConfig()
        level_cfg = cfg.get_approval_level_config(0)
        level_cfg["action"] = "mutated"
        # 内部状态不应被修改
        assert cfg.get_approval_level_config(0)["action"] == "auto_execute"


class TestEvoConfigIsolation:
    def test_two_instances_independent(self):
        """两个实例互不影响。"""
        cfg1 = EvoConfig()
        cfg2 = EvoConfig()
        # 修改不同实例的底层数据不应影响另一个
        cfg1._data["evolution_strategy"]["initial"] = "repair"
        assert cfg2.evolution_strategy == "cautious"
