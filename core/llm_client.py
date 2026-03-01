"""统一 LLM 客户端接口 — 多 Provider 注册表架构。

支持 anthropic 和 openai 兼容两种后端，通过配置动态路由。
"""

import json
import logging
import os
from abc import ABC, abstractmethod
from typing import Any

logger = logging.getLogger(__name__)


class BaseLLMClient(ABC):
    """LLM 客户端抽象基类。"""

    @abstractmethod
    async def complete(
        self,
        system_prompt: str,
        user_message: str,
        model: str = "opus",
        max_tokens: int = 2000,
    ) -> str:
        """
        调用 LLM 并返回文本响应。

        Args:
            system_prompt: 系统提示词
            user_message: 用户消息
            model: Provider 名称（如 "opus", "qwen"）
            max_tokens: 最大输出 token 数

        Returns:
            LLM 的文本响应

        Raises:
            不抛异常。超时或错误时返回空字符串并记录日志。
        """


# 默认 Provider 配置（无 YAML 时兜底）
_DEFAULT_PROVIDERS: dict[str, dict[str, Any]] = {
    "opus": {
        "type": "anthropic",
        "model_id": "claude-opus-4-6",
        "api_key_env": "ANTHROPIC_API_KEY",
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


class LLMClient(BaseLLMClient):
    """多 Provider LLM 客户端。

    通过 providers 注册表动态路由到不同后端：
    - type=anthropic: Anthropic SDK（Claude 系列）
    - type=openai: OpenAI 兼容接口（Qwen、MiniMax、DeepSeek 等）
    """

    def __init__(
        self,
        providers: dict[str, dict[str, Any]] | None = None,
        aliases: dict[str, str] | None = None,
    ):
        self._providers = providers or _DEFAULT_PROVIDERS
        self._aliases = aliases or _DEFAULT_ALIASES
        self._clients: dict[str, Any] = {}  # lazy-init cache

    def _resolve(self, model: str) -> tuple[str, dict]:
        """将 model 名解析为 (provider_name, config)，支持别名。"""
        name = self._aliases.get(model, model)
        if name not in self._providers:
            raise ValueError(f"Unknown LLM provider: {model!r}")
        return name, self._providers[name]

    def _get_client(self, name: str, config: dict):
        """获取或创建指定 provider 的客户端（懒初始化）。"""
        if name in self._clients:
            return self._clients[name]

        ptype = config.get("type", "openai")
        api_key = os.getenv(config.get("api_key_env", ""), "")
        base_url = config.get("base_url", "")

        if ptype == "anthropic":
            import anthropic
            kwargs = {"api_key": api_key}
            if base_url:
                kwargs["base_url"] = base_url
            client = anthropic.AsyncAnthropic(**kwargs)
        else:
            from openai import AsyncOpenAI
            kwargs = {"api_key": api_key}
            if base_url:
                kwargs["base_url"] = base_url
            client = AsyncOpenAI(**kwargs)

        self._clients[name] = client
        return client

    async def complete(
        self,
        system_prompt: str,
        user_message: str,
        model: str = "opus",
        max_tokens: int = 2000,
    ) -> str:
        try:
            name, config = self._resolve(model)
            client = self._get_client(name, config)
            model_id = config.get("model_id", model)

            if config.get("type") == "anthropic":
                return await self._call_anthropic(
                    client, model_id, system_prompt, user_message, max_tokens
                )
            else:
                extra_body = config.get("extra_body")
                return await self._call_openai(
                    client, model_id, system_prompt, user_message, max_tokens, extra_body
                )
        except Exception as e:
            logger.error(f"LLM call failed (model={model}): {e}")
            return ""

    @staticmethod
    async def _call_anthropic(client, model_id, system_prompt, user_message, max_tokens) -> str:
        """通过 Anthropic SDK 调用 Claude。"""
        response = await client.messages.create(
            model=model_id,
            max_tokens=max_tokens,
            system=system_prompt,
            messages=[{"role": "user", "content": user_message}],
        )
        if not response.content:
            raise ValueError("Anthropic API returned empty content")
        return response.content[0].text or ""

    @staticmethod
    async def _call_openai(client, model_id, system_prompt, user_message, max_tokens, extra_body=None) -> str:
        """通过 OpenAI 兼容接口调用。"""
        kwargs: dict[str, Any] = {
            "model": model_id,
            "max_tokens": max_tokens,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
        }
        if extra_body:
            kwargs["extra_body"] = extra_body
        response = await client.chat.completions.create(**kwargs)
        if not response.choices:
            raise ValueError("OpenAI-compatible API returned empty choices")
        return response.choices[0].message.content or ""


class MockLLMClient(BaseLLMClient):
    """测试用 Mock LLM 客户端。"""

    def __init__(self, responses: dict[str, str] | None = None):
        """
        Args:
            responses: 按 model 名返回预设响应。
                       例如 {"qwen": '{"type": "NONE"}', "opus": "分析结果..."}
                       也支持 "gemini-flash" key 以兼容旧代码。
        """
        self.responses = responses or {}
        self.calls: list[dict] = []

    async def complete(
        self,
        system_prompt: str,
        user_message: str,
        model: str = "qwen",
        max_tokens: int = 2000,
    ) -> str:
        self.calls.append({
            "system_prompt": system_prompt,
            "user_message": user_message,
            "model": model,
            "max_tokens": max_tokens,
        })
        if model in self.responses:
            return self.responses[model]
        # gemini-flash → qwen 兼容：如果请求 qwen 但只有 gemini-flash 的 response
        if model == "qwen" and "gemini-flash" in self.responses:
            return self.responses["gemini-flash"]
        if model == "gemini-flash" and "qwen" in self.responses:
            return self.responses["qwen"]
        # 默认返回一个合法的 JSON 反思输出
        return json.dumps({
            "type": "NONE",
            "outcome": "SUCCESS",
            "lesson": "mock response",
            "root_cause": None,
            "reusable_experience": None,
        })
