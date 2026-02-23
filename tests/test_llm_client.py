"""测试 LLM 客户端（Mock）。"""

import json
import pytest
from core.llm_client import MockLLMClient


class TestMockLLMClient:
    @pytest.mark.asyncio
    async def test_default_response(self):
        """默认返回合法 JSON。"""
        client = MockLLMClient()
        result = await client.complete("system", "hello")
        data = json.loads(result)
        assert data["type"] == "NONE"
        assert data["outcome"] == "SUCCESS"

    @pytest.mark.asyncio
    async def test_custom_response(self):
        """按 model 返回预设响应。"""
        client = MockLLMClient(responses={
            "opus": "这是 Opus 的回答",
            "gemini-flash": '{"type": "ERROR"}',
        })

        opus_result = await client.complete("sys", "msg", model="opus")
        assert opus_result == "这是 Opus 的回答"

        gemini_result = await client.complete("sys", "msg", model="gemini-flash")
        assert json.loads(gemini_result)["type"] == "ERROR"

    @pytest.mark.asyncio
    async def test_records_calls(self):
        """记录所有调用。"""
        client = MockLLMClient()
        await client.complete("sys1", "msg1", model="opus")
        await client.complete("sys2", "msg2", model="gemini-flash")

        assert len(client.calls) == 2
        assert client.calls[0]["model"] == "opus"
        assert client.calls[1]["model"] == "gemini-flash"
