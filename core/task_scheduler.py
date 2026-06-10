# core/task_scheduler.py — 任务调度器，SQLite 支撑的任务队列和历史

import sqlite3
import uuid
import datetime
import json
import os
import threading
import logging
from core.event_bus import bus, Event

logger = logging.getLogger(__name__)

VALID_STATUSES = {"queued", "running", "completed", "failed", "cancelled", "retrying"}
DEFAULT_MAX_RETRIES = 3


class TaskScheduler:
    """SQLite 持久化的任务调度器。

    Phase 3 增强:
    - retry_count / max_retries 支持自动重试
    - cancel_running_task() 支持取消运行中任务（含进程管理集成）
    - retry_task() 将失败任务重新入队
    """

    def __init__(self, db_path: str = "data/tasks.sqlite3"):
        self._db_path = db_path
        self._lock = threading.Lock()
        os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
        self._init_db()
        self._migrate()

    # ── 数据库初始化 ──

    def _init_db(self):
        """初始化数据库表结构。幂等。"""
        with self._get_conn() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS tasks (
                    id              TEXT PRIMARY KEY,
                    service_id      TEXT NOT NULL,
                    model_type      TEXT NOT NULL,
                    adapter_name    TEXT NOT NULL,
                    request_payload TEXT NOT NULL,
                    target_gpu      TEXT,
                    status          TEXT NOT NULL DEFAULT 'queued',
                    created_at      TEXT NOT NULL,
                    started_at      TEXT,
                    finished_at     TEXT,
                    result_paths    TEXT,
                    error_summary   TEXT,
                    error_detail    TEXT,
                    retry_count     INTEGER NOT NULL DEFAULT 0,
                    max_retries     INTEGER NOT NULL DEFAULT 3
                );
                CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);
                CREATE INDEX IF NOT EXISTS idx_tasks_service_id ON tasks(service_id);
                CREATE INDEX IF NOT EXISTS idx_tasks_created_at ON tasks(created_at);
            """)
        logger.debug("TaskScheduler 数据库已初始化: %s", self._db_path)

    def _migrate(self):
        """Phase 3 迁移：为旧表添加 retry_count/max_retries 列。"""
        try:
            with self._get_conn() as conn:
                conn.execute(
                    "ALTER TABLE tasks ADD COLUMN retry_count INTEGER NOT NULL DEFAULT 0"
                )
        except sqlite3.OperationalError:
            pass  # 列已存在
        try:
            with self._get_conn() as conn:
                conn.execute(
                    "ALTER TABLE tasks ADD COLUMN max_retries INTEGER NOT NULL DEFAULT 3"
                )
        except sqlite3.OperationalError:
            pass

    def _get_conn(self) -> sqlite3.Connection:
        """获取新数据库连接。线程安全要求每个线程使用独立连接。"""
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    # ── 任务创建 ──

    def create_task(
        self,
        service_id: str,
        model_type: str,
        adapter_name: str,
        request_payload: dict,
        target_gpu: list[int] | None = None,
        max_retries: int = DEFAULT_MAX_RETRIES,
    ) -> str:
        """创建新任务并写入 SQLite。返回任务 ID (UUID v4)。

        Args:
            service_id: 服务 ID
            model_type: 模型类型
            adapter_name: 适配器名称
            request_payload: 请求负载
            target_gpu: 目标 GPU 列表
            max_retries: 最大重试次数（默认 3，0 表示不重试）
        """
        task_id = str(uuid.uuid4())
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()

        with self._lock:
            with self._get_conn() as conn:
                conn.execute(
                    """INSERT INTO tasks
                       (id, service_id, model_type, adapter_name, request_payload,
                        target_gpu, status, created_at, retry_count, max_retries)
                       VALUES (?, ?, ?, ?, ?, ?, 'queued', ?, 0, ?)""",
                    (
                        task_id, service_id, model_type, adapter_name,
                        json.dumps(request_payload, ensure_ascii=False),
                        json.dumps(target_gpu) if target_gpu else None,
                        now,
                        max_retries,
                    ),
                )
                conn.commit()

        bus.emit(Event("task_created", {
            "task_id": task_id,
            "service_id": service_id,
        }))
        logger.info("任务已创建: id=%s service=%s model=%s (max_retries=%d)",
                     task_id, service_id, model_type, max_retries)
        return task_id

    # ── 状态更新 ──

    def update_task_status(
        self,
        task_id: str,
        status: str,
        error_summary: str | None = None,
        error_detail: str | None = None,
        result_paths: list[str] | None = None,
    ):
        """更新任务状态。status 必须为有效值。

        Raises:
            ValueError: status 不在 VALID_STATUSES 中
        """
        if status not in VALID_STATUSES:
            raise ValueError(
                f"无效状态: '{status}'，有效值为: {', '.join(sorted(VALID_STATUSES))}"
            )

        now = datetime.datetime.now(datetime.timezone.utc).isoformat()

        with self._lock:
            with self._get_conn() as conn:
                updates = ["status = ?"]
                params = [status]

                if status == "running":
                    updates.append("started_at = ?")
                    params.append(now)
                elif status in ("completed", "failed", "cancelled"):
                    updates.append("finished_at = ?")
                    params.append(now)

                if error_summary is not None:
                    updates.append("error_summary = ?")
                    params.append(error_summary)
                if error_detail is not None:
                    updates.append("error_detail = ?")
                    params.append(error_detail)
                if result_paths is not None:
                    updates.append("result_paths = ?")
                    params.append(json.dumps(result_paths))

                params.append(task_id)
                conn.execute(
                    f"UPDATE tasks SET {', '.join(updates)} WHERE id = ?",
                    params,
                )
                conn.commit()

        if status in ("completed", "failed", "cancelled"):
            bus.emit(Event("task_completed", {
                "task_id": task_id,
                "service_id": self._get_task_service(task_id),
                "status": status,
            }))
            logger.info("任务完成: id=%s status=%s", task_id, status)

    def _get_task_service(self, task_id: str) -> str:
        """获取任务所属 service_id。"""
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT service_id FROM tasks WHERE id = ?", (task_id,)
            ).fetchone()
            return row["service_id"] if row else ""

    # ── 重试 ──

    def retry_task(self, task_id: str) -> bool:
        """将失败任务重新入队（如果还有重试次数）。

        Returns:
            True 如果任务已重试，False 如果超出重试次数或任务不存在。
        """
        with self._lock:
            with self._get_conn() as conn:
                row = conn.execute(
                    "SELECT status, retry_count, max_retries FROM tasks WHERE id = ?",
                    (task_id,),
                ).fetchone()

                if not row:
                    logger.warning("重试失败: 任务 %s 不存在", task_id)
                    return False

                current_count = row["retry_count"]
                max_retries = row["max_retries"]

                if current_count >= max_retries:
                    logger.warning(
                        "任务 %s 已达到最大重试次数 (%d/%d)",
                        task_id, current_count, max_retries,
                    )
                    return False

                new_count = current_count + 1
                conn.execute(
                    """UPDATE tasks SET status = 'queued', retry_count = ?,
                       started_at = NULL, finished_at = NULL,
                       error_summary = NULL, error_detail = NULL
                       WHERE id = ?""",
                    (new_count, task_id),
                )
                conn.commit()

        bus.emit(Event("task_created", {
            "task_id": task_id,
            "service_id": self._get_task_service(task_id),
        }))
        logger.info(
            "任务重试: id=%s (第 %d/%d 次)",
            task_id, new_count, max_retries,
        )
        return True

    def auto_retry_failed(self, service_id: str | None = None) -> int:
        """自动重试所有失败且未超出重试次数的任务。

        Returns:
            成功重新入队的任务数。
        """
        tasks = self.list_tasks(service_id=service_id, status="failed")
        count = 0
        for t in tasks:
            if self.retry_task(t["id"]):
                count += 1
        return count

    # ── 查询 ──

    def get_task(self, task_id: str) -> dict | None:
        """获取单个任务记录。"""
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT * FROM tasks WHERE id = ?", (task_id,)
            ).fetchone()
            return dict(row) if row else None

    def list_tasks(
        self,
        service_id: str | None = None,
        status: str | None = None,
        limit: int = 100,
    ) -> list[dict]:
        """列出任务。可按 service_id 和 status 筛选。"""
        query = "SELECT * FROM tasks"
        conditions = []
        params = []

        if service_id:
            conditions.append("service_id = ?")
            params.append(service_id)
        if status:
            conditions.append("status = ?")
            params.append(status)

        if conditions:
            query += " WHERE " + " AND ".join(conditions)

        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)

        with self._get_conn() as conn:
            rows = conn.execute(query, params).fetchall()
            return [dict(r) for r in rows]

    def get_running_tasks(self, service_id: str) -> list[dict]:
        """获取指定服务所有运行中的任务。"""
        return self.list_tasks(service_id=service_id, status="running")

    def get_failed_retryable(self, service_id: str | None = None) -> list[dict]:
        """获取可重试的失败任务（retry_count < max_retries）。"""
        tasks = self.list_tasks(service_id=service_id, status="failed")
        return [
            t for t in tasks
            if t.get("retry_count", 0) < t.get("max_retries", DEFAULT_MAX_RETRIES)
        ]

    # ── 取消 ──

    def cancel_task(self, task_id: str):
        """取消排队中的任务。运行中任务通过 cancel_running_task 处理。"""
        task = self.get_task(task_id)
        if task and task["status"] == "running":
            self._cancel_running_task_internal(task_id, task)
        else:
            self.update_task_status(task_id, "cancelled")
        logger.info("任务已取消: id=%s", task_id)

    def _cancel_running_task_internal(self, task_id: str, task: dict):
        """内部：取消运行中的任务，尝试终止关联进程。"""
        self.update_task_status(
            task_id, "cancelled",
            error_summary="任务被用户取消",
            error_detail=f"任务 {task_id} 在运行中被取消",
        )

        # 尝试通过 ProcessManager 终止关联进程
        try:
            from core import process_manager
            service_id = task.get("service_id", "")
            if process_manager and service_id in process_manager.get_active_processes():
                logger.info(
                    "正在终止与已取消任务 %s 关联的服务 %s 的进程",
                    task_id, service_id,
                )
                # 发出事件通知 ProcessManager 可以终止
                bus.emit(Event("task_cancelled_running", {
                    "task_id": task_id,
                    "service_id": service_id,
                }))
        except Exception:
            pass

    def cancel_all_service_tasks(self, service_id: str) -> int:
        """取消指定服务的所有排队中任务。

        Returns:
            取消的任务数。
        """
        tasks = self.list_tasks(service_id=service_id, status="queued")
        for t in tasks:
            self.update_task_status(t["id"], "cancelled",
                                     error_summary="服务已停止")
        return len(tasks)

    # ── 统计 ──

    def get_stats(self, service_id: str | None = None) -> dict:
        """获取任务统计信息。"""
        with self._get_conn() as conn:
            if service_id:
                row = conn.execute(
                    """SELECT status, COUNT(*) as cnt FROM tasks
                       WHERE service_id = ? GROUP BY status""",
                    (service_id,),
                ).fetchall()
            else:
                row = conn.execute(
                    "SELECT status, COUNT(*) as cnt FROM tasks GROUP BY status"
                ).fetchall()

            stats = {s: 0 for s in VALID_STATUSES}
            for r in row:
                if r["status"] in stats:
                    stats[r["status"]] = r["cnt"]
            return stats
