import json
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient


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


_install_test_stubs()
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import app as app_module  # noqa: E402


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
        app_module.HISTORY_FILE = str(self.base / "data" / "history.json")
        app_module.CONFIG_FILE = str(self.base / "data" / "config.json")
        app_module.CONFIG_KEY_FILE = str(self.base / "data" / "config.key")

        os.makedirs(app_module.PDF_DIR, exist_ok=True)
        os.makedirs(app_module.MD_DIR, exist_ok=True)
        os.makedirs(app_module.IMAGES_DIR, exist_ok=True)
        os.makedirs(os.path.dirname(app_module.HISTORY_FILE), exist_ok=True)
        with open(app_module.HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump([], f)

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

    def test_export_xmind_by_file_id_passes_images_dir(self):
        file_id = "file-export"
        md_path = Path(app_module.MD_DIR) / f"{file_id}.md"
        md_path.write_text("# title\n- item", encoding="utf-8")

        app_module.add_file_record(
            file_id=file_id,
            filename="paper.pdf",
            file_hash="hash-export",
            pdf_path=str(Path(app_module.PDF_DIR) / "paper.pdf"),
            md_path=str(md_path),
            status="completed",
            task_id="task-export",
        )

        expected_images_dir = os.path.join(app_module.IMAGES_DIR, file_id)
        with patch.object(app_module, "generate_xmind_content", return_value=b"XMIND") as mock_gen:
            with TestClient(app_module.app) as client:
                res = client.get(f"/export/xmind/{file_id}")

        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.content, b"XMIND")
        self.assertIn("attachment; filename=paper.xmind", res.headers.get("content-disposition", ""))
        mock_gen.assert_called_once()
        self.assertEqual(mock_gen.call_args.kwargs.get("images_dir"), expected_images_dir)

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

            imported_payload = {
                "active_profile_id": "p1",
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


if __name__ == "__main__":
    unittest.main(verbosity=2)
