import os
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import parser_service as ps  # noqa: E402

try:
    from docling_core.types.doc.document import ContentLayer, DocItemLabel

    _HAS_DOCLING_CORE = True
except Exception:
    ContentLayer = None
    DocItemLabel = None
    _HAS_DOCLING_CORE = False


def _score_payload(score: float, total: int = 10, valid: int = 8, levels=None):
    if levels is None:
        levels = [1, 2, 3]
    return {
        "score": score,
        "valid_heading_ratio": round(valid / max(total, 1), 3),
        "total_headings": total,
        "valid_headings": valid,
        "heading_levels": levels,
        "text_length": 5000,
        "chars_per_heading": 625.0,
        "content_lines": 60,
        "content_per_heading": 7.5,
        "signals": {
            "density_band": "ideal",
            "depth_band": "deep",
            "content_band": "rich",
        },
        "breakdown": {
            "valid": 24.0,
            "density": 25.0,
            "depth": 25.0,
            "content": 20.0,
        },
    }


def _runtime_config(**overrides):
    base = {
        "parser_backend": "hybrid",
        "hybrid_noise_threshold": 0.2,
        "hybrid_docling_skip_score": 70.0,
        "hybrid_switch_min_delta": 2.0,
        "hybrid_marker_min_length": 200,
        "marker_prefer_api": False,
    }
    base.update(overrides)
    return base


class ParserBackendRoutingTests(unittest.TestCase):
    def test_docling_backend_routes_to_docling_pipeline(self):
        with patch.object(ps, "_run_docling_pipeline", return_value=("doc-md", Path("/tmp/data"))) as mock_doc:
            result = ps.process_pdf_safely("a.pdf", output_dir="/tmp/out", file_id="f1", parser_backend="docling")
        self.assertEqual(result[0], "doc-md")
        mock_doc.assert_called_once()

    def test_marker_backend_routes_to_marker_pipeline(self):
        with patch.object(ps, "_run_marker_pipeline", return_value=("marker-md", Path("/tmp/data"))) as mock_marker:
            result = ps.process_pdf_safely("a.pdf", output_dir="/tmp/out", file_id="f1", parser_backend="marker")
        self.assertEqual(result[0], "marker-md")
        mock_marker.assert_called_once()


class ParserQualityScoreTests(unittest.TestCase):
    def test_compute_quality_score_prefers_structured_markdown(self):
        structured = "\n".join(
            [
                "# 文档",
                "## 1. 概述",
                "内容A",
                "内容B",
                "### 1.1 背景",
                "内容C",
                "#### 1.1.1 定义",
                "内容D",
            ]
        )
        noisy = "\n".join(
            [
                "# 2212",
                "## A7*",
                "### it (InitialNode)",
                "#### ----",
                "Page 3",
                "http://example.com",
            ]
        )

        good = ps._compute_quality_score(structured)
        bad = ps._compute_quality_score(noisy)

        self.assertGreater(good["score"], bad["score"])
        self.assertIn("signals", good)
        self.assertIn("breakdown", good)
        self.assertGreater(good["valid_headings"], bad["valid_headings"])


class TocMatchingTests(unittest.TestCase):
    def test_toc_titles_match_chinese_symbols(self):
        toc = "12.5.1.E-R图转换关系模式（重点★★★★★）"
        item = "12.5.1 E-R图转换关系模式（重点）"
        self.assertTrue(ps._toc_titles_match(toc, item))

    def test_toc_titles_match_chinese_with_spacing(self):
        toc = "10.1.5.1.模拟数据编码（次重点 ★★★★☆）"
        item = "10.1.5.1 模拟 数据 编码（次重点）"
        self.assertTrue(ps._toc_titles_match(toc, item))

    def test_toc_titles_match_rejects_unrelated_titles(self):
        toc = "10.1.5.1.模拟数据编码（次重点 ★★★★☆）"
        item = "12.5.1 E-R图转换关系模式（重点）"
        self.assertFalse(ps._toc_titles_match(toc, item))


class ParserHybridDecisionTests(unittest.TestCase):
    def test_hybrid_skips_marker_when_docling_score_is_high(self):
        with patch.object(ps, "_run_docling_pipeline", return_value=("doc-md", Path("/tmp/data"))):
            with patch.object(ps, "_compute_quality_score", return_value=_score_payload(75.0)):
                with patch.object(ps, "_run_marker_pipeline") as mock_marker:
                    with patch.object(ps, "get_parser_runtime_config", return_value=_runtime_config()):
                        result = ps.process_pdf_safely(
                            "a.pdf", output_dir="/tmp/out", file_id="f1", parser_backend="hybrid"
                        )
        self.assertEqual(result[0], "doc-md")
        mock_marker.assert_not_called()

    def test_hybrid_selects_marker_when_score_gap_is_large_enough(self):
        with patch.object(ps, "_run_docling_pipeline", return_value=("doc-md", Path("/tmp/data"))):
            with patch.object(ps, "_is_marker_available", return_value=True):
                with patch.object(
                    ps, "_run_marker_pipeline", return_value=("m" * 600, Path("/tmp/data"))
                ) as mock_marker:
                    with patch.object(
                        ps,
                        "_compute_quality_score",
                        side_effect=[_score_payload(60.0), _score_payload(66.0)],
                    ):
                        with patch.object(ps, "get_parser_runtime_config", return_value=_runtime_config()):
                            result = ps.process_pdf_safely(
                                "a.pdf", output_dir="/tmp/out", file_id="f1", parser_backend="hybrid"
                            )
        self.assertEqual(result[0], "m" * 600)
        mock_marker.assert_called_once()

    def test_hybrid_keeps_docling_when_marker_gap_is_too_small(self):
        with patch.object(ps, "_run_docling_pipeline", return_value=("doc-md", Path("/tmp/data"))):
            with patch.object(ps, "_is_marker_available", return_value=True):
                with patch.object(ps, "_run_marker_pipeline", return_value=("m" * 600, Path("/tmp/data"))):
                    with patch.object(
                        ps,
                        "_compute_quality_score",
                        side_effect=[_score_payload(60.0), _score_payload(61.5)],
                    ):
                        with patch.object(ps, "get_parser_runtime_config", return_value=_runtime_config()):
                            result = ps.process_pdf_safely(
                                "a.pdf", output_dir="/tmp/out", file_id="f1", parser_backend="hybrid"
                            )
        self.assertEqual(result[0], "doc-md")

    def test_hybrid_keeps_docling_when_marker_unavailable(self):
        with patch.object(ps, "_run_docling_pipeline", return_value=("doc-md", Path("/tmp/data"))):
            with patch.object(ps, "_is_marker_available", return_value=False):
                with patch.object(ps, "_is_marker_api_available", return_value=False):
                    with patch.object(ps, "get_parser_runtime_config", return_value=_runtime_config()):
                        with patch.object(ps, "_compute_quality_score", return_value=_score_payload(55.0)):
                            result = ps.process_pdf_safely(
                                "a.pdf", output_dir="/tmp/out", file_id="f1", parser_backend="hybrid"
                            )
        self.assertEqual(result[0], "doc-md")


class ParserMarkerFallbackTests(unittest.TestCase):
    def test_marker_prefers_api_and_falls_back_to_cli(self):
        with patch.object(ps, "get_parser_runtime_config", return_value=_runtime_config(marker_prefer_api=True)):
            with patch.object(ps, "_run_marker_pipeline_api", side_effect=RuntimeError("api fail")):
                with patch.object(ps, "_run_marker_pipeline_cli", return_value=("cli-md", Path("/tmp/data"))):
                    result = ps._run_marker_pipeline(Path("a.pdf"), "/tmp/out", "f1", True)
        self.assertEqual(result[0], "cli-md")

    def test_marker_prefers_cli_and_falls_back_to_api(self):
        with patch.object(ps, "get_parser_runtime_config", return_value=_runtime_config(marker_prefer_api=False)):
            with patch.object(ps, "_run_marker_pipeline_cli", side_effect=RuntimeError("cli fail")):
                with patch.object(ps, "_run_marker_pipeline_api", return_value=("api-md", Path("/tmp/data"))):
                    result = ps._run_marker_pipeline(Path("a.pdf"), "/tmp/out", "f1", True)
        self.assertEqual(result[0], "api-md")

    def test_update_parser_runtime_config_applies_values(self):
        ps.update_parser_runtime_config(
            {
                "parser_backend": "hybrid",
                "hybrid_noise_threshold": 0.33,
                "hybrid_docling_skip_score": 66,
                "hybrid_switch_min_delta": 4,
                "hybrid_marker_min_length": 321,
                "marker_prefer_api": True,
            }
        )
        cfg = ps.get_parser_runtime_config()
        self.assertEqual(cfg["parser_backend"], "hybrid")
        self.assertAlmostEqual(cfg["hybrid_noise_threshold"], 0.33, places=2)
        self.assertAlmostEqual(cfg["hybrid_docling_skip_score"], 66.0, places=2)
        self.assertAlmostEqual(cfg["hybrid_switch_min_delta"], 4.0, places=2)
        self.assertEqual(cfg["hybrid_marker_min_length"], 321)
        self.assertTrue(cfg["marker_prefer_api"])

        # restore default for test isolation
        ps.update_parser_runtime_config(_runtime_config(parser_backend="docling"))


class _FakeDoc:
    def __init__(self, items, pages=None):
        self._items = items
        self.pages = pages

    def iterate_items(self):
        for item in self._items:
            yield item, 0


class _FakeResult:
    def __init__(self, doc):
        self.document = doc


@unittest.skipUnless(_HAS_DOCLING_CORE, "docling_core 不可用")
class ParserProvenanceCompatibilityTests(unittest.TestCase):
    def test_reclassify_supports_v2_page_no_mapping(self):
        item = SimpleNamespace(
            label=DocItemLabel.TEXT,
            prov=[SimpleNamespace(page_no=1, bbox=SimpleNamespace(t=980.0, b=940.0))],
            content_layer=ContentLayer.BODY,
        )
        doc = _FakeDoc(items=[item], pages={1: SimpleNamespace(size=SimpleNamespace(height=1000.0))})

        changed = ps.reclassify_furniture_by_position(_FakeResult(doc))

        self.assertEqual(changed, 1)
        self.assertEqual(item.content_layer, ContentLayer.FURNITURE)

    def test_reclassify_supports_legacy_page_object(self):
        item = SimpleNamespace(
            label=DocItemLabel.TEXT,
            prov=[SimpleNamespace(page=SimpleNamespace(height=1000.0), bbox=SimpleNamespace(t=980.0, b=940.0))],
            content_layer=ContentLayer.BODY,
        )
        doc = _FakeDoc(items=[item], pages=None)

        changed = ps.reclassify_furniture_by_position(_FakeResult(doc))

        self.assertEqual(changed, 1)
        self.assertEqual(item.content_layer, ContentLayer.FURNITURE)

    def test_reclassify_handles_list_pages_with_one_based_page_no(self):
        item = SimpleNamespace(
            label=DocItemLabel.TEXT,
            prov=[SimpleNamespace(page_no=1, bbox=SimpleNamespace(t=980.0, b=940.0))],
            content_layer=ContentLayer.BODY,
        )
        doc = _FakeDoc(items=[item], pages=[SimpleNamespace(size=SimpleNamespace(height=1000.0))])

        changed = ps.reclassify_furniture_by_position(_FakeResult(doc))

        self.assertEqual(changed, 1)
        self.assertEqual(item.content_layer, ContentLayer.FURNITURE)


class HierarchyPostprocessorGuardTests(unittest.TestCase):
    def test_skip_hierarchy_postprocess_for_large_page_count(self):
        result = _FakeResult(_FakeDoc(items=[], pages=[object(), object(), object()]))
        with patch.object(ps, "_HIERARCHICAL_AVAILABLE", True):
            with patch.object(ps, "HIERARCHY_POSTPROCESS_MAX_PAGES", 2):
                with patch.object(ps, "ResultPostprocessor") as mock_post:
                    ps.apply_hierarchy_postprocessor(result, "dummy.pdf")
        mock_post.assert_not_called()

    def test_run_hierarchy_postprocess_when_page_count_within_limit(self):
        result = _FakeResult(_FakeDoc(items=[], pages=[object(), object()]))
        with patch.object(ps, "_HIERARCHICAL_AVAILABLE", True):
            with patch.object(ps, "HIERARCHY_POSTPROCESS_MAX_PAGES", 10):
                with patch.object(ps, "ResultPostprocessor") as mock_post:
                    mock_post.return_value.process.return_value = None
                    ps.apply_hierarchy_postprocessor(result, "dummy.pdf")
        mock_post.assert_called_once()


if __name__ == "__main__":
    unittest.main(verbosity=2)
