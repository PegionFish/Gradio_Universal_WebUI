# 模块 6：任务管理与结果存储

## 用途

`TaskScheduler` 在 SQLite 中持久化任务队列和任务历史。`ResultManager` 在 `data/jobs/` 中管理任务结果文件。

## 依赖

- **模块 1**：项目骨架（`data/tasks.sqlite3`、`data/jobs/` 目录）
- **模块 3**：EventBus（任务事件通知）

## TaskScheduler

### 文件位置

`core/task_scheduler.py`

### SQLite 数据库

```text
data/tasks.sqlite3
```

首次使用时自动创建。不需要迁移版本管理——第一阶段只有一张表，若添加新表请先检查 `CREATE TABLE IF NOT EXISTS`。

### DDL

```sql
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
```

### 实现

```python
import sqlite3
import uuid
import datetime
import json
import threading
import logging
from core.event_bus import bus, Event

logger = logging.getLogger("core.task_scheduler")


class TaskScheduler:
    def __init__(self, db_path: str = "data/tasks.sqlite3"):
        self._db_path = db_path
        self._lock = threading.Lock()
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self._init_db()
    
    def _init_db(self):
        """初始化数据库表结构。"""
        with self._get_conn() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS tasks (
                    id TEXT PRIMARY KEY,
                    service_id TEXT NOT NULL,
                    model_type TEXT NOT NULL,
                    adapter_name TEXT NOT NULL,
                    request_payload TEXT NOT NULL,
                    target_gpu TEXT,
                    status TEXT NOT NULL DEFAULT 'queued',
                    created_at TEXT NOT NULL,
                    started_at TEXT,
                    finished_at TEXT,
                    result_paths TEXT,
                    error_summary TEXT,
                    error_detail TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);
                CREATE INDEX IF NOT EXISTS idx_tasks_service_id ON tasks(service_id);
                CREATE INDEX IF NOT EXISTS idx_tasks_created_at ON tasks(created_at);
            """)
    
    def _get_conn(self) -> sqlite3.Connection:
        """获取新数据库连接。线程安全要求每个线程使用独立连接。"""
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn
    
    def create_task(self, service_id: str, model_type: str,
                    adapter_name: str, request_payload: dict,
                    target_gpu: list[int] | None = None) -> str:
        """创建新任务并写入 SQLite。返回任务 ID。"""
        task_id = str(uuid.uuid4())
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        
        with self._lock:
            with self._get_conn() as conn:
                conn.execute(
                    """INSERT INTO tasks
                       (id, service_id, model_type, adapter_name, request_payload,
                        target_gpu, status, created_at)
                       VALUES (?, ?, ?, ?, ?, ?, 'queued', ?)""",
                    (task_id, service_id, model_type, adapter_name,
                     json.dumps(request_payload, ensure_ascii=False),
                     json.dumps(target_gpu) if target_gpu else None,
                     now)
                )
                conn.commit()
        
        bus.emit(Event("task_created", {
            "task_id": task_id,
            "service_id": service_id,
        }))
        return task_id
    
    def update_task_status(self, task_id: str, status: str,
                           error_summary: str | None = None,
                           error_detail: str | None = None,
                           result_paths: list[str] | None = None):
        """更新任务状态。status 必须为有效值。"""
        VALID_STATUSES = {"queued", "running", "completed", "failed", "cancelled"}
        if status not in VALID_STATUSES:
            raise ValueError(f"无效状态: {status}")
        
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
                    params
                )
                conn.commit()
        
        if status in ("completed", "failed", "cancelled"):
            bus.emit(Event("task_completed", {
                "task_id": task_id,
                "status": status,
            }))
    
    def get_task(self, task_id: str) -> dict | None:
        with self._get_conn() as conn:
            row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
            if row:
                return dict(row)
            return None
    
    def list_tasks(self, service_id: str | None = None,
                   status: str | None = None,
                   limit: int = 100) -> list[dict]:
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
        return self.list_tasks(service_id=service_id, status="running")
    
    def cancel_task(self, task_id: str):
        """取消排队中的任务。运行中的任务不可取消（第二阶段实现）。"""
        self.update_task_status(task_id, "cancelled")
```

### 任务状态机

```
                     用户提交
                         │
                         ▼
      ┌───────────── queued ─────────────┐
      │              │    │               │
      │   服务开始处理 │    │ 用户手动取消   │
      │              ▼    ▼               │
      │  ┌─────── running                 │
      │  │    ╱    │    ╲                 │
      │  │ 成功   失败  服务中断            │
      │  ▼       ▼       ▼                │
      │ completed  failed  failed(service stopped)
      │                                    │
      └──────────────── cancelled ◄────────┘
```

## ResultManager

### 文件位置

`core/result_manager.py`

### 实现

```python
import os
import json
import datetime


class ResultManager:
    def __init__(self, base_dir: str = "data/jobs/"):
        self._base_dir = base_dir
    
    def task_dir(self, task_id: str) -> str:
        """返回任务目录路径。"""
        return os.path.join(self._base_dir, "tasks", task_id)
    
    def ensure_task_dir(self, task_id: str) -> str:
        """创建任务目录并返回路径。"""
        path = self.task_dir(task_id)
        os.makedirs(os.path.join(path, "logs"), exist_ok=True)
        os.makedirs(os.path.join(path, "outputs"), exist_ok=True)
        return path
    
    def save_request(self, task_id: str, payload: dict):
        """保存请求负载到 request.json。"""
        path = os.path.join(self.task_dir(task_id), "request.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
    
    def save_response(self, task_id: str, response: dict):
        """保存输出元数据到 response.json。"""
        path = os.path.join(self.task_dir(task_id), "response.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(response, f, ensure_ascii=False, indent=2)
    
    def save_log(self, task_id: str, log_name: str, content: str):
        """保存日志片段到 logs/ 目录。"""
        path = os.path.join(self.task_dir(task_id), "logs", log_name)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
    
    def get_output_path(self, task_id: str, filename: str) -> str:
        """返回 outputs/ 下某个文件的路径。"""
        return os.path.join(self.task_dir(task_id), "outputs", filename)
    
    def list_outputs(self, task_id: str) -> list[str]:
        """列出 outputs/ 下的所有文件。"""
        outputs_dir = os.path.join(self.task_dir(task_id), "outputs")
        if os.path.isdir(outputs_dir):
            return os.listdir(outputs_dir)
        return []
```

## 集成点

### TaskScheduler + ResultManager 在任务提交中的使用

```python
# webui/pages/stable_diffusion.py 回调示例
def on_submit(service_id, prompt, target_gpu):
    # 1. 创建任务记录
    task_id = scheduler.create_task(
        service_id=service_id,
        model_type="stable-diffusion",
        adapter_name="StableDiffusionAdapter",
        request_payload={"prompt": prompt, "steps": 20},
        target_gpu=parse_gpu_list(target_gpu),
    )
    
    # 2. 创建结果目录
    result_mgr.ensure_task_dir(task_id)
    result_mgr.save_request(task_id, {"prompt": prompt})
    
    # 3. 通过适配器提交（第二阶段）
    # ...
    
    return task_id
```

### 在 main.py 中的集成

```python
from core.task_scheduler import TaskScheduler
from core.result_manager import ResultManager

scheduler = TaskScheduler(db_path="data/tasks.sqlite3")
result_mgr = ResultManager(base_dir="data/jobs/")
```

## 验收标准

1. 首次初始化时自动创建 SQLite 数据库和索引
2. `create_task()` 返回 UUID v4 格式的 ID
3. `get_task()` 返回正确的任务记录
4. `list_tasks(service_id="sd-webui")` 只返回该服务的任务
5. `update_task_status(...)` 正确修改状态和时间戳
6. 非法状态值抛出 `ValueError`
7. `cancel_task()` 将排队中任务标记为 `cancelled`
8. `ResultManager.ensure_task_dir()` 创建 `data/jobs/tasks/<task_id>/logs/` 和 `outputs/`
9. `save_request()` / `save_response()` 写入正确的 JSON
10. 并发创建任务时无 SQLite 竞争问题（借助 `threading.Lock` + WAL 模式）
