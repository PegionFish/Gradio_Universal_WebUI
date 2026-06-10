# tests/test_task_scheduler.py

import json
import pytest
from core.task_scheduler import TaskScheduler, VALID_STATUSES


class TestTaskSchedulerInit:
    """验收标准 1: 首次初始化时自动创建 SQLite 数据库和索引。"""

    def test_db_created_on_init(self, tmp_workspace):
        import os
        db_path = os.path.join(tmp_workspace, "tasks.sqlite3")
        scheduler = TaskScheduler(db_path=db_path)
        assert os.path.exists(db_path)

    def test_init_is_idempotent(self, tmp_workspace):
        import os
        db_path = os.path.join(tmp_workspace, "tasks.sqlite3")
        TaskScheduler(db_path=db_path)
        TaskScheduler(db_path=db_path)  # 不应报错


class TestCreateTask:
    """验收标准 2: create_task() 返回 UUID v4 格式的 ID。"""

    def test_create_task_returns_uuid(self, scheduler):
        task_id = scheduler.create_task(
            service_id="sd-1",
            model_type="stable-diffusion",
            adapter_name="SDAdapter",
            request_payload={"prompt": "test"},
        )
        assert len(task_id) == 36
        assert task_id.count("-") == 4

    def test_create_task_stores_correct_data(self, scheduler):
        task_id = scheduler.create_task(
            service_id="sd-1",
            model_type="stable-diffusion",
            adapter_name="SDAdapter",
            request_payload={"prompt": "hello"},
            target_gpu=[0],
        )
        task = scheduler.get_task(task_id)
        assert task is not None
        assert task["service_id"] == "sd-1"
        assert task["status"] == "queued"
        assert json.loads(task["request_payload"]) == {"prompt": "hello"}
        assert json.loads(task["target_gpu"]) == [0]

    def test_create_task_publishes_event(self, scheduler):
        from core.event_bus import bus
        events = []
        bus.on("task_created", lambda e: events.append(e))

        task_id = scheduler.create_task(
            service_id="sd-1", model_type="sd", adapter_name="A",
            request_payload={},
        )
        assert len(events) == 1
        assert events[0].data["task_id"] == task_id
        bus.clear()


class TestGetTask:
    """验收标准 3: get_task() 返回正确的任务记录。"""

    def test_get_task_returns_all_fields(self, scheduler):
        task_id = scheduler.create_task(
            service_id="svc", model_type="m", adapter_name="a",
            request_payload={"x": 1},
        )
        task = scheduler.get_task(task_id)
        assert task["service_id"] == "svc"
        assert task["model_type"] == "m"
        assert task["adapter_name"] == "a"
        assert task["created_at"] is not None

    def test_get_task_nonexistent(self, scheduler):
        assert scheduler.get_task("nonexistent-id") is None


class TestListTasks:
    """验收标准 4: list_tasks 筛选功能。"""

    def test_list_all(self, scheduler):
        scheduler.create_task("sd-1", "m", "a", {})
        scheduler.create_task("asr-1", "m", "a", {})
        tasks = scheduler.list_tasks()
        assert len(tasks) >= 2

    def test_filter_by_service(self, scheduler):
        scheduler.create_task("sd-1", "m", "a", {})
        scheduler.create_task("asr-1", "m", "a", {})
        tasks = scheduler.list_tasks(service_id="sd-1")
        assert all(t["service_id"] == "sd-1" for t in tasks)

    def test_filter_by_status(self, scheduler):
        sid = scheduler.create_task("sd-1", "m", "a", {})
        scheduler.update_task_status(sid, "running")
        running = scheduler.list_tasks(status="running")
        assert all(t["status"] == "running" for t in running)

    def test_limit(self, scheduler):
        for i in range(10):
            scheduler.create_task(f"svc-{i}", "m", "a", {})
        tasks = scheduler.list_tasks(limit=3)
        assert len(tasks) <= 3

    def test_order_desc_by_created_at(self, scheduler):
        id1 = scheduler.create_task("s1", "m", "a", {"idx": 1})
        id2 = scheduler.create_task("s2", "m", "a", {"idx": 2})
        tasks = scheduler.list_tasks()
        # 最新创建的任务排最前
        assert tasks[0]["id"] == id2
        assert tasks[1]["id"] == id1


class TestUpdateTaskStatus:
    """验收标准 5: update_task_status 正确修改状态和时间戳。"""

    def test_update_to_running_sets_started_at(self, scheduler):
        task_id = scheduler.create_task("svc", "m", "a", {})
        scheduler.update_task_status(task_id, "running")
        task = scheduler.get_task(task_id)
        assert task["status"] == "running"
        assert task["started_at"] is not None

    def test_update_to_completed_sets_finished_at(self, scheduler):
        task_id = scheduler.create_task("svc", "m", "a", {})
        scheduler.update_task_status(task_id, "completed")
        task = scheduler.get_task(task_id)
        assert task["status"] == "completed"
        assert task["finished_at"] is not None

    def test_update_stores_error_info(self, scheduler):
        task_id = scheduler.create_task("svc", "m", "a", {})
        scheduler.update_task_status(
            task_id, "failed",
            error_summary="Connection refused",
            error_detail="Traceback...",
        )
        task = scheduler.get_task(task_id)
        assert task["error_summary"] == "Connection refused"
        assert task["error_detail"] == "Traceback..."

    def test_update_stores_result_paths(self, scheduler):
        task_id = scheduler.create_task("svc", "m", "a", {})
        scheduler.update_task_status(
            task_id, "completed",
            result_paths=["/output/img.png", "/output/log.txt"],
        )
        task = scheduler.get_task(task_id)
        paths = json.loads(task["result_paths"])
        assert paths == ["/output/img.png", "/output/log.txt"]

    def test_update_publishes_task_completed_event(self, scheduler):
        from core.event_bus import bus
        events = []
        bus.on("task_completed", lambda e: events.append(e))

        task_id = scheduler.create_task("svc", "m", "a", {})
        scheduler.update_task_status(task_id, "completed")
        assert len(events) == 1
        assert events[0].data["task_id"] == task_id
        assert events[0].data["status"] == "completed"
        bus.clear()

    def test_update_publishes_failed_event(self, scheduler):
        from core.event_bus import bus
        events = []
        bus.on("task_completed", lambda e: events.append(e))
        task_id = scheduler.create_task("svc", "m", "a", {})
        scheduler.update_task_status(task_id, "failed")
        assert len(events) == 1
        bus.clear()


class TestInvalidStatus:
    """验收标准 6: 非法状态值抛出 ValueError。"""

    def test_invalid_status_raises(self, scheduler):
        task_id = scheduler.create_task("s", "m", "a", {})
        with pytest.raises(ValueError, match="无效状态"):
            scheduler.update_task_status(task_id, "pending")


class TestCancelTask:
    """验收标准 7: cancel_task() 将排队中任务标记为 cancelled。"""

    def test_cancel_queued_task(self, scheduler):
        task_id = scheduler.create_task("s", "m", "a", {})
        scheduler.cancel_task(task_id)
        task = scheduler.get_task(task_id)
        assert task["status"] == "cancelled"

    def test_cancel_already_running(self, scheduler):
        task_id = scheduler.create_task("s", "m", "a", {})
        scheduler.update_task_status(task_id, "running")
        scheduler.cancel_task(task_id)
        task = scheduler.get_task(task_id)
        assert task["status"] == "cancelled"  # 当前允许取消运行中任务


class TestGetRunningTasks:
    def test_returns_only_running(self, scheduler):
        sid1 = scheduler.create_task("s1", "m", "a", {})
        sid2 = scheduler.create_task("s1", "m", "a", {})
        scheduler.update_task_status(sid1, "running")
        running = scheduler.get_running_tasks("s1")
        assert len(running) == 1
        assert running[0]["id"] == sid1
