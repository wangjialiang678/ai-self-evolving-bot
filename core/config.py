"""进化系统配置加载器。"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

# 默认 Provider 配置
_DEFAULT_PROVIDERS: dict[str, dict[str, Any]] = {
    "opus": {
        "type": "anthropic",
        "model_id": "claude-opus-4-6",
        "api_key_env": "PROXY_API_KEY",
        "base_url": "https://vtok.ai",
    },
    "qwen": {
        "type": "openai",
        "model_id": "qwen/qwen3-235b-a22b",
        "api_key_env": "NVIDIA_API_KEY",
        "base_url": "https://integrate.api.nvidia.com/v1",
        "extra_body": {"chat_template_kwargs": {"thinking": False}},
    },
}

_DEFAULT_ALIASES: dict[str, str] = {
    "gemini-flash": "qwen",
}

# 默认配置，当无 YAML 文件时使用
_DEFAULTS: dict[str, Any] = {
    "llm": {
        "providers": _DEFAULT_PROVIDERS,
        "aliases": _DEFAULT_ALIASES,
    },
    "agent_loop": {"model": "opus"},
    "observer": {
        "light_mode": {"enabled": True, "model": "qwen"},
        "deep_mode": {"schedule": "02:00", "model": "opus", "emergency_threshold": 3},
    },
    "architect": {"schedule": "03:00", "model": "opus", "max_daily_proposals": 3},
    "approval": {
        "levels": {
            0: {"action": "auto_execute", "notify": False, "max_files": 1},
            1: {"action": "execute_then_notify", "notify": True, "max_files": 3},
            2: {"action": "propose_then_wait", "notify": True, "max_files": 5},
            3: {"action": "discuss", "notify": True, "max_files": 999},
        }
    },
    "rollback": {"auto_threshold": 0.20, "backup_retention_days": 30},
    "blast_radius": {"level_0_max_files": 1, "level_1_max_files": 3},
    "rate_limit": {"max_daily_modifications": 5, "min_interval_hours": 2},
    "communication": {
        "quiet_hours_start": "22:00",
        "quiet_hours_end": "08:00",
        "daily_report": True,
        "daily_report_time": "08:30",
    },
    "evolution_strategy": {
        "initial": "cautious",
        "transitions": {
            "cautious_to_balanced": {"min_days": 7, "min_success_rate": 0.70},
            "balanced_to_growth": {"stale_days": 14, "min_success_rate": 0.80},
            "any_to_repair": {"success_drop": 0.20, "critical_threshold": 3},
            "repair_to_balanced": {"recovery_days": 2},
        },
    },
    "cron": {
        "observer_cron": "0 2 * * *",
        "architect_cron": "0 3 * * *",
        "briefing_cron": "30 8 * * *",
        "heartbeat_interval": 1800,
    },
}


class EvoConfig:
    """进化系统配置加载器。"""

    def __init__(self, config_path: str | Path | None = None):
        """从 YAML 文件加载配置，或使用默认值。

        Args:
            config_path: YAML 配置文件路径。None 时使用内置默认值。
        """
        self._data: dict[str, Any] = {}

        if config_path is not None:
            path = Path(config_path)
            if path.exists():
                try:
                    with path.open("r", encoding="utf-8") as f:
                        loaded = yaml.safe_load(f)
                    if isinstance(loaded, dict):
                        self._data = loaded
                    else:
                        logger.warning("Config file %s is not a dict, using defaults", path)
                        self._data = _deep_copy(_DEFAULTS)
                except Exception as exc:
                    logger.error("Failed to load config from %s: %s", path, exc)
                    self._data = _deep_copy(_DEFAULTS)
            else:
                logger.warning("Config file %s not found, using defaults", path)
                self._data = _deep_copy(_DEFAULTS)
        else:
            self._data = _deep_copy(_DEFAULTS)

    def get(self, key: str, default: Any = None) -> Any:
        """点分路径访问配置，如 'observer.deep_mode.schedule'。

        Args:
            key: 点分路径字符串
            default: 路径不存在时返回的默认值

        Returns:
            对应的配置值，不存在则返回 default
        """
        parts = key.split(".")
        current: Any = self._data
        for part in parts:
            if not isinstance(current, dict):
                return default
            if part not in current:
                return default
            current = current[part]
        return current

    # ── LLM Provider 配置 ──

    @property
    def providers(self) -> dict[str, dict[str, Any]]:
        """LLM Provider 注册表。"""
        return dict(self.get("llm.providers", _DEFAULT_PROVIDERS))

    @property
    def aliases(self) -> dict[str, str]:
        """模型名别名映射。"""
        return dict(self.get("llm.aliases", _DEFAULT_ALIASES))

    # ── 各组件模型选择 ──

    @property
    def agent_loop_model(self) -> str:
        """Agent Loop（Telegram 对话）使用的模型。"""
        return str(self.get("agent_loop.model", "opus"))

    @property
    def observer_light_model(self) -> str:
        """Observer 轻量模式使用的模型。"""
        return str(self.get("observer.light_mode.model", "qwen"))

    @property
    def observer_deep_model(self) -> str:
        """Observer 深度模式使用的模型。"""
        return str(self.get("observer.deep_mode.model", "opus"))

    @property
    def architect_model(self) -> str:
        """Architect 使用的模型。"""
        return str(self.get("architect.model", "opus"))

    # ── 调度配置 ──

    @property
    def observer_schedule(self) -> str:
        """Observer 深度分析定时时间（24h 格式 HH:MM）。"""
        return str(self.get("observer.deep_mode.schedule", "02:00"))

    @property
    def architect_schedule(self) -> str:
        """Architect 定时时间（24h 格式 HH:MM）。"""
        return str(self.get("architect.schedule", "03:00"))

    @property
    def quiet_hours(self) -> tuple[str, str]:
        """安静时段 (start, end)，格式 HH:MM。"""
        start = str(self.get("communication.quiet_hours_start", "22:00"))
        end = str(self.get("communication.quiet_hours_end", "08:00"))
        return (start, end)

    @property
    def evolution_strategy(self) -> str:
        """当前进化策略名称。"""
        return str(self.get("evolution_strategy.initial", "cautious"))

    @property
    def observer_cron(self) -> str:
        """Observer 深度分析 cron 表达式。"""
        return str(self.get("cron.observer_cron", "0 2 * * *"))

    @property
    def architect_cron(self) -> str:
        """Architect 分析 cron 表达式。"""
        return str(self.get("cron.architect_cron", "0 3 * * *"))

    @property
    def briefing_cron(self) -> str:
        """每日简报 cron 表达式。"""
        return str(self.get("cron.briefing_cron", "30 8 * * *"))

    @property
    def heartbeat_interval(self) -> int:
        """心跳检测间隔（秒）。"""
        return int(self.get("cron.heartbeat_interval", 1800))

    def get_approval_level_config(self, level: int) -> dict:
        """获取指定审批级别的配置。

        Args:
            level: 审批级别 (0-3)

        Returns:
            该级别的配置 dict，若不存在返回空 dict
        """
        levels = self.get("approval.levels", {})
        if not isinstance(levels, dict):
            return {}
        return dict(levels.get(level, {}))


def _deep_copy(data: Any) -> Any:
    """递归深复制字典/列表，避免默认值被修改。"""
    if isinstance(data, dict):
        return {k: _deep_copy(v) for k, v in data.items()}
    if isinstance(data, list):
        return [_deep_copy(v) for v in data]
    return data
