# core/result_manager.py — 结果管理器，data/jobs/ 下的任务结果文件管理

import os
import json
import logging

logger = logging.getLogger(__name__)


class ResultManager:
    """管理任务结果文件的存储和检索。

    文件布局:
        data/jobs/tasks/<task_id>/
        ├── request.json
        ├── response.json
        ├── logs/
        │   └── <log_name>
        └── outputs/
            └── <output_file>
    """

    def __init__(self, base_dir: str = "data/jobs/"):
        self._base_dir = base_dir

    # ── 目录管理 ──

    def task_dir(self, task_id: str) -> str:
        """返回任务目录路径（不创建）。"""
        return os.path.join(self._base_dir, "tasks", task_id)

    def ensure_task_dir(self, task_id: str) -> str:
        """创建任务目录（含 logs/ 和 outputs/ 子目录）并返回路径。"""
        path = self.task_dir(task_id)
        os.makedirs(os.path.join(path, "logs"), exist_ok=True)
        os.makedirs(os.path.join(path, "outputs"), exist_ok=True)
        logger.debug("任务目录已创建: %s", path)
        return path

    # ── 请求/响应持久化 ──

    def save_request(self, task_id: str, payload: dict):
        """保存请求负载到 request.json。"""
        path = os.path.join(self._ensure_dir(task_id), "request.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)

    def save_response(self, task_id: str, response: dict):
        """保存输出元数据到 response.json。"""
        path = os.path.join(self._ensure_dir(task_id), "response.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(response, f, ensure_ascii=False, indent=2)

    # ── 日志 ──

    def save_log(self, task_id: str, log_name: str, content: str):
        """保存日志片段到 logs/ 目录。"""
        path = os.path.join(self._ensure_dir(task_id), "logs", log_name)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)

    # ── 输出文件 ──

    def get_output_path(self, task_id: str, filename: str) -> str:
        """返回 outputs/ 下某个文件的完整路径。"""
        path = os.path.join(self.task_dir(task_id), "outputs", filename)
        return path

    def list_outputs(self, task_id: str) -> list[str]:
        """列出 outputs/ 下的所有文件名。"""
        outputs_dir = os.path.join(self.task_dir(task_id), "outputs")
        if os.path.isdir(outputs_dir):
            return os.listdir(outputs_dir)
        return []

    # ── 内部 ──

    def _ensure_dir(self, task_id: str) -> str:
        """确保任务根目录存在（不含子目录），返回路径。"""
        path = self.task_dir(task_id)
        os.makedirs(path, exist_ok=True)
        return path
