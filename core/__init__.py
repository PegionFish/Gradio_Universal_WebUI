# core/__init__.py — 核心服务模块

from core.config_service import ConfigService, ConfigError
from core.service_registry import ServiceRegistry
from core.event_bus import EventBus, Event, bus
from core.process_manager import ProcessManager
from core.health_checker import HealthChecker

# 模块级变量，在 main.py 的 setup_core() 中初始化
# 后台线程和 WebUI 页面通过 from core import registry, config 引用这些变量。
# setup_core() 在 WebUI 启动前完成，因此页面代码访问 core 变量时总是已初始化状态。
config: ConfigService = None           # type: ignore[assignment]
registry: ServiceRegistry = None       # type: ignore[assignment]
process_manager: ProcessManager = None # type: ignore[assignment]
health_checker: HealthChecker = None   # type: ignore[assignment]


def setup_core(config_dir: str = "config/") -> None:
    """初始化所有核心服务。由 main.py 在启动序列步骤 3 中调用。"""
    global config, registry, process_manager, health_checker
    config = ConfigService(config_dir)
    registry = ServiceRegistry()
    process_manager = ProcessManager()
    health_checker = HealthChecker()


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
    "setup_core",
]
