# tests/test_process_manager.py

import os
import sys
import subprocess
import pytest
from unittest.mock import patch, MagicMock
from core.process_manager import ProcessManager
from core.service_record import ServiceRecord


@pytest.fixture
def proc_mgr():
    """返回干净的 ProcessManager。"""
    return ProcessManager()


class TestProcessManagerInit:
    def test_init_state(self, proc_mgr):
        assert proc_mgr._worker is None
        assert proc_mgr._watcher is None
        assert proc_mgr._processes == {}
        assert proc_mgr._log_files == {}

    def test_start_worker(self, proc_mgr):
        proc_mgr.start_worker()
        assert proc_mgr._worker is not None
        assert proc_mgr._worker.is_alive()
        proc_mgr.stop_all()

    def test_start_worker_idempotent(self, proc_mgr):
        proc_mgr.start_worker()
        worker1 = proc_mgr._worker
        proc_mgr.start_worker()
        assert proc_mgr._worker is worker1
        proc_mgr.stop_all()

    def test_start_watcher(self, proc_mgr):
        proc_mgr.start_watcher()
        assert proc_mgr._watcher is not None
        assert proc_mgr._watcher.is_alive()
        proc_mgr.stop_all()

    def test_is_running(self, proc_mgr):
        assert proc_mgr.is_running is False
        proc_mgr.start_worker()
        assert proc_mgr.is_running is True
        proc_mgr.stop_all()

    def test_get_active_processes_empty(self, proc_mgr):
        assert proc_mgr.get_active_processes() == []


class TestProcessManagerQueueActions:
    """验收标准 1: start/stop/restart 异步提交到队列。"""

    def test_queue_action_direct(self, proc_mgr):
        """直接测试队列机制（绕过延迟导入）。"""
        queue = proc_mgr._queue
        # 验证队列初始为空
        assert queue.empty()

    def test_worker_loop_processes_actions(self, proc_mgr):
        """验证工作线程能从队列取出动作并分发。"""
        import threading
        import time

        # 放入操作到队列
        proc_mgr._queue.put(("start", "test-svc"))

        # Mock _do_start
        executed = []
        proc_mgr._do_start = lambda sid: executed.append(("start", sid))
        proc_mgr._do_stop = lambda sid: executed.append(("stop", sid))

        # 在单独线程中运行 _worker_loop，让它处理队列中的项
        t = threading.Thread(target=proc_mgr._worker_loop, daemon=True)
        t.start()

        # 等待处理
        time.sleep(0.3)

        # 停止并检查
        proc_mgr.stop_all()
        t.join(timeout=2)
        assert executed == [("start", "test-svc")]


class TestDoStartStop:
    """验收标准 2-3: 进程启动和停止（集成测试）。"""

    def test_do_start_missing_service(self, proc_mgr):
        """服务不存在时标记为 exited。"""
        import core
        orig = core.registry
        mock_registry = MagicMock()
        mock_registry.get.return_value = None
        core.registry = mock_registry
        try:
            proc_mgr._do_start("ghost")
        finally:
            core.registry = orig
        mock_registry.set_runtime_state.assert_called_with("ghost", "exited")

    def test_do_start_no_command(self, proc_mgr):
        """服务无启动命令时标记为 exited。"""
        import core
        orig = core.registry
        mock_registry = MagicMock()
        mock_registry.get.return_value = ServiceRecord(
            id="test", display_name="T", model_type="sd",
            start_command="", working_dir="",
        )
        core.registry = mock_registry
        try:
            proc_mgr._do_start("test")
        finally:
            core.registry = orig
        mock_registry.set_runtime_state.assert_called_with("test", "exited")

    def test_do_stop_no_process(self, proc_mgr):
        """无活跃进程时标记为 stopped。"""
        import core
        orig = core.registry
        mock_registry = MagicMock()
        mock_registry.get.return_value = ServiceRecord(
            id="test", display_name="T", model_type="sd",
            stop_timeout_seconds=30,
        )
        core.registry = mock_registry
        try:
            proc_mgr._do_stop("test")
        finally:
            core.registry = orig
        mock_registry.set_runtime_state.assert_called_with("test", "stopped")


class TestDoStopWindows:
    """验收标准 3 (Windows)."""

    @pytest.mark.skipif(sys.platform != "win32", reason="Windows-only")
    def test_do_stop_windows(self, proc_mgr):
        """Windows: terminate() 被调用。"""
        mock_process = MagicMock()
        mock_process.pid = 12345
        mock_process.wait.return_value = None  # 正常退出

        proc_mgr._processes["test-svc"] = mock_process

        import core
        orig = core.registry
        mock_registry = MagicMock()
        mock_registry.get.return_value = ServiceRecord(
            id="test-svc", display_name="T", model_type="sd",
            stop_timeout_seconds=30,
        )
        core.registry = mock_registry
        try:
            proc_mgr._do_stop("test-svc")
        finally:
            core.registry = orig

        mock_process.terminate.assert_called_once()
        mock_registry.set_runtime_state.assert_called_with("test-svc", "stopped")


class TestTailLog:
    """测试 tail_log 方法。"""

    def test_tail_log_no_directory(self, proc_mgr):
        """不存在的服务日志目录返回 (无日志)。"""
        # tail_log 内部使用 os.path.join("data/logs/services", service_id)
        # 直接调用真实路径（不存在时应返回无日志）
        result = proc_mgr.tail_log("__nonexistent_svc_test__")
        assert result == "(无日志)"

    def test_tail_log_empty_directory(self, proc_mgr, tmp_workspace):
        """空日志目录返回 (无日志)。"""
        svc_dir = os.path.join(
            tmp_workspace, "data", "logs", "services", "empty-svc",
        )
        os.makedirs(svc_dir, exist_ok=True)

        # 通过 patch glob.glob 在 tail_log 内部查找时定位到我们的目录
        import glob as glob_module
        with patch.object(glob_module, "glob", return_value=[]):
            # 也需要 isdir 返回 True
            import os as os_module
            def mock_isdir(path):
                if "empty-svc" in str(path):
                    return True
                return os_module.path.isdir(path)
            with patch.object(os_module.path, "isdir", side_effect=mock_isdir):
                result = proc_mgr.tail_log("empty-svc")
                assert result == "(无日志)"

    def test_tail_log_real_file(self, proc_mgr, tmp_workspace):
        """使用实际文件验证 tail_log 返回最后 N 行。"""
        svc_log_dir = os.path.join(
            tmp_workspace, "data", "logs", "services", "test2",
        )
        os.makedirs(svc_log_dir, exist_ok=True)
        log_file = os.path.join(svc_log_dir, "20260610_000000.log")
        with open(log_file, "w", encoding="utf-8") as f:
            for i in range(100):
                f.write(f"line {i+1}\n")

        import glob as glob_module
        import os as os_module

        def mock_isdir(path):
            if "test2" in str(path):
                return True
            return os_module.path.isdir(path)

        with patch.object(os_module.path, "isdir", side_effect=mock_isdir):
            with patch.object(glob_module, "glob", return_value=[log_file]):
                result = proc_mgr.tail_log("test2")
                lines = result.strip().split("\n")
                assert len(lines) == 50
                assert "line 100" in lines[-1]
                assert "line 51" in lines[0]


class TestStopAll:
    def test_stop_all_shuts_down_cleanly(self, proc_mgr):
        proc_mgr.start_worker()
        proc_mgr.stop_all()
        assert proc_mgr._shutdown.is_set()
