import json
import os
import sys
import tempfile
import asyncio
import types
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from cryptography.fernet import Fernet
from fastapi.testclient import TestClient


_STUBBED_MODULES = ("parser_service", "cognitive_engine", "hardware_utils")
_ORIGINAL_MODULES = {name: sys.modules.get(name) for name in _STUBBED_MODULES}


def _install_test_stubs():
    """Install lightweight stubs so app import does not require heavy runtime deps."""
    parser_service = types.ModuleType("parser_service")
    parser_service.process_pdf_safely = lambda *args, **kwargs: ("# dummy\n", None)
    parser_service.get_parser_runtime_config = lambda: {
        "parser_backend": "docling",
        "hybrid_noise_threshold": 0.2,
        "hybrid_docling_skip_score": 70.0,
        "hybrid_switch_min_delta": 2.0,
        "hybrid_marker_min_length": 200,
        "marker_prefer_api": False,
        "hf_endpoint_region": "global",
        "task_timeout_seconds": 600,
    }
    parser_service.update_parser_runtime_config = lambda *args, **kwargs: None
    sys.modules["parser_service"] = parser_service

    cognitive_engine = types.ModuleType("cognitive_engine")
    cognitive_engine.generate_mindmap_structure = lambda *args, **kwargs: "# dummy"
    cognitive_engine.update_client_config = lambda *args, **kwargs: None
    cognitive_engine.set_model = lambda *args, **kwargs: None
    cognitive_engine.set_account_type = lambda *args, **kwargs: None

    async def _test_connection(*args, **kwargs):
        return {"success": True, "message": "ok"}

    cognitive_engine.test_connection = _test_connection

    async def _fetch_models_detailed(*args, **kwargs):
        return {"success": True, "models": ["dummy-model"], "error": ""}

    cognitive_engine.fetch_models_detailed = _fetch_models_detailed
    sys.modules["cognitive_engine"] = cognitive_engine

    hardware_utils = types.ModuleType("hardware_utils")
    hardware_utils.get_hardware_info = lambda: {"device_type": "cpu"}
    sys.modules["hardware_utils"] = hardware_utils


def _restore_original_modules():
    for name, module in _ORIGINAL_MODULES.items():
        if module is None:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = module


_install_test_stubs()
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import app as app_module  # noqa: E402

_restore_original_modules()


def _swallow_background_task(coro):
    """Prevent background coroutine from running during request tests."""
    coro.close()
    return None


class FastAPIEndpointTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.base = Path(self.tmpdir.name)
        self._rebind_storage_paths()
        app_module.tasks.clear()

    def tearDown(self):
        self.tmpdir.cleanup()

    def _rebind_storage_paths(self):
        app_module.DATA_DIR = str(self.base / "data")
        app_module.PDF_DIR = str(self.base / "data" / "pdfs")
        app_module.MD_DIR = str(self.base / "data" / "mds")
        app_module.IMAGES_DIR = str(self.base / "data" / "images")
        app_module.SOURCE_MD_DIR = str(self.base / "data" / "source_mds")
        app_module.SOURCE_INDEX_DIR = str(self.base / "data" / "source_indexes")
        app_module.SOURCE_LINE_MAP_DIR = str(self.base / "data" / "source_line_maps")
        app_module.HISTORY_FILE = str(self.base / "data" / "history.json")
        app_module.CONFIG_FILE = str(self.base / "data" / "config.json")
        app_module.CONFIG_KEY_FILE = str(self.base / "data" / "config.key")

        os.makedirs(app_module.PDF_DIR, exist_ok=True)
        os.makedirs(app_module.MD_DIR, exist_ok=True)
        os.makedirs(app_module.IMAGES_DIR, exist_ok=True)
        os.makedirs(app_module.SOURCE_MD_DIR, exist_ok=True)
        os.makedirs(app_module.SOURCE_INDEX_DIR, exist_ok=True)
        os.makedirs(app_module.SOURCE_LINE_MAP_DIR, exist_ok=True)
        os.makedirs(os.path.dirname(app_module.HISTORY_FILE), exist_ok=True)
        with open(app_module.HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump([], f)

    def test_build_source_markdown_strips_all_sidecar_comments(self):
        raw = "\n".join(
            [
                "## 标题 <!-- fm_anchor:{\"page_no\":1} --> <!-- FM-Confidence: 0.31 -->",
                "正文 <!-- FM-Confidence: 0.10 -->",
            ]
        )

        cleaned = app_module._build_source_markdown(raw)

        self.assertNotIn("fm_anchor", cleaned.lower())
        self.assertNotIn("fm-confidence", cleaned.lower())
        self.assertEqual(len(raw.splitlines()), len(cleaned.splitlines()))

    def test_task_status_includes_file_id(self):
        task = app_module.create_task("task-1", file_id="file-1")
        task.status = app_module.TaskStatus.PROCESSING
        task.progress = 42
        task.message = "running"

        with TestClient(app_module.app) as client:
            res = client.get("/task/task-1")

        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["file_id"], "file-1")
        self.assertEqual(data["progress"], 42)
        self.assertNotIn("result", data)

    def test_task_status_excludes_result_by_default_and_supports_include_result(self):
        task = app_module.create_task("task-result", file_id="file-result")
        task.status = app_module.TaskStatus.COMPLETED
        task.progress = 100
        task.message = "done"
        task.result = "# final markdown"

        with TestClient(app_module.app) as client:
            default_res = client.get("/task/task-result")
            include_res = client.get("/task/task-result?include_result=true")

        self.assertEqual(default_res.status_code, 200)
        self.assertEqual(include_res.status_code, 200)
        default_data = default_res.json()
        include_data = include_res.json()
        self.assertNotIn("result", default_data)
        self.assertEqual(include_data.get("result"), "# final markdown")

    def test_document_status_returns_live_task(self):
        file_id = "file-doc-status"
        task_id = "task-doc-status"
        pdf_path = Path(app_module.PDF_DIR) / "doc-status.pdf"
        md_path = Path(app_module.MD_DIR) / f"{file_id}.md"
        pdf_path.write_bytes(b"pdf")
        md_path.write_text("# md", encoding="utf-8")

        app_module.add_file_record(
            file_id=file_id,
            filename="doc-status.pdf",
            file_hash="hash-doc-status",
            pdf_path=str(pdf_path),
            md_path=str(md_path),
            status="processing",
            task_id=task_id,
        )
        task = app_module.create_task(task_id, file_id=file_id)
        task.status = app_module.TaskStatus.PROCESSING
        task.progress = 37
        task.message = "processing"
        app_module._persist_task_snapshot(task)

        with TestClient(app_module.app) as client:
            res = client.get(f"/documents/{file_id}/status")

        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["task_id"], task_id)
        self.assertEqual(data["file_id"], file_id)
        self.assertEqual(data["status"], "processing")
        self.assertEqual(data["progress"], 37)

    def test_document_status_falls_back_to_snapshot_when_task_evicted(self):
        file_id = "file-doc-snapshot"
        task_id = "task-doc-snapshot"
        pdf_path = Path(app_module.PDF_DIR) / "doc-snapshot.pdf"
        md_path = Path(app_module.MD_DIR) / f"{file_id}.md"
        pdf_path.write_bytes(b"pdf")
        md_path.write_text("# md", encoding="utf-8")

        app_module.add_file_record(
            file_id=file_id,
            filename="doc-snapshot.pdf",
            file_hash="hash-doc-snapshot",
            pdf_path=str(pdf_path),
            md_path=str(md_path),
            status="processing",
            task_id=task_id,
        )
        task = app_module.create_task(task_id, file_id=file_id)
        task.status = app_module.TaskStatus.PROCESSING
        task.progress = 66
        task.message = "snapshot-only"
        app_module._persist_task_snapshot(task)
        app_module.tasks.pop(task_id, None)

        with TestClient(app_module.app) as client:
            res = client.get(f"/documents/{file_id}/status")

        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["task_id"], task_id)
        self.assertEqual(data["file_id"], file_id)
        self.assertEqual(data["status"], "processing")
        self.assertEqual(data["progress"], 66)

    def test_get_file_content_supports_raw_format(self):
        file_id = "file-raw"
        md_path = Path(app_module.MD_DIR) / f"{file_id}.md"
        md_content = "# raw\ncontent"
        md_path.write_text(md_content, encoding="utf-8")
        pdf_path = Path(app_module.PDF_DIR) / "raw.pdf"
        pdf_path.write_bytes(b"pdf")

        app_module.add_file_record(
            file_id=file_id,
            filename="raw.pdf",
            file_hash="hash-raw",
            pdf_path=str(pdf_path),
            md_path=str(md_path),
            status="completed",
            task_id="task-raw",
        )

        with TestClient(app_module.app) as client:
            res = client.get(f"/file/{file_id}?format=raw")

        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.text, md_content)
        self.assertIn("text/markdown", res.headers.get("content-type", ""))

    def test_document_cancel_routes_to_task_cancel(self):
        file_id = "file-doc-cancel"
        task_id = "task-doc-cancel"
        pdf_path = Path(app_module.PDF_DIR) / "doc-cancel.pdf"
        md_path = Path(app_module.MD_DIR) / f"{file_id}.md"
        pdf_path.write_bytes(b"pdf")
        md_path.write_text("# md", encoding="utf-8")

        app_module.add_file_record(
            file_id=file_id,
            filename="doc-cancel.pdf",
            file_hash="hash-doc-cancel",
            pdf_path=str(pdf_path),
            md_path=str(md_path),
            status="processing",
            task_id=task_id,
        )
        task = app_module.create_task(task_id, file_id=file_id)
        task.status = app_module.TaskStatus.PROCESSING

        with TestClient(app_module.app) as client:
            res = client.post(f"/documents/{file_id}/cancel", json={"reason": "test-cancel"})

        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["task_id"], task_id)
        self.assertEqual(data["status"], "cancelling")
        self.assertTrue(task.cancel_requested)

    def test_upload_duplicate_processing_reuses_existing_task(self):
        content = b"same-pdf-content"
        file_hash = app_module.hashlib.md5(content).hexdigest()
        old_file_id = "file-existing"
        old_task_id = "task-existing"

        old_pdf = Path(app_module.PDF_DIR) / "existing.pdf"
        old_pdf.write_bytes(content)
        old_md = Path(app_module.MD_DIR) / f"{old_file_id}.md"
        old_md.write_text("# old", encoding="utf-8")

        app_module.add_file_record(
            file_id=old_file_id,
            filename="doc.pdf",
            file_hash=file_hash,
            pdf_path=str(old_pdf),
            md_path=str(old_md),
            status="processing",
            task_id=old_task_id,
        )
        task = app_module.create_task(old_task_id, file_id=old_file_id)
        task.status = app_module.TaskStatus.PROCESSING

        with patch.object(app_module.asyncio, "create_task", side_effect=_swallow_background_task):
            with TestClient(app_module.app) as client:
                res = client.post("/upload", files={"file": ("doc.pdf", content, "application/pdf")})

        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertTrue(data["is_duplicate"])
        self.assertEqual(data["status"], "processing")
        self.assertEqual(data["task_id"], old_task_id)
        self.assertEqual(data["file_id"], old_file_id)

    def test_upload_duplicate_completed_existing_md_is_opt_in(self):
        content = b"same-pdf-content-ready"
        file_hash = app_module.hashlib.md5(content).hexdigest()
        old_file_id = "file-ready"
        old_task_id = "task-ready"

        old_pdf = Path(app_module.PDF_DIR) / "ready.pdf"
        old_pdf.write_bytes(content)
        old_md = Path(app_module.MD_DIR) / f"{old_file_id}.md"
        old_md.write_text("# ready md", encoding="utf-8")

        app_module.add_file_record(
            file_id=old_file_id,
            filename="ready.pdf",
            file_hash=file_hash,
            pdf_path=str(old_pdf),
            md_path=str(old_md),
            status="completed",
            task_id=old_task_id,
        )

        with TestClient(app_module.app) as client:
            res_default = client.post("/upload", files={"file": ("ready.pdf", content, "application/pdf")})
            res_with_md = client.post(
                "/upload?include_existing_md=true",
                files={"file": ("ready.pdf", content, "application/pdf")},
            )

        self.assertEqual(res_default.status_code, 200)
        self.assertEqual(res_with_md.status_code, 200)
        default_data = res_default.json()
        with_md_data = res_with_md.json()

        self.assertTrue(default_data["is_duplicate"])
        self.assertEqual(default_data["status"], "completed")
        self.assertEqual(default_data["file_id"], old_file_id)
        self.assertNotIn("existing_md", default_data)

        self.assertEqual(with_md_data.get("existing_md"), "# ready md")

    def test_upload_duplicate_processing_restarts_when_task_missing(self):
        content = b"same-pdf-content-restart"
        file_hash = app_module.hashlib.md5(content).hexdigest()
        old_file_id = "file-stale"
        old_task_id = "task-stale"

        old_pdf = Path(app_module.PDF_DIR) / "stale.pdf"
        old_pdf.write_bytes(content)
        old_md = Path(app_module.MD_DIR) / f"{old_file_id}.md"
        old_md.write_text("# stale", encoding="utf-8")

        app_module.add_file_record(
            file_id=old_file_id,
            filename="stale.pdf",
            file_hash=file_hash,
            pdf_path=str(old_pdf),
            md_path=str(old_md),
            status="processing",
            task_id=old_task_id,
        )
        # 注意：不创建 old_task_id，对应“历史处理中任务已丢失”的场景

        with patch.object(app_module.asyncio, "create_task", side_effect=_swallow_background_task):
            with TestClient(app_module.app) as client:
                res = client.post("/upload", files={"file": ("stale.pdf", content, "application/pdf")})

        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertTrue(data["is_duplicate"])
        self.assertEqual(data["status"], "processing")
        self.assertEqual(data["file_id"], old_file_id)
        self.assertNotEqual(data["task_id"], old_task_id)
        self.assertIn(data["task_id"], app_module.tasks)

        history = app_module.load_history()
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["file_id"], old_file_id)
        self.assertEqual(history[0]["task_id"], data["task_id"])
        self.assertEqual(history[0]["status"], "processing")

    def test_upload_rejects_oversized_file_with_413(self):
        old_limit = app_module.MAX_UPLOAD_BYTES
        app_module.MAX_UPLOAD_BYTES = 1024
        try:
            payload = b"a" * 2048
            with TestClient(app_module.app) as client:
                res = client.post("/upload", files={"file": ("oversized.pdf", payload, "application/pdf")})

            self.assertEqual(res.status_code, 413)
            detail = res.json().get("detail", {})
            self.assertEqual(detail.get("code"), "FILE_TOO_LARGE")
            self.assertEqual(detail.get("max_bytes"), 1024)

            temp_dir = Path(app_module.DATA_DIR) / "temp"
            if temp_dir.exists():
                self.assertEqual(list(temp_dir.iterdir()), [])
        finally:
            app_module.MAX_UPLOAD_BYTES = old_limit

    def test_delete_file_removes_disk_artifacts(self):
        file_id = "file-delete"
        task_id = "task-delete"
        pdf_path = Path(app_module.PDF_DIR) / "to-delete.pdf"
        md_path = Path(app_module.MD_DIR) / f"{file_id}.md"
        image_dir = Path(app_module.IMAGES_DIR) / file_id

        pdf_path.write_bytes(b"pdf")
        md_path.write_text("# md", encoding="utf-8")
        image_dir.mkdir(parents=True, exist_ok=True)
        (image_dir / "pic_0.png").write_bytes(b"img")

        app_module.add_file_record(
            file_id=file_id,
            filename="to-delete.pdf",
            file_hash="hash-delete",
            pdf_path=str(pdf_path),
            md_path=str(md_path),
            status="completed",
            task_id=task_id,
        )
        app_module.create_task(task_id, file_id=file_id)

        with TestClient(app_module.app) as client:
            res = client.delete(f"/file/{file_id}")

        self.assertEqual(res.status_code, 200)
        self.assertFalse(pdf_path.exists())
        self.assertFalse(md_path.exists())
        self.assertFalse(image_dir.exists())
        self.assertEqual(app_module.load_history(), [])
        self.assertNotIn(task_id, app_module.tasks)

    def test_get_file_tree_uses_source_index(self):
        file_id = "file-tree"
        md_path = Path(app_module.MD_DIR) / f"{file_id}.md"
        md_path.write_text("# title\n## a\nx", encoding="utf-8")
        source_md = Path(app_module.SOURCE_MD_DIR) / f"{file_id}.md"
        source_md.write_text("# title\n## a\nx", encoding="utf-8")
        index_path = Path(app_module.SOURCE_INDEX_DIR) / f"{file_id}.json"
        index_payload = {
            "file_id": file_id,
            "source_md_path": str(source_md),
            "tree": {
                "node_id": "root",
                "topic": "Root",
                "level": 0,
                "source_line_start": 1,
                "source_line_end": 3,
                "children": [
                    {
                        "node_id": "n_1",
                        "topic": "title",
                        "level": 1,
                        "source_line_start": 1,
                        "source_line_end": 3,
                        "children": [],
                    }
                ],
            },
            "flat_nodes": [
                {
                    "node_id": "n_1",
                    "topic": "title",
                    "level": 1,
                    "source_line_start": 1,
                    "source_line_end": 3,
                }
            ],
            "node_index": {
                "n_1": {
                    "node_id": "n_1",
                    "topic": "title",
                    "level": 1,
                    "source_line_start": 1,
                    "source_line_end": 3,
                }
            },
        }
        index_path.write_text(json.dumps(index_payload, ensure_ascii=False), encoding="utf-8")

        app_module.add_file_record(
            file_id=file_id,
            filename="tree.pdf",
            file_hash="hash-tree",
            pdf_path=str(Path(app_module.PDF_DIR) / "tree.pdf"),
            md_path=str(md_path),
            status="completed",
            task_id="task-tree",
        )

        with TestClient(app_module.app) as client:
            res = client.get(f"/file/{file_id}/tree")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["file_id"], file_id)
        self.assertEqual(data["flat_nodes"][0]["node_id"], "n_1")

    def test_get_file_tree_can_skip_flat_nodes_payload(self):
        file_id = "file-tree-skip-flat"
        md_path = Path(app_module.MD_DIR) / f"{file_id}.md"
        md_path.write_text("# title\n## a\nx", encoding="utf-8")
        source_md = Path(app_module.SOURCE_MD_DIR) / f"{file_id}.md"
        source_md.write_text("# title\n## a\nx", encoding="utf-8")
        index_path = Path(app_module.SOURCE_INDEX_DIR) / f"{file_id}.json"
        index_payload = {
            "file_id": file_id,
            "source_md_path": str(source_md),
            "tree": {"node_id": "root", "topic": "Root", "level": 0, "children": []},
            "flat_nodes": [
                {"node_id": "n_1", "topic": "A", "level": 1, "source_line_start": 1, "source_line_end": 2},
                {"node_id": "n_2", "topic": "B", "level": 1, "source_line_start": 2, "source_line_end": 3},
            ],
            "node_index": {},
        }
        index_path.write_text(json.dumps(index_payload, ensure_ascii=False), encoding="utf-8")

        app_module.add_file_record(
            file_id=file_id,
            filename="tree-skip-flat.pdf",
            file_hash="hash-tree-skip-flat",
            pdf_path=str(Path(app_module.PDF_DIR) / "tree-skip-flat.pdf"),
            md_path=str(md_path),
            status="completed",
            task_id="task-tree-skip-flat",
        )

        with TestClient(app_module.app) as client:
            res = client.get(f"/file/{file_id}/tree?include_flat_nodes=false")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data.get("flat_nodes"), [])
        self.assertEqual(int(data.get("flat_nodes_total", 0)), 2)
        self.assertFalse(bool(data.get("flat_nodes_has_more")))

    def test_get_file_tree_supports_flat_nodes_pagination(self):
        file_id = "file-tree-pagination"
        md_path = Path(app_module.MD_DIR) / f"{file_id}.md"
        md_path.write_text("# title\n## a\nx", encoding="utf-8")
        source_md = Path(app_module.SOURCE_MD_DIR) / f"{file_id}.md"
        source_md.write_text("# title\n## a\nx", encoding="utf-8")
        index_path = Path(app_module.SOURCE_INDEX_DIR) / f"{file_id}.json"
        index_payload = {
            "file_id": file_id,
            "source_md_path": str(source_md),
            "tree": {"node_id": "root", "topic": "Root", "level": 0, "children": []},
            "flat_nodes": [
                {"node_id": "n_1", "topic": "A", "level": 1, "source_line_start": 1, "source_line_end": 1},
                {"node_id": "n_2", "topic": "B", "level": 1, "source_line_start": 2, "source_line_end": 2},
                {"node_id": "n_3", "topic": "C", "level": 1, "source_line_start": 3, "source_line_end": 3},
            ],
            "node_index": {},
        }
        index_path.write_text(json.dumps(index_payload, ensure_ascii=False), encoding="utf-8")

        app_module.add_file_record(
            file_id=file_id,
            filename="tree-pagination.pdf",
            file_hash="hash-tree-pagination",
            pdf_path=str(Path(app_module.PDF_DIR) / "tree-pagination.pdf"),
            md_path=str(md_path),
            status="completed",
            task_id="task-tree-pagination",
        )

        with TestClient(app_module.app) as client:
            res = client.get(
                f"/file/{file_id}/tree?include_tree=false&include_flat_nodes=true&flat_offset=1&flat_limit=1"
            )
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data.get("tree"), {})
        self.assertEqual([node["node_id"] for node in data.get("flat_nodes", [])], ["n_2"])
        self.assertEqual(int(data.get("flat_nodes_total", 0)), 3)
        self.assertEqual(int(data.get("flat_nodes_offset", 0)), 1)
        self.assertEqual(int(data.get("flat_nodes_limit", 0)), 1)
        self.assertTrue(bool(data.get("flat_nodes_has_more")))

    def test_get_node_source_returns_excerpt(self):
        file_id = "file-source"
        md_path = Path(app_module.MD_DIR) / f"{file_id}.md"
        source_md = Path(app_module.SOURCE_MD_DIR) / f"{file_id}.md"
        content = "\n".join(
            [
                "# Root",
                "## Section A",
                "Line A1",
                "Line A2",
                "## Section B",
                "Line B1",
            ]
        )
        md_path.write_text(content, encoding="utf-8")
        source_md.write_text(content, encoding="utf-8")
        index_path = Path(app_module.SOURCE_INDEX_DIR) / f"{file_id}.json"
        index_payload = {
            "file_id": file_id,
            "source_md_path": str(source_md),
            "tree": {},
            "flat_nodes": [],
            "capabilities": {"anchor_version": "1.0", "parser_backend": "docling", "has_precise_anchor": True},
            "node_index": {
                "n_section_a": {
                    "node_id": "n_section_a",
                    "topic": "Section A",
                    "level": 2,
                    "source_line_start": 2,
                    "source_line_end": 4,
                    "pdf_page_no": 3,
                    "pdf_y_ratio": 0.1,
                }
            },
        }
        index_path.write_text(json.dumps(index_payload, ensure_ascii=False), encoding="utf-8")

        app_module.add_file_record(
            file_id=file_id,
            filename="source.pdf",
            file_hash="hash-source",
            pdf_path=str(Path(app_module.PDF_DIR) / "source.pdf"),
            md_path=str(md_path),
            status="completed",
            task_id="task-source",
        )

        with TestClient(app_module.app) as client:
            res = client.get(f"/file/{file_id}/node/n_section_a/source?context_lines=1&max_lines=10")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["line_start"], 2)
        self.assertEqual(data["line_end"], 4)
        self.assertEqual(data["pdf_page_no"], 3)
        self.assertAlmostEqual(data["pdf_y_ratio"], 0.1, places=2)

    def test_get_node_source_returns_norm_and_raw_line_numbers(self):
        file_id = "file-source-map"
        md_path = Path(app_module.MD_DIR) / f"{file_id}.md"
        source_md = Path(app_module.SOURCE_MD_DIR) / f"{file_id}.md"
        line_map_path = Path(app_module.SOURCE_LINE_MAP_DIR) / f"{file_id}.json"

        md_path.write_text("# Root\nkeep\nnoise\n## B\nBody", encoding="utf-8")
        source_md.write_text("# Root\n## B\nBody", encoding="utf-8")
        line_map_path.write_text(
            json.dumps(
                {
                    "version": 1,
                    "file_id": file_id,
                    "line_system": "normalized_v1",
                    "norm_to_raw": [1, 4, 5],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        index_path = Path(app_module.SOURCE_INDEX_DIR) / f"{file_id}.json"
        index_path.write_text(
            json.dumps(
                {
                    "file_id": file_id,
                    "source_md_path": str(source_md),
                    "source_line_map_path": str(line_map_path),
                    "line_system": "normalized_v1",
                    "tree": {},
                    "flat_nodes": [],
                    "capabilities": {"anchor_version": "1.0", "parser_backend": "docling", "has_precise_anchor": True},
                    "node_index": {
                        "n_b": {
                            "node_id": "n_b",
                            "topic": "B",
                            "level": 2,
                            "source_line_start": 2,
                            "source_line_end": 3,
                        }
                    },
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        app_module.add_file_record(
            file_id=file_id,
            filename="source-map.pdf",
            file_hash="hash-source-map",
            pdf_path=str(Path(app_module.PDF_DIR) / "source-map.pdf"),
            md_path=str(md_path),
            status="completed",
            task_id="task-source-map",
        )

        with TestClient(app_module.app) as client:
            res = client.get(f"/file/{file_id}/node/n_b/source?context_lines=0&max_lines=10")

        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["line_start_norm"], 2)
        self.assertEqual(data["line_end_norm"], 3)
        self.assertEqual(data["line_start_raw"], 4)
        self.assertEqual(data["line_end_raw"], 5)
        self.assertEqual(data["line_system"], "normalized_v1")

    def test_get_pdf_file_uses_inline_disposition(self):
        file_id = "file-inline"
        pdf_path = Path(app_module.PDF_DIR) / "inline.pdf"
        pdf_path.write_bytes(b"%PDF-1.4\n")
        md_path = Path(app_module.MD_DIR) / f"{file_id}.md"
        md_path.write_text("# doc", encoding="utf-8")

        app_module.add_file_record(
            file_id=file_id,
            filename="inline.pdf",
            file_hash="hash-inline",
            pdf_path=str(pdf_path),
            md_path=str(md_path),
            status="completed",
            task_id="task-inline",
        )

        with TestClient(app_module.app) as client:
            res = client.get(f"/file/{file_id}/pdf")
        self.assertEqual(res.status_code, 200)
        self.assertIn("inline;", res.headers.get("content-disposition", ""))

    def test_get_file_tree_rebuilds_missing_index_from_markdown_headings(self):
        file_id = "file-rebuild"
        md_path = Path(app_module.MD_DIR) / f"{file_id}.md"
        md_path.write_text("# Root\n## A\n### A.1\n## B\nBody", encoding="utf-8")

        app_module.add_file_record(
            file_id=file_id,
            filename="rebuild.pdf",
            file_hash="hash-rebuild",
            pdf_path=str(Path(app_module.PDF_DIR) / "rebuild.pdf"),
            md_path=str(md_path),
            status="completed",
            task_id="task-rebuild",
        )

        with TestClient(app_module.app) as client:
            res = client.get(f"/file/{file_id}/tree")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        flat = data.get("flat_nodes", [])
        self.assertEqual(len(flat), 5)
        self.assertEqual([item["topic"] for item in flat], ["Root", "Root", "A", "A.1", "B"])

    def test_get_file_tree_rebuilds_missing_index_from_markdown_lists(self):
        file_id = "file-rebuild-list"
        md_path = Path(app_module.MD_DIR) / f"{file_id}.md"
        md_path.write_text("# Doc\n\n- **Section A**\n  - Point A1\n- Section B", encoding="utf-8")

        app_module.add_file_record(
            file_id=file_id,
            filename="rebuild-list.pdf",
            file_hash="hash-rebuild-list",
            pdf_path=str(Path(app_module.PDF_DIR) / "rebuild-list.pdf"),
            md_path=str(md_path),
            status="completed",
            task_id="task-rebuild-list",
        )

        with TestClient(app_module.app) as client:
            res = client.get(f"/file/{file_id}/tree")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        flat = data.get("flat_nodes", [])
        topics = [item["topic"] for item in flat]
        self.assertIn("Section A", topics)
        self.assertIn("Point A1", topics)
        self.assertIn("Section B", topics)
        self.assertGreaterEqual(len(flat), 5)

    def test_get_file_tree_rebuilds_low_quality_existing_index(self):
        file_id = "file-rebuild-low-quality"
        md_path = Path(app_module.MD_DIR) / f"{file_id}.md"
        md_path.write_text("# Doc\n\n- **Section A**\n  - Point A1\n- Section B", encoding="utf-8")
        index_path = Path(app_module.SOURCE_INDEX_DIR) / f"{file_id}.json"
        shallow_index = {
            "file_id": file_id,
            "source_md_path": str(md_path),
            "tree": {
                "node_id": "root",
                "topic": "Root",
                "level": 0,
                "source_line_start": 1,
                "source_line_end": 1,
                "children": [],
            },
            "flat_nodes": [
                {
                    "node_id": "root",
                    "topic": "Root",
                    "level": 0,
                    "source_line_start": 1,
                    "source_line_end": 1,
                }
            ],
            "node_index": {
                "root": {
                    "node_id": "root",
                    "topic": "Root",
                    "level": 0,
                    "source_line_start": 1,
                    "source_line_end": 1,
                }
            },
            "index_mode": "legacy_shallow",
        }
        index_path.write_text(json.dumps(shallow_index, ensure_ascii=False), encoding="utf-8")

        app_module.add_file_record(
            file_id=file_id,
            filename="rebuild-low-quality.pdf",
            file_hash="hash-rebuild-low-quality",
            pdf_path=str(Path(app_module.PDF_DIR) / "rebuild-low-quality.pdf"),
            md_path=str(md_path),
            status="completed",
            task_id="task-rebuild-low-quality",
        )

        with TestClient(app_module.app) as client:
            res = client.get(f"/file/{file_id}/tree")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        flat = data.get("flat_nodes", [])
        self.assertGreaterEqual(len(flat), 5)
        self.assertIn("Section A", [item["topic"] for item in flat])

        rebuilt_index = json.loads(index_path.read_text(encoding="utf-8"))
        self.assertEqual(rebuilt_index.get("index_mode"), "markdown_outline_v2")

    def test_admin_source_index_rebuild_endpoint_supports_dry_run_and_apply(self):
        file_id = "file-admin-rebuild"
        md_path = Path(app_module.MD_DIR) / f"{file_id}.md"
        md_path.write_text("# Doc\n\n- Section A\n  - Point A1\n- Section B", encoding="utf-8")
        index_path = Path(app_module.SOURCE_INDEX_DIR) / f"{file_id}.json"
        index_path.write_text(
            json.dumps(
                {
                    "file_id": file_id,
                    "source_md_path": str(md_path),
                    "tree": {
                        "node_id": "root",
                        "topic": "Root",
                        "level": 0,
                        "source_line_start": 1,
                        "source_line_end": 1,
                        "children": [],
                    },
                    "flat_nodes": [
                        {
                            "node_id": "root",
                            "topic": "Root",
                            "level": 0,
                            "source_line_start": 1,
                            "source_line_end": 1,
                        }
                    ],
                    "node_index": {
                        "root": {
                            "node_id": "root",
                            "topic": "Root",
                            "level": 0,
                            "source_line_start": 1,
                            "source_line_end": 1,
                        }
                    },
                    "index_mode": "legacy_shallow",
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        app_module.add_file_record(
            file_id=file_id,
            filename="admin-rebuild.pdf",
            file_hash="hash-admin-rebuild",
            pdf_path=str(Path(app_module.PDF_DIR) / "admin-rebuild.pdf"),
            md_path=str(md_path),
            status="completed",
            task_id="task-admin-rebuild",
        )

        with TestClient(app_module.app) as client:
            dry_res = client.post(
                "/admin/source-index/rebuild",
                json={"dry_run": True, "file_ids": [file_id]},
            )
            self.assertEqual(dry_res.status_code, 200)
            dry_data = dry_res.json()
            self.assertTrue(dry_data.get("success"))
            self.assertEqual(dry_data.get("summary", {}).get("rebuilt"), 1)
            self.assertEqual(dry_data.get("items", [])[0].get("action"), "would_rebuild")

            unchanged = json.loads(index_path.read_text(encoding="utf-8"))
            self.assertEqual(unchanged.get("index_mode"), "legacy_shallow")

            apply_res = client.post(
                "/admin/source-index/rebuild",
                json={"dry_run": False, "file_ids": [file_id]},
            )
            self.assertEqual(apply_res.status_code, 200)
            apply_data = apply_res.json()
            self.assertTrue(apply_data.get("success"))
            self.assertEqual(apply_data.get("summary", {}).get("rebuilt"), 1)
            self.assertEqual(apply_data.get("items", [])[0].get("action"), "rebuilt")

        rebuilt = json.loads(index_path.read_text(encoding="utf-8"))
        self.assertEqual(rebuilt.get("index_mode"), "markdown_outline_v2")
        self.assertGreaterEqual(len(rebuilt.get("flat_nodes", [])), 4)

    def test_config_save_encrypts_api_key_and_get_masks(self):
        payload = {
            "active_profile_id": "p1",
            "profiles": [
                {
                    "id": "p1",
                    "name": "default",
                    "provider": "deepseek",
                    "base_url": "https://api.deepseek.com",
                    "model": "deepseek-chat",
                    "api_key": "sk-test-123",
                    "account_type": "free",
                    "manual_models": ["deepseek-chat"],
                }
            ],
        }

        with TestClient(app_module.app) as client:
            save_res = client.post("/config", json=payload)
            self.assertEqual(save_res.status_code, 200)

            get_res = client.get("/config")
            self.assertEqual(get_res.status_code, 200)
            view = get_res.json()
            self.assertEqual(view["profiles"][0]["api_key"], "***")
            self.assertTrue(view["profiles"][0]["has_api_key"])

        config_file_content = Path(app_module.CONFIG_FILE).read_text(encoding="utf-8")
        self.assertNotIn("sk-test-123", config_file_content)
        self.assertIn("enc:v1:", config_file_content)

    def test_config_export_and_import_roundtrip_without_plaintext_key(self):
        initial_payload = {
            "active_profile_id": "p1",
            "advanced": {
                "engine_concurrency": 4,
                "engine_temperature": 0.45,
                "engine_max_tokens": 9000,
            },
            "profiles": [
                {
                    "id": "p1",
                    "name": "default",
                    "provider": "deepseek",
                    "base_url": "https://api.deepseek.com",
                    "model": "deepseek-chat",
                    "api_key": "sk-test-456",
                    "account_type": "free",
                    "manual_models": ["deepseek-chat"],
                }
            ],
        }

        with TestClient(app_module.app) as client:
            save_res = client.post("/config", json=initial_payload)
            self.assertEqual(save_res.status_code, 200)

            export_res = client.get("/config/export")
            self.assertEqual(export_res.status_code, 200)
            exported = export_res.json()
            self.assertEqual(exported["profiles"][0]["api_key"], "")
            self.assertTrue(exported["profiles"][0]["has_api_key"])
            self.assertEqual(exported["advanced"]["engine_concurrency"], 4)
            self.assertAlmostEqual(exported["advanced"]["engine_temperature"], 0.45, places=2)
            self.assertEqual(exported["advanced"]["engine_max_tokens"], 9000)

            imported_payload = {
                "active_profile_id": "p1",
                "advanced": exported.get("advanced"),
                "profiles": [
                    {
                        "id": "p1",
                        "name": "default",
                        "provider": "deepseek",
                        "base_url": "https://api.deepseek.com",
                        "model": "deepseek-chat",
                        "api_key": "",
                        "has_api_key": True,
                        "account_type": "free",
                        "manual_models": ["deepseek-chat"],
                    }
                ],
            }
            import_res = client.post("/config/import", json=imported_payload)
            self.assertEqual(import_res.status_code, 200)
            self.assertTrue(import_res.json().get("success"))

            get_res = client.get("/config")
            self.assertEqual(get_res.status_code, 200)
            view = get_res.json()
            self.assertEqual(view["profiles"][0]["api_key"], "***")
            self.assertTrue(view["profiles"][0]["has_api_key"])
            self.assertEqual(view["advanced"]["engine_concurrency"], 4)
            self.assertAlmostEqual(view["advanced"]["engine_temperature"], 0.45, places=2)
            self.assertEqual(view["advanced"]["engine_max_tokens"], 9000)

    def test_config_roundtrip_includes_parser_settings(self):
        payload = {
            "active_profile_id": "p1",
            "parser": {
                "parser_backend": "hybrid",
                "hybrid_noise_threshold": 0.35,
                "hybrid_docling_skip_score": 68,
                "hybrid_switch_min_delta": 3,
                "hybrid_marker_min_length": 300,
                "marker_prefer_api": True,
                "hf_endpoint_region": "cn",
                "task_timeout_seconds": 1200,
            },
            "advanced": {
                "engine_concurrency": 7,
                "engine_temperature": 0.7,
                "engine_max_tokens": 12000,
            },
            "profiles": [
                {
                    "id": "p1",
                    "name": "default",
                    "provider": "deepseek",
                    "base_url": "https://api.deepseek.com",
                    "model": "deepseek-chat",
                    "api_key": "sk-test-999",
                    "account_type": "free",
                    "manual_models": ["deepseek-chat"],
                }
            ],
        }

        with TestClient(app_module.app) as client:
            save_res = client.post("/config", json=payload)
            self.assertEqual(save_res.status_code, 200)

            get_res = client.get("/config")
            self.assertEqual(get_res.status_code, 200)
            parser = get_res.json().get("parser", {})
            self.assertEqual(parser.get("parser_backend"), "hybrid")
            self.assertEqual(parser.get("hybrid_marker_min_length"), 300)
            self.assertTrue(parser.get("marker_prefer_api"))
            self.assertEqual(parser.get("hf_endpoint_region"), "cn")
            self.assertEqual(parser.get("task_timeout_seconds"), 1200)
            advanced = get_res.json().get("advanced", {})
            self.assertEqual(advanced.get("engine_concurrency"), 7)
            self.assertAlmostEqual(advanced.get("engine_temperature"), 0.7, places=2)
            self.assertEqual(advanced.get("engine_max_tokens"), 12000)

    def test_config_key_rotation_keeps_non_secret_fields_and_returns_alert(self):
        payload = {
            "active_profile_id": "p1",
            "parser": {
                "parser_backend": "hybrid",
                "hybrid_noise_threshold": 0.31,
                "hybrid_docling_skip_score": 66,
                "hybrid_switch_min_delta": 3.5,
                "hybrid_marker_min_length": 256,
                "marker_prefer_api": True,
                "hf_endpoint_region": "global",
                "task_timeout_seconds": 900,
            },
            "advanced": {
                "engine_concurrency": 4,
                "engine_temperature": 0.55,
                "engine_max_tokens": 10000,
            },
            "profiles": [
                {
                    "id": "p1",
                    "name": "default",
                    "provider": "deepseek",
                    "base_url": "https://api.deepseek.com",
                    "model": "deepseek-chat",
                    "api_key": "sk-rotate-key",
                    "account_type": "free",
                    "manual_models": ["deepseek-chat"],
                }
            ],
        }

        with TestClient(app_module.app) as client:
            save_res = client.post("/config", json=payload)
            self.assertEqual(save_res.status_code, 200)

            before = Path(app_module.CONFIG_FILE).read_text(encoding="utf-8")
            self.assertIn("enc:v1:", before)

            Path(app_module.CONFIG_KEY_FILE).write_bytes(Fernet.generate_key())
            app_module._config_cipher = None

            get_res = client.get("/config")
            self.assertEqual(get_res.status_code, 200)
            data = get_res.json()

            self.assertEqual(data.get("active_profile_id"), "p1")
            self.assertEqual(data.get("profiles", [])[0].get("base_url"), "https://api.deepseek.com")
            self.assertEqual(data.get("profiles", [])[0].get("model"), "deepseek-chat")
            self.assertEqual(data.get("profiles", [])[0].get("api_key"), "")
            self.assertFalse(data.get("profiles", [])[0].get("has_api_key"))
            self.assertEqual(data.get("parser", {}).get("parser_backend"), "hybrid")
            self.assertEqual(data.get("advanced", {}).get("engine_concurrency"), 4)

            alerts = data.get("alerts", [])
            self.assertTrue(any(item.get("code") == "CONFIG_SECRET_RECOVERY_REQUIRED" for item in alerts))
            self.assertTrue(any(item.get("requires_api_key_reentry") for item in alerts))

            after = Path(app_module.CONFIG_FILE).read_text(encoding="utf-8")
            self.assertEqual(before, after)

    def test_config_rejects_non_integer_task_timeout(self):
        payload = {
            "active_profile_id": "p1",
            "parser": {
                "parser_backend": "docling",
                "hybrid_noise_threshold": 0.2,
                "hybrid_docling_skip_score": 70,
                "hybrid_switch_min_delta": 2,
                "hybrid_marker_min_length": 200,
                "marker_prefer_api": False,
                "hf_endpoint_region": "global",
                "task_timeout_seconds": 61.5,
            },
            "advanced": {
                "engine_concurrency": 5,
                "engine_temperature": 0.3,
                "engine_max_tokens": 8192,
            },
            "profiles": [
                {
                    "id": "p1",
                    "name": "default",
                    "provider": "deepseek",
                    "base_url": "https://api.deepseek.com",
                    "model": "deepseek-chat",
                    "api_key": "sk-test-999",
                    "account_type": "free",
                    "manual_models": ["deepseek-chat"],
                }
            ],
        }

        with TestClient(app_module.app) as client:
            save_res = client.post("/config", json=payload)
            self.assertEqual(save_res.status_code, 422)
            detail = save_res.json().get("detail", {})
            self.assertEqual(detail.get("code"), "INVALID_TASK_TIMEOUT_SECONDS")

    def test_config_rejects_invalid_hf_endpoint_region(self):
        payload = {
            "active_profile_id": "p1",
            "parser": {
                "parser_backend": "docling",
                "hybrid_noise_threshold": 0.2,
                "hybrid_docling_skip_score": 70,
                "hybrid_switch_min_delta": 2,
                "hybrid_marker_min_length": 200,
                "marker_prefer_api": False,
                "hf_endpoint_region": "mars",
                "task_timeout_seconds": 600,
            },
            "advanced": {
                "engine_concurrency": 5,
                "engine_temperature": 0.3,
                "engine_max_tokens": 8192,
            },
            "profiles": [
                {
                    "id": "p1",
                    "name": "default",
                    "provider": "deepseek",
                    "base_url": "https://api.deepseek.com",
                    "model": "deepseek-chat",
                    "api_key": "sk-test-999",
                    "account_type": "free",
                    "manual_models": ["deepseek-chat"],
                }
            ],
        }

        with TestClient(app_module.app) as client:
            save_res = client.post("/config", json=payload)
            self.assertEqual(save_res.status_code, 422)
            detail = save_res.json().get("detail", {})
            self.assertEqual(detail.get("code"), "INVALID_HF_ENDPOINT_REGION")

    def test_local_filelock_blocks_concurrent_access(self):
        lock_path = str(self.base / "data" / "concurrency.lock")
        entered = threading.Event()
        release = threading.Event()
        timings = {}

        def _holder():
            with app_module._LocalFileLock(lock_path, timeout=1):
                entered.set()
                release.wait(timeout=1.0)

        worker = threading.Thread(target=_holder, daemon=True)
        worker.start()
        self.assertTrue(entered.wait(timeout=1.0))

        start = time.monotonic()
        release_delay = 0.2

        def _release_later():
            time.sleep(release_delay)
            release.set()

        releaser = threading.Thread(target=_release_later, daemon=True)
        releaser.start()

        with app_module._LocalFileLock(lock_path, timeout=1):
            timings["waited"] = time.monotonic() - start

        worker.join(timeout=1.0)
        releaser.join(timeout=1.0)

        self.assertGreaterEqual(timings.get("waited", 0.0), 0.12)

    def test_cancel_task_endpoint_marks_task_as_cancelling(self):
        task = app_module.create_task("task-cancel", file_id="file-1")
        task.status = app_module.TaskStatus.PROCESSING
        task.progress = 55
        task.message = "processing"

        class _Worker:
            def __init__(self):
                self.cancelled = False

            def done(self):
                return False

            def cancel(self):
                self.cancelled = True

        worker = _Worker()
        task.worker = worker

        with TestClient(app_module.app) as client:
            res = client.post("/task/task-cancel/cancel", json={"reason": "test-cancel"})

        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertTrue(data.get("success"))
        self.assertEqual(data.get("status"), "cancelling")
        self.assertTrue(task.cancel_requested)
        self.assertEqual(task.cancel_reason, "test-cancel")
        self.assertTrue(worker.cancelled)

    def test_build_source_markdown_keeps_line_numbers_stable(self):
        raw_md = "\n".join(
            [
                "# Root <!-- fm_anchor:page=1;y=0.1 -->",
                "",
                "",
                "## Section A <!-- fm_anchor:page=2;y=0.3 -->",
                "Line A1",
                "",
                "",
                "",
                "Line A2",
            ]
        )

        source_md = app_module._build_source_markdown(raw_md)

        self.assertEqual(len(source_md.splitlines()), len(raw_md.splitlines()))
        self.assertNotIn("fm_anchor", source_md)
        self.assertIn("\n\n\n", source_md)

    def test_process_document_task_uses_durable_pipeline_when_available(self):
        called = {"durable": 0, "legacy": 0}

        async def _durable(*args, **kwargs):
            called["durable"] += 1

        async def _legacy(*args, **kwargs):
            called["legacy"] += 1

        with patch.dict(os.environ, {"FILESMIND_WORKFLOW_ENGINE": "auto"}, clear=False):
            with patch.object(app_module, "_durable_workflow_prerequisites", return_value=(True, "")):
                with patch.object(app_module, "_process_document_task_durable", side_effect=_durable):
                    with patch.object(app_module, "_process_document_task_legacy", side_effect=_legacy):
                        asyncio.run(
                            app_module.process_document_task(
                                task_id="task-dispatch-durable",
                                file_location="/tmp/doc.pdf",
                                file_id="file-dispatch-durable",
                                original_filename="doc.pdf",
                                file_hash="hash-dispatch-durable",
                            )
                        )

        self.assertEqual(called["durable"], 1)
        self.assertEqual(called["legacy"], 0)

    def test_process_document_task_fallbacks_to_legacy_when_durable_unavailable(self):
        called = {"durable": 0, "legacy": 0}

        async def _durable(*args, **kwargs):
            called["durable"] += 1

        async def _legacy(*args, **kwargs):
            called["legacy"] += 1

        with patch.dict(os.environ, {"FILESMIND_WORKFLOW_ENGINE": "auto"}, clear=False):
            with patch.object(
                app_module, "_durable_workflow_prerequisites", return_value=(False, "FILESMIND_DB_DSN is required")
            ):
                with patch.object(app_module, "_process_document_task_durable", side_effect=_durable):
                    with patch.object(app_module, "_process_document_task_legacy", side_effect=_legacy):
                        asyncio.run(
                            app_module.process_document_task(
                                task_id="task-dispatch-legacy",
                                file_location="/tmp/doc.pdf",
                                file_id="file-dispatch-legacy",
                                original_filename="doc.pdf",
                                file_hash="hash-dispatch-legacy",
                            )
                        )

        self.assertEqual(called["durable"], 0)
        self.assertEqual(called["legacy"], 1)

    def test_process_document_task_uses_engine_level_limiter_only(self):
        file_id = "file-engine-limiter"
        task_id = "task-engine-limiter"
        pdf_path = Path(app_module.PDF_DIR) / "engine-limiter.pdf"
        pdf_path.write_bytes(b"%PDF-1.4\n")
        md_path = Path(app_module.MD_DIR) / f"{file_id}.md"
        md_path.write_text("# placeholder", encoding="utf-8")

        app_module.add_file_record(
            file_id=file_id,
            filename="engine-limiter.pdf",
            file_hash="hash-engine-limiter",
            pdf_path=str(pdf_path),
            md_path=str(md_path),
            status="processing",
            task_id=task_id,
        )
        task = app_module.create_task(task_id, file_id=file_id)

        class _Node:
            def __init__(self, topic, content, level=1, node_id="n"):
                self.topic = topic
                self.full_content = content
                self.level = level
                self.id = node_id
                self.source_line_start = 1
                self.source_line_end = 3
                self.children = []
                self.ai_details = []

            def get_breadcrumbs(self):
                return self.topic

        root = _Node("Root", "x" * 80, level=0, node_id="root")
        child = _Node("Child", "y" * 120, level=1, node_id="child-1")
        root.children = [child]

        structure_utils = types.ModuleType("structure_utils")
        structure_utils.build_hierarchy_tree = lambda _md: root
        structure_utils.assign_stable_node_ids = lambda _root, file_id=None: None
        structure_utils.tree_to_markdown = lambda _root: "## Final"

        call_counter = {"count": 0}
        cognitive_engine = types.ModuleType("cognitive_engine")

        async def _refine_node_content(node_title, content_chunk, context_path=""):
            call_counter["count"] += 1
            return [{"topic": f"{node_title}-detail", "details": [context_path, content_chunk[:8]]}]

        cognitive_engine.refine_node_content = _refine_node_content

        with patch.dict(sys.modules, {"structure_utils": structure_utils, "cognitive_engine": cognitive_engine}):
            with patch.object(app_module, "process_pdf_safely", return_value=("# Root\n\n## Child\nBody", None)):
                with patch.object(
                    app_module.asyncio,
                    "Semaphore",
                    side_effect=AssertionError("app-level semaphore should not be used in stage 3"),
                ):
                    asyncio.run(
                        app_module.process_document_task(
                            task_id=task_id,
                            file_location=str(pdf_path),
                            file_id=file_id,
                            original_filename="engine-limiter.pdf",
                        )
                    )

        self.assertEqual(task.status, app_module.TaskStatus.COMPLETED)
        self.assertGreaterEqual(call_counter["count"], 1)

    def test_process_document_task_completes_with_gaps_when_refinement_nodes_fail(self):
        file_id = "file-engine-fail"
        task_id = "task-engine-fail"
        pdf_path = Path(app_module.PDF_DIR) / "engine-fail.pdf"
        pdf_path.write_bytes(b"%PDF-1.4\n")
        md_path = Path(app_module.MD_DIR) / f"{file_id}.md"
        md_path.write_text("# placeholder", encoding="utf-8")

        app_module.add_file_record(
            file_id=file_id,
            filename="engine-fail.pdf",
            file_hash="hash-engine-fail",
            pdf_path=str(pdf_path),
            md_path=str(md_path),
            status="processing",
            task_id=task_id,
        )
        task = app_module.create_task(task_id, file_id=file_id)

        class _Node:
            def __init__(self, topic, content, level=1, node_id="n"):
                self.topic = topic
                self.full_content = content
                self.level = level
                self.id = node_id
                self.source_line_start = 1
                self.source_line_end = 3
                self.children = []
                self.ai_details = []

            def get_breadcrumbs(self):
                return self.topic

        root = _Node("Root", "x" * 80, level=0, node_id="root")
        child = _Node("Child", "y" * 120, level=1, node_id="child-1")
        root.children = [child]

        structure_utils = types.ModuleType("structure_utils")
        structure_utils.build_hierarchy_tree = lambda _md: root
        structure_utils.assign_stable_node_ids = lambda _root, file_id=None: None
        structure_utils.tree_to_markdown = lambda _root: "## Final"

        cognitive_engine = types.ModuleType("cognitive_engine")

        async def _refine_node_content(node_title, content_chunk, context_path=""):
            raise RuntimeError(f"429 for {node_title}")

        cognitive_engine.refine_node_content = _refine_node_content

        with patch.dict(sys.modules, {"structure_utils": structure_utils, "cognitive_engine": cognitive_engine}):
            with patch.object(app_module, "process_pdf_safely", return_value=("# Root\n\n## Child\nBody", None)):
                asyncio.run(
                    app_module.process_document_task(
                        task_id=task_id,
                        file_location=str(pdf_path),
                        file_id=file_id,
                        original_filename="engine-fail.pdf",
                    )
                )

        self.assertEqual(task.status, app_module.TaskStatus.COMPLETED_WITH_GAPS)
        self.assertIn("Completed with gaps", task.message)
        self.assertEqual(len(task.failure_details), 1)
        self.assertEqual(task.failure_details[0]["topic"], "Child")

        app_module.tasks.pop(task_id, None)
        with TestClient(app_module.app) as client:
            status_res = client.get(f"/task/{task_id}")
        self.assertEqual(status_res.status_code, 200)
        status_data = status_res.json()
        self.assertEqual(status_data["status"], "completed_with_gaps")
        self.assertEqual(len(status_data.get("failure_details") or []), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
