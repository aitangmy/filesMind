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
    sys.modules["parser_service"] = parser_service

    cognitive_engine = types.ModuleType("cognitive_engine")
    cognitive_engine.generate_mindmap_structure = lambda *args, **kwargs: "# dummy"
    cognitive_engine.update_client_config = lambda *args, **kwargs: None
    cognitive_engine.set_model = lambda *args, **kwargs: None
    cognitive_engine.set_account_type = lambda *args, **kwargs: None

    async def _test_connection(*args, **kwargs):
        return {"success": True, "message": "ok"}

    cognitive_engine.test_connection = _test_connection
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


if __name__ == "__main__":
    unittest.main(verbosity=2)
