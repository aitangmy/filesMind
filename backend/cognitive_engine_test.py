import asyncio
import os
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch


sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cognitive_engine as ce  # noqa: E402


def _make_response(content: str):
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content))]
    )


class _FakeCompletions:
    def __init__(self, behaviors):
        self.behaviors = list(behaviors)
        self.calls = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        idx = len(self.calls) - 1
        behavior = self.behaviors[idx]
        if isinstance(behavior, Exception):
            raise behavior
        return behavior


class _FakeClient:
    def __init__(self, base_url: str, behaviors):
        self.base_url = base_url
        self.chat = SimpleNamespace(completions=_FakeCompletions(behaviors))


class RefineNodeTests(unittest.TestCase):
    def test_minimax_refine_does_not_send_response_format(self):
        fake_client = _FakeClient(
            "https://api.minimaxi.com/v1",
            [_make_response('[{"topic":"子点","details":[]}]')],
        )

        with patch.object(ce, "get_client", return_value=fake_client):
            with patch.object(ce, "get_model", return_value="MiniMax-M2.5"):
                data = asyncio.run(ce.refine_node_content("标题", "正文", "路径"))

        self.assertEqual(len(data), 1)
        first_call = fake_client.chat.completions.calls[0]
        self.assertNotIn("response_format", first_call)

    def test_refine_fallback_retries_without_response_format(self):
        error = Exception(
            "Error code: 400 - invalid params, binding: expr_path=response_format.type"
        )
        fake_client = _FakeClient(
            "https://api.openai.com/v1",
            [
                error,
                _make_response('{"items":[{"topic":"子点","details":["细节"]}]}'),
            ],
        )

        with patch.object(ce, "get_client", return_value=fake_client):
            with patch.object(ce, "get_model", return_value="gpt-4o-mini"):
                data = asyncio.run(ce.refine_node_content("标题", "正文", "路径"))

        self.assertEqual(len(fake_client.chat.completions.calls), 2)
        first_call = fake_client.chat.completions.calls[0]
        second_call = fake_client.chat.completions.calls[1]
        self.assertIn("response_format", first_call)
        self.assertNotIn("response_format", second_call)
        self.assertEqual(data[0]["topic"], "子点")

    def test_refine_response_sanitizes_noise_items(self):
        payload = """{
          "items": [
            {"topic": "Page 3", "details": ["3 / 20", "有效内容"]},
            {"topic": "核心概念", "details": ["仅供参考", "关键定义", "关键定义"]},
            {"topic": "2212", "details": []},
            {"topic": "it (InitialNode)", "details": ["https://example.com"]}
          ]
        }"""
        data = ce._parse_refine_response(payload, "测试章节")

        self.assertEqual(len(data), 1)
        topics = [item["topic"] for item in data]
        self.assertIn("核心概念", topics)
        core = next(item for item in data if item["topic"] == "核心概念")
        self.assertEqual(core["details"], ["关键定义"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
