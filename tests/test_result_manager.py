# tests/test_result_manager.py

import os
import json
import pytest
from core.result_manager import ResultManager


class TestResultManagerDirs:
    """验收标准 8: ensure_task_dir 创建正确的目录结构。"""

    def test_task_dir_returns_correct_path(self, result_mgr):
        expected = os.path.join(result_mgr._base_dir, "tasks", "test-id")
        assert result_mgr.task_dir("test-id") == expected

    def test_ensure_task_dir_creates_dirs(self, result_mgr):
        path = result_mgr.ensure_task_dir("task-123")
        assert os.path.isdir(path)
        assert os.path.isdir(os.path.join(path, "logs"))
        assert os.path.isdir(os.path.join(path, "outputs"))

    def test_ensure_task_dir_is_idempotent(self, result_mgr):
        result_mgr.ensure_task_dir("task-1")
        result_mgr.ensure_task_dir("task-1")  # 不应报错


class TestSaveRequestResponse:
    """验收标准 9: save_request/save_response 写入正确的 JSON。"""

    def test_save_request_writes_json(self, result_mgr):
        result_mgr.save_request("task-1", {"prompt": "hello", "steps": 20})
        path = os.path.join(result_mgr.task_dir("task-1"), "request.json")
        with open(path) as f:
            data = json.load(f)
        assert data["prompt"] == "hello"
        assert data["steps"] == 20

    def test_save_response_writes_json(self, result_mgr):
        result_mgr.save_response("task-1", {"output": "result.png", "status": "done"})
        path = os.path.join(result_mgr.task_dir("task-1"), "response.json")
        with open(path) as f:
            data = json.load(f)
        assert data["status"] == "done"

    def test_save_request_unicode(self, result_mgr):
        result_mgr.save_request("task-1", {"prompt": "一只猫"})
        path = os.path.join(result_mgr.task_dir("task-1"), "request.json")
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        assert data["prompt"] == "一只猫"


class TestSaveLog:
    def test_save_log_writes_content(self, result_mgr):
        result_mgr.ensure_task_dir("task-1")
        result_mgr.save_log("task-1", "stderr.log", "error output\nline 2")
        path = os.path.join(result_mgr.task_dir("task-1"), "logs", "stderr.log")
        assert os.path.exists(path)
        with open(path) as f:
            assert f.read() == "error output\nline 2"


class TestOutputFiles:
    def test_get_output_path(self, result_mgr):
        path = result_mgr.get_output_path("task-id", "image.png")
        assert path.endswith(os.path.join("tasks", "task-id", "outputs", "image.png"))

    def test_list_outputs_empty(self, result_mgr):
        result_mgr.ensure_task_dir("task-1")
        assert result_mgr.list_outputs("task-1") == []

    def test_list_outputs_with_files(self, result_mgr):
        result_mgr.ensure_task_dir("task-1")
        out_dir = os.path.join(result_mgr.task_dir("task-1"), "outputs")
        with open(os.path.join(out_dir, "a.png"), "w") as f:
            f.write("")
        with open(os.path.join(out_dir, "b.txt"), "w") as f:
            f.write("")
        files = result_mgr.list_outputs("task-1")
        assert "a.png" in files
        assert "b.txt" in files
