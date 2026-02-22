import asyncio
import os
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch


sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cognitive_engine as ce  # noqa: E402


def _make_response(content: str):
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])


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
        self.assertIn("extra_body", first_call)
        self.assertTrue(first_call["extra_body"].get("reasoning_split"))

    def test_refine_fallback_retries_without_response_format(self):
        error = Exception("Error code: 400 - invalid params, binding: expr_path=response_format.type")
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

    def test_refine_response_removes_table_separator_noise(self):
        payload = """{
          "items": [
            {"topic": "表格结构", "details": ["|------|------|", "有效细节"]},
            {"topic": "|-----|-----|", "details": ["无效"]}
          ]
        }"""
        data = ce._parse_refine_response(payload, "测试章节")

        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["topic"], "表格结构")
        self.assertEqual(data[0]["details"], ["有效细节"])

    def test_refine_response_extracts_json_after_think_block(self):
        payload = """<think>
内部推理内容
</think>
[{"topic":"统一过程","details":["迭代开发"]}]"""
        data = ce._parse_refine_response(payload, "测试章节")

        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["topic"], "统一过程")
        self.assertEqual(data[0]["details"], ["迭代开发"])

    def test_refine_response_extracts_json_from_mixed_text(self):
        payload = """模型解释：以下是结果
{
  "items": [
    {"topic": "RUP", "details": ["用例驱动"]}
  ]
}
谢谢。"""
        data = ce._parse_refine_response(payload, "测试章节")

        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["topic"], "RUP")

    def test_refine_low_confidence_adds_confidence_instruction(self):
        fake_client = _FakeClient(
            "https://api.openai.com/v1",
            [_make_response('{"items":[{"topic":"子点","details":["细节"]}]}')],
        )

        with patch.object(ce, "get_client", return_value=fake_client):
            with patch.object(ce, "get_model", return_value="gpt-4o-mini"):
                data = asyncio.run(
                    ce.refine_node_content(
                        "标题",
                        "正文",
                        "路径",
                        heading_confidence=0.2,
                    )
                )

        self.assertEqual(len(data), 1)
        first_call = fake_client.chat.completions.calls[0]
        system_text = first_call["messages"][0]["content"]
        self.assertIn("章节置信度", system_text)
        self.assertIn("返回空数组 []", system_text)


class EngineSettingsTests(unittest.TestCase):
    def setUp(self):
        self._old_engine = dict(ce._engine_settings)
        self._old_semaphore = ce._semaphore
        self._old_rate = ce._rate_limiter
        self._old_refresh = ce._limiter_needs_refresh
        self._old_model = ce.get_model()

    def tearDown(self):
        ce._engine_settings.update(self._old_engine)
        ce.set_model(self._old_model)
        ce._semaphore = self._old_semaphore
        ce._rate_limiter = self._old_rate
        ce._limiter_needs_refresh = self._old_refresh

    def test_update_client_config_clamps_advanced_values_and_marks_limiter_refresh(self):
        with patch.object(ce, "AsyncOpenAI", return_value=SimpleNamespace()):
            marker = object()
            ce._semaphore = marker
            ce._rate_limiter = marker
            ce._limiter_needs_refresh = False
            ce.update_client_config(
                {
                    "base_url": "https://api.deepseek.com",
                    "api_key": "dummy",
                    "model": "deepseek-chat",
                    "advanced": {
                        "engine_concurrency": 999,
                        "engine_temperature": -5,
                        "engine_max_tokens": 999999,
                    },
                }
            )

        self.assertEqual(ce._engine_settings["concurrency"], 10)
        self.assertEqual(ce._engine_settings["temperature"], 0.0)
        self.assertEqual(ce._engine_settings["max_tokens"], 16000)
        self.assertIs(ce._semaphore, marker)
        self.assertIs(ce._rate_limiter, marker)
        self.assertTrue(ce._limiter_needs_refresh)

    def test_set_model_marks_runtime_limiter_refresh_without_replacing_objects(self):
        marker = object()
        ce._semaphore = marker
        ce._rate_limiter = marker
        ce._limiter_needs_refresh = False

        ce.set_model("gpt-4o")

        self.assertEqual(ce.get_model(), "gpt-4o")
        self.assertIs(ce._semaphore, marker)
        self.assertIs(ce._rate_limiter, marker)
        self.assertTrue(ce._limiter_needs_refresh)

    def test_get_rate_limiter_reuses_gate_and_updates_limit_after_refresh(self):
        ce.cleanup()
        with patch.object(ce, "AsyncOpenAI", return_value=SimpleNamespace()):
            ce.update_client_config(
                {
                    "base_url": "https://api.deepseek.com",
                    "api_key": "dummy",
                    "model": "deepseek-chat",
                    "advanced": {
                        "engine_concurrency": 2,
                        "engine_temperature": 0.3,
                        "engine_max_tokens": 4096,
                    },
                }
            )
            semaphore1, limiter1 = ce.get_rate_limiter()
            self.assertIsInstance(semaphore1, ce.DynamicConcurrencyLimiter)
            self.assertEqual(semaphore1.get_limit(), 2)
            self.assertIsNone(limiter1)

            ce.update_client_config(
                {
                    "base_url": "https://api.deepseek.com",
                    "api_key": "dummy",
                    "model": "deepseek-chat",
                    "advanced": {
                        "engine_concurrency": 7,
                        "engine_temperature": 0.3,
                        "engine_max_tokens": 4096,
                    },
                }
            )
            semaphore2, limiter2 = ce.get_rate_limiter()
            self.assertIs(semaphore1, semaphore2)
            self.assertEqual(semaphore2.get_limit(), 7)
            self.assertIsNone(limiter2)


class RefineLimiterAndRetryTests(unittest.TestCase):
    def setUp(self):
        self._old_semaphore = ce._semaphore
        self._old_rate = ce._rate_limiter
        self._old_refresh = ce._limiter_needs_refresh
        self._old_model = ce.get_model()

    def tearDown(self):
        ce._semaphore = self._old_semaphore
        ce._rate_limiter = self._old_rate
        ce.set_model(self._old_model)
        ce._limiter_needs_refresh = self._old_refresh

    def test_refine_node_content_uses_rate_limiter(self):
        class _Limiter:
            def __init__(self):
                self.count = 0

            async def acquire(self):
                self.count += 1

        limiter = _Limiter()
        fake_client = _FakeClient(
            "https://api.minimaxi.com/v1",
            [_make_response('[{"topic":"Sub","details":[]}]')],
        )

        with patch.object(ce, "get_client", return_value=fake_client):
            with patch.object(ce, "get_model", return_value="MiniMax-M2.5"):
                with patch.object(ce, "get_rate_limiter", return_value=(asyncio.Semaphore(1), limiter)):
                    data = asyncio.run(ce.refine_node_content("Title", "Body", "Path"))

        self.assertEqual(len(data), 1)
        self.assertEqual(limiter.count, 1)

    def test_refine_node_content_raises_after_retry_exhausted(self):
        fake_client = _FakeClient(
            "https://api.minimaxi.com/v1",
            [
                Exception("429 Too Many Requests"),
                Exception("429 Too Many Requests"),
                Exception("429 Too Many Requests"),
                Exception("429 Too Many Requests"),
            ],
        )

        with patch.object(ce, "get_client", return_value=fake_client):
            with patch.object(ce, "get_model", return_value="MiniMax-M2.5"):
                with self.assertRaises(ce.RefineNodeRequestError):
                    asyncio.run(ce.refine_node_content("Title", "Body", "Path"))


class SanitizeBranchTests(unittest.TestCase):
    def test_snap_prefers_shallower_level_when_jitter_is_ambiguous(self):
        level_stack = [(0, 1), (3, 3), (5, 4)]
        snapped = ce._snap_orig_level_for_stack(4, level_stack, jitter_tolerance=1)
        self.assertEqual(snapped, 3)

    def test_numbering_resolution_prefers_sibling_level_over_parent_level(self):
        history = [
            {"sig": (1,), "level": 2},
            {"sig": (1, 1), "level": 5},
        ]

        level = ce._resolve_level_by_numbering((1, 3), history, fallback_level=3)
        self.assertEqual(level, 5)

    def test_sanitize_branch_aligns_numbered_siblings(self):
        branch = "\n".join(
            [
                "## 1.1 背景",
                "###### 1.2 发展阶段",
            ]
        )
        sanitized = ce.sanitize_branch(branch)
        lines = sanitized.split("\n")
        self.assertEqual(lines[0], "### 1.1 背景")
        self.assertEqual(lines[1], "### 1.2 发展阶段")

    def test_sanitize_branch_builds_parent_child_levels_by_numbering(self):
        branch = "\n".join(
            [
                "## 1. 概述",
                "## 1.1 背景",
                "## 1.1.1 定义",
            ]
        )
        sanitized = ce.sanitize_branch(branch)
        lines = sanitized.split("\n")
        self.assertEqual(lines[0], "## 1. 概述")
        self.assertEqual(lines[1], "### 1.1 背景")
        self.assertEqual(lines[2], "#### 1.1.1 定义")

    def test_sanitize_branch_removes_confidence_comments(self):
        branch = "## 2. 方法 <!-- FM-Confidence: 0.20 -->"
        sanitized = ce.sanitize_branch(branch)
        self.assertEqual(sanitized.strip(), "## 2. 方法")

    def test_sanitize_branch_prevents_staircase_on_repeated_noisy_headings(self):
        branch = "\n".join(
            [
                "## 1. 核心理论",
                "###### 假标题A",
                "###### 假标题B",
                "###### 假标题C",
            ]
        )
        sanitized = ce.sanitize_branch(branch)
        lines = sanitized.split("\n")
        self.assertEqual(lines[0], "## 1. 核心理论")
        self.assertEqual(lines[1], "### 假标题A")
        self.assertEqual(lines[2], "### 假标题B")
        self.assertEqual(lines[3], "### 假标题C")

    def test_sanitize_branch_handles_ocr_jitter_for_non_numbered_siblings(self):
        branch = "\n".join(
            [
                "## 1. 核心理论",
                "#### 假标题A",
                "##### 假标题B",
                "#### 假标题C",
            ]
        )
        sanitized = ce.sanitize_branch(branch)
        lines = sanitized.split("\n")
        self.assertEqual(lines[0], "## 1. 核心理论")
        self.assertEqual(lines[1], "### 假标题A")
        self.assertEqual(lines[2], "### 假标题B")
        self.assertEqual(lines[3], "### 假标题C")

    def test_sanitize_branch_keeps_shallow_context_after_deep_numbered_anchor(self):
        branch = "\n".join(
            [
                "## 1. 架构",
                "#### 无编号分组",
                "###### 1.1.1 深层锚点",
                "#### 分组B",
            ]
        )
        sanitized = ce.sanitize_branch(branch)
        lines = sanitized.split("\n")
        self.assertEqual(lines[0], "## 1. 架构")
        self.assertEqual(lines[1], "### 无编号分组")
        self.assertEqual(lines[2], "#### 1.1.1 深层锚点")
        self.assertEqual(lines[3], "### 分组B")


if __name__ == "__main__":
    unittest.main(verbosity=2)
