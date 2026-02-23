"""统一 LLM 客户端接口 — 封装 Claude Opus (vtok.ai 代理) + Qwen 3.5 (NVIDIA)。"""

import json
import logging
import os
from abc import ABC, abstractmethod

logger = logging.getLogger(__name__)


class BaseLLMClient(ABC):
    """LLM 客户端抽象基类。"""

    @abstractmethod
    async def complete(
        self,
        system_prompt: str,
        user_message: str,
        model: str = "qwen",
        max_tokens: int = 2000,
    ) -> str:
        """
        调用 LLM 并返回文本响应。

        Args:
            system_prompt: 系统提示词
            user_message: 用户消息
            model: 模型标识 ("opus" | "qwen")
            max_tokens: 最大输出 token 数

        Returns:
            LLM 的文本响应

        Raises:
            不抛异常。超时或错误时返回空字符串并记录日志。
        """


class LLMClient(BaseLLMClient):
    """真实 LLM 客户端。

    - Claude Opus/Sonnet: 通过 vtok.ai 中转站（Anthropic SDK + base_url）
    - Qwen 3.5: 通过 NVIDIA 平台（OpenAI 兼容接口）
    """

    # 模型 ID 映射
    OPUS_MODEL = "claude-sonnet-4-20250514"
    QWEN_MODEL = "qwen/qwen3-235b-a22b"  # NVIDIA 平台上的 Qwen 3.5

    def __init__(
        self,
        proxy_api_key: str | None = None,
        proxy_base_url: str | None = None,
        nvidia_api_key: str | None = None,
    ):
        self.proxy_api_key = proxy_api_key or os.getenv("PROXY_API_KEY")
        self.proxy_base_url = proxy_base_url or os.getenv("PROXY_BASE_URL", "https://vtok.ai")
        self.nvidia_api_key = nvidia_api_key or os.getenv("NVIDIA_API_KEY")
        self._anthropic_client = None
        self._nvidia_client = None

    def _get_anthropic(self):
        """获取 Anthropic 客户端（通过 vtok.ai 代理）。"""
        if self._anthropic_client is None:
            import anthropic
            self._anthropic_client = anthropic.AsyncAnthropic(
                api_key=self.proxy_api_key,
                base_url=self.proxy_base_url,
            )
        return self._anthropic_client

    def _get_nvidia(self):
        """获取 NVIDIA OpenAI 兼容客户端（用于 Qwen 3.5）。"""
        if self._nvidia_client is None:
            from openai import AsyncOpenAI
            self._nvidia_client = AsyncOpenAI(
                api_key=self.nvidia_api_key,
                base_url="https://integrate.api.nvidia.com/v1",
            )
        return self._nvidia_client

    async def complete(
        self,
        system_prompt: str,
        user_message: str,
        model: str = "qwen",
        max_tokens: int = 2000,
    ) -> str:
        try:
            if model == "opus":
                return await self._call_opus(system_prompt, user_message, max_tokens)
            elif model in ("qwen", "gemini-flash"):
                # qwen 替代 gemini-flash 做辅助/低成本任务
                return await self._call_qwen(system_prompt, user_message, max_tokens)
            else:
                logger.warning(f"Unknown model '{model}', falling back to qwen")
                return await self._call_qwen(system_prompt, user_message, max_tokens)
        except Exception as e:
            logger.error(f"LLM call failed (model={model}): {e}")
            return ""

    async def _call_opus(self, system_prompt: str, user_message: str, max_tokens: int) -> str:
        """通过 vtok.ai 代理调用 Claude。"""
        client = self._get_anthropic()
        response = await client.messages.create(
            model=self.OPUS_MODEL,
            max_tokens=max_tokens,
            system=system_prompt,
            messages=[{"role": "user", "content": user_message}],
        )
        return response.content[0].text

    async def _call_qwen(self, system_prompt: str, user_message: str, max_tokens: int) -> str:
        """通过 NVIDIA 平台调用 Qwen 3.5。"""
        client = self._get_nvidia()
        response = await client.chat.completions.create(
            model=self.QWEN_MODEL,
            max_tokens=max_tokens,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
        )
        return response.choices[0].message.content


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
