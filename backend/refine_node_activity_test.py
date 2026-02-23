import asyncio
import os
import sys
import unittest
from unittest.mock import MagicMock, patch


sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import activities.refine_node_activity as rna  # noqa: E402
from workflow_contracts.models import NodeStatus  # noqa: E402


class RefineNodeActivityTests(unittest.TestCase):
    def _make_payload(self, content: str, attempt: int = 1, max_attempts: int = 8):
        return rna.RefineNodeInput(
            doc_id="d1",
            node_id="n1",
            topic="Topic",
            content=content,
            breadcrumbs="A > B",
            model_profile="default",
            attempt=attempt,
            max_attempts=max_attempts,
        )

    def test_empty_details_on_refine_eligible_content_is_retryable_failed(self):
        repo = MagicMock()
        activity = rna.RefineNodeActivity(nodes_repo=repo)

        async def _empty_details(**_kwargs):
            return []

        payload = self._make_payload("这是一个可提炼节点内容，长度足够触发空结果失败机制。")
        with patch.dict(os.environ, {"FILESMIND_REFINE_MIN_CONTENT_CHARS": "10"}, clear=False):
            with patch.object(rna, "refine_node_content", side_effect=_empty_details):
                result = asyncio.run(activity.run(payload))

        self.assertEqual(result.status, NodeStatus.RETRYABLE_FAILED)
        repo.mark_node_retryable_failed.assert_called_once()
        repo.mark_node_success.assert_not_called()

    def test_empty_details_on_short_content_remains_success(self):
        repo = MagicMock()
        activity = rna.RefineNodeActivity(nodes_repo=repo)

        async def _empty_details(**_kwargs):
            return []

        payload = self._make_payload("简短")
        with patch.dict(os.environ, {"FILESMIND_REFINE_MIN_CONTENT_CHARS": "10"}, clear=False):
            with patch.object(rna, "refine_node_content", side_effect=_empty_details):
                result = asyncio.run(activity.run(payload))

        self.assertEqual(result.status, NodeStatus.SUCCESS)
        repo.mark_node_success.assert_called_once()
        repo.mark_node_retryable_failed.assert_not_called()


if __name__ == "__main__":
    unittest.main(verbosity=2)
