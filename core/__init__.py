# core/__init__.py — 核心服务模块

from core.config_service import ConfigService, ConfigError
from core.service_registry import ServiceRegistry
from core.event_bus import EventBus, Event, bus
from core.process_manager import ProcessManager
from core.health_checker import HealthChecker
from core.task_scheduler import TaskScheduler
from core.result_manager import ResultManager
from core.gpu_monitor import GpuMonitor

# 模块级变量，在 main.py 的 setup_core() 中初始化
# 后台线程和 WebUI 页面通过 from core import registry, config 引用这些变量。
# setup_core() 在 WebUI 启动前完成，因此页面代码访问 core 变量时总是已初始化状态。
config: ConfigService = None           # type: ignore[assignment]
registry: ServiceRegistry = None       # type: ignore[assignment]
process_manager: ProcessManager = None # type: ignore[assignment]
health_checker: HealthChecker = None   # type: ignore[assignment]
scheduler: TaskScheduler = None        # type: ignore[assignment]
result_mgr: ResultManager = None       # type: ignore[assignment]
gpu_monitor: GpuMonitor = None         # type: ignore[assignment]


def setup_core(config_dir: str = "config/") -> None:
    """初始化所有核心服务。由 main.py 在启动序列步骤 3 中调用。"""
    global config, registry, process_manager, health_checker, scheduler, result_mgr, gpu_monitor
    config = ConfigService(config_dir)
    registry = ServiceRegistry()
    process_manager = ProcessManager()
    health_checker = HealthChecker()
    scheduler = TaskScheduler(db_path="data/tasks.sqlite3")
    result_mgr = ResultManager(base_dir="data/jobs/")
    gpu_monitor = GpuMonitor()


__all__ = [
    "ConfigService",
    "ConfigError",
    "ServiceRegistry",
    "EventBus",
    "Event",
    "bus",
    "config",
    "registry",
    "process_manager",
    "health_checker",
    "scheduler",
    "result_mgr",
    "gpu_monitor",
    "setup_core",
]
