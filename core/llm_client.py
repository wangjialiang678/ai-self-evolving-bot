"""统一 LLM 客户端接口 — 封装 Claude Opus 和 Gemini Flash。"""

import json
import logging
from abc import ABC, abstractmethod

logger = logging.getLogger(__name__)


class BaseLLMClient(ABC):
    """LLM 客户端抽象基类。"""

    @abstractmethod
    async def complete(
        self,
        system_prompt: str,
        user_message: str,
        model: str = "gemini-flash",
        max_tokens: int = 2000,
    ) -> str:
        """
        调用 LLM 并返回文本响应。

        Args:
            system_prompt: 系统提示词
            user_message: 用户消息
            model: 模型标识 ("opus" | "gemini-flash")
            max_tokens: 最大输出 token 数

        Returns:
            LLM 的文本响应

        Raises:
            不抛异常。超时或错误时返回空字符串并记录日志。
        """


class LLMClient(BaseLLMClient):
    """真实 LLM 客户端，支持 Claude Opus + Gemini Flash。"""

    def __init__(self, anthropic_key: str | None = None, google_key: str | None = None):
        self.anthropic_key = anthropic_key
        self.google_key = google_key
        self._anthropic_client = None
        self._google_client = None

    def _get_anthropic(self):
        if self._anthropic_client is None:
            import anthropic
            self._anthropic_client = anthropic.AsyncAnthropic(api_key=self.anthropic_key)
        return self._anthropic_client

    def _get_google(self):
        if self._google_client is None:
            from google import genai
            self._google_client = genai.Client(api_key=self.google_key)
        return self._google_client

    async def complete(
        self,
        system_prompt: str,
        user_message: str,
        model: str = "gemini-flash",
        max_tokens: int = 2000,
    ) -> str:
        try:
            if model == "opus":
                return await self._call_anthropic(system_prompt, user_message, max_tokens)
            else:
                return await self._call_gemini(system_prompt, user_message, model, max_tokens)
        except Exception as e:
            logger.error(f"LLM call failed (model={model}): {e}")
            return ""

    async def _call_anthropic(self, system_prompt: str, user_message: str, max_tokens: int) -> str:
        client = self._get_anthropic()
        response = await client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=max_tokens,
            system=system_prompt,
            messages=[{"role": "user", "content": user_message}],
        )
        return response.content[0].text

    async def _call_gemini(self, system_prompt: str, user_message: str, model: str, max_tokens: int) -> str:
        client = self._get_google()
        model_name = "gemini-2.0-flash" if "flash" in model else "gemini-2.0-pro"
        response = await client.aio.models.generate_content(
            model=model_name,
            contents=f"{system_prompt}\n\n{user_message}",
            config={"max_output_tokens": max_tokens},
        )
        return response.text


class MockLLMClient(BaseLLMClient):
    """测试用 Mock LLM 客户端。"""

    def __init__(self, responses: dict[str, str] | None = None):
        """
        Args:
            responses: 按 model 名返回预设响应。
                       例如 {"gemini-flash": '{"type": "NONE"}', "opus": "分析结果..."}
        """
        self.responses = responses or {}
        self.calls: list[dict] = []

    async def complete(
        self,
        system_prompt: str,
        user_message: str,
        model: str = "gemini-flash",
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
        # 默认返回一个合法的 JSON 反思输出
        return json.dumps({
            "type": "NONE",
            "outcome": "SUCCESS",
            "lesson": "mock response",
            "root_cause": None,
            "reusable_experience": None,
        })
