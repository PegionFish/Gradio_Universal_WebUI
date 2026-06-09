# core/process_manager.py — 进程管理器，控制模型服务进程的生命周期

import queue
import threading
import subprocess
import signal
import os
import sys
import datetime
import logging

logger = logging.getLogger(__name__)

# 平台检测
_IS_WINDOWS = sys.platform == "win32"


class ProcessManager:
    """管理模型服务进程的生命周期（启动、停止、重启、监控）。

    线程模型：
    服务启动/停止/重启操作通过内部队列提交给工作线程执行。
    Gradio 回调仅负责向队列提交请求并立即返回，不阻塞主线程。
    """

    def __init__(self):
        self._processes: dict[str, subprocess.Popen] = {}
        self._log_files: dict[str, str] = {}
        self._shutdown = threading.Event()
        self._queue: queue.Queue = queue.Queue()
        self._worker: threading.Thread | None = None
        self._watcher: threading.Thread | None = None

    # ── 生命周期 ──

    def start_worker(self):
        """启动工作线程。由 main.py 在后台线程初始化阶段显式调用。

        不在 __init__ 中自动启动，以确保 ServiceRegistry 和配置已就绪。
        """
        if self._worker is not None:
            return
        self._worker = threading.Thread(
            target=self._worker_loop, daemon=True, name="proc-mgr"
        )
        self._worker.start()
        logger.info("ProcessManager 工作线程已启动")

    def start_watcher(self):
        """启动进程监控线程，每 15 秒检查存活。"""
        if self._watcher is not None:
            return

        def _watch():
            while not self._shutdown.is_set():
                for service_id, process in list(self._processes.items()):
                    if process.poll() is not None:
                        exit_code = process.returncode
                        logger.warning(
                            "服务 %s 意外退出 (exit code: %s)",
                            service_id, exit_code,
                        )
                        self._processes.pop(service_id, None)
                        # 延迟导入防止循环依赖
                        from core import registry
                        registry.set_runtime_state(service_id, "exited")
                self._shutdown.wait(15)

        self._watcher = threading.Thread(
            target=_watch, daemon=True, name="proc-watcher"
        )
        self._watcher.start()
        logger.info("ProcessManager 监控线程已启动")

    def stop_all(self):
        """停止所有运行中服务。在进程关闭时调用。"""
        logger.info("正在停止所有服务...")
        self._shutdown.set()
        for service_id in list(self._processes.keys()):
            self._do_stop(service_id)
        logger.info("所有服务已停止")

    # ── 公开接口（异步提交到队列）──

    def start(self, service_id: str):
        """异步启动服务。Gradio 回调可直接调用，不阻塞。"""
        from core import registry
        self._queue.put(("start", service_id))
        registry.set_runtime_state(service_id, "starting")

    def stop(self, service_id: str):
        """异步停止服务。"""
        from core import registry
        self._queue.put(("stop", service_id))
        registry.set_runtime_state(service_id, "stopping")

    def restart(self, service_id: str):
        """异步重启服务。"""
        from core import registry
        self._queue.put(("restart", service_id))
        registry.set_runtime_state(service_id, "stopping")

    # ── 工作线程 ──

    def _worker_loop(self):
        """工作线程循环，从队列取出请求执行。"""
        while not self._shutdown.is_set():
            try:
                action, service_id = self._queue.get(timeout=1)
                if action == "start":
                    self._do_start(service_id)
                elif action == "stop":
                    self._do_stop(service_id)
                elif action == "restart":
                    self._do_stop(service_id)
                    self._do_start(service_id)
            except queue.Empty:
                continue

    # ── 实际进程操作 ──

    def _do_start(self, service_id: str):
        """在工作线程中实际启动进程。"""
        from core import registry

        service = registry.get(service_id)
        if not service or not service.start_command or not service.working_dir:
            logger.error("服务 %s 缺少启动配置", service_id)
            registry.set_runtime_state(service_id, "exited")
            return

        env = os.environ.copy()
        env.update(service.env)
        if service.gpu_assignment:
            env["CUDA_VISIBLE_DEVICES"] = ",".join(
                map(str, service.gpu_assignment)
            )

        # 创建日志文件
        log_path = self._open_service_log(service_id)

        try:
            # 构建子进程参数
            kwargs = {
                "args": service.start_command,
                "shell": True,
                "cwd": service.working_dir,
                "env": env,
                "stdout": open(log_path, "w", encoding="utf-8"),
                "stderr": subprocess.STDOUT,
            }

            if _IS_WINDOWS:
                # Windows: 创建新进程组（用于后续终止整个进程树）
                kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
            else:
                # Unix: 创建新会话（用于干净终止整个进程组）
                kwargs["preexec_fn"] = os.setsid

            process = subprocess.Popen(**kwargs)
            self._processes[service_id] = process
            self._log_files[service_id] = log_path
            registry.set_pid(service_id, process.pid)

        except FileNotFoundError:
            logger.error(
                "服务 %s 启动失败: 命令 '%s' 未找到",
                service_id, service.start_command,
            )
            registry.set_runtime_state(service_id, "exited")
        except PermissionError:
            logger.error(
                "服务 %s 启动失败: 无权执行 '%s'",
                service_id, service.start_command,
            )
            registry.set_runtime_state(service_id, "exited")
        except Exception:
            logger.exception("服务 %s 启动失败 (未知异常)", service_id)
            registry.set_runtime_state(service_id, "exited")

    def _do_stop(self, service_id: str):
        """在工作线程中实际停止进程。"""
        from core import registry

        process = self._processes.get(service_id)
        if not process:
            registry.set_runtime_state(service_id, "stopped")
            return

        record = registry.get(service_id)
        timeout = record.stop_timeout_seconds if record else 30

        try:
            if _IS_WINDOWS:
                # Windows: 使用 terminate() 发送 Ctrl+C 事件
                process.terminate()
            else:
                # Unix: SIGTERM 到进程组
                os.killpg(os.getpgid(process.pid), signal.SIGTERM)

            process.wait(timeout=timeout)

        except subprocess.TimeoutExpired:
            logger.warning("服务 %s 超时未响应 SIGTERM，强制 SIGKILL", service_id)
            if _IS_WINDOWS:
                process.kill()
            else:
                os.killpg(os.getpgid(process.pid), signal.SIGKILL)
            process.wait()

        except (ProcessLookupError, OSError):
            # 进程已不存在
            pass

        self._processes.pop(service_id, None)
        registry.set_pid(service_id, None)
        registry.set_runtime_state(service_id, "stopped")

        # 记录日志文件位置
        log_file = self._log_files.get(service_id)
        if log_file:
            logger.info("服务 %s 日志已保存: %s", service_id, log_file)

    # ── 日志辅助 ──

    def _open_service_log(self, service_id: str) -> str:
        """创建服务日志文件并返回路径。"""
        log_dir = os.path.join("data/logs/services", service_id)
        os.makedirs(log_dir, exist_ok=True)
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        log_path = os.path.join(log_dir, f"{timestamp}.log")
        return log_path

    def tail_log(self, service_id: str, lines: int = 50) -> str:
        """返回服务日志的最后 N 行。由 WebUI 服务管理页面调用。"""
        import glob

        log_dir = os.path.join("data/logs/services", service_id)
        if not os.path.isdir(log_dir):
            return "(无日志)"

        log_files = sorted(glob.glob(os.path.join(log_dir, "*.log")))
        if not log_files:
            return "(无日志)"

        latest = log_files[-1]
        try:
            with open(latest, "r", encoding="utf-8") as f:
                all_lines = f.readlines()
        except (OSError, UnicodeDecodeError):
            return "(日志读取失败)"

        return "".join(all_lines[-lines:])

    # ── 状态查询 ──

    @property
    def is_running(self) -> bool:
        """工作线程是否正在运行。"""
        return self._worker is not None and self._worker.is_alive()

    def get_active_processes(self) -> list[str]:
        """返回当前活跃进程的服务 ID 列表。"""
        return list(self._processes.keys())
