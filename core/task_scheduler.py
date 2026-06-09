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

VALID_STATUSES = {"queued", "running", "completed", "failed", "cancelled"}


class TaskScheduler:
    """SQLite 持久化的任务调度器。

    每个线程使用独立数据库连接（sqlite3 线程安全规则）。
    写操作通过 threading.Lock 序列化以确保并发安全。
    """

    def __init__(self, db_path: str = "data/tasks.sqlite3"):
        self._db_path = db_path
        self._lock = threading.Lock()
        os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
        self._init_db()

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
                    error_detail    TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);
                CREATE INDEX IF NOT EXISTS idx_tasks_service_id ON tasks(service_id);
                CREATE INDEX IF NOT EXISTS idx_tasks_created_at ON tasks(created_at);
            """)
        logger.debug("TaskScheduler 数据库已初始化: %s", self._db_path)

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
    ) -> str:
        """创建新任务并写入 SQLite。返回任务 ID (UUID v4)。"""
        task_id = str(uuid.uuid4())
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()

        with self._lock:
            with self._get_conn() as conn:
                conn.execute(
                    """INSERT INTO tasks
                       (id, service_id, model_type, adapter_name, request_payload,
                        target_gpu, status, created_at)
                       VALUES (?, ?, ?, ?, ?, ?, 'queued', ?)""",
                    (
                        task_id, service_id, model_type, adapter_name,
                        json.dumps(request_payload, ensure_ascii=False),
                        json.dumps(target_gpu) if target_gpu else None,
                        now,
                    ),
                )
                conn.commit()

        bus.emit(Event("task_created", {
            "task_id": task_id,
            "service_id": service_id,
        }))
        logger.info("任务已创建: id=%s service=%s model=%s", task_id, service_id, model_type)
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
        """获取任务所属 service_id（不暴露完整记录时使用）。"""
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT service_id FROM tasks WHERE id = ?", (task_id,)
            ).fetchone()
            return row["service_id"] if row else ""

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
        """列出任务。可按 service_id 和 status 筛选。

        Args:
            service_id: 可选的服务 ID 筛选
            status: 可选的状态筛选
            limit: 最大返回数（默认 100）
        """
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

    # ── 取消 ──

    def cancel_task(self, task_id: str):
        """取消排队中的任务。运行中的任务不可取消（第二阶段实现）。"""
        self.update_task_status(task_id, "cancelled")
        logger.info("任务已取消: id=%s", task_id)
