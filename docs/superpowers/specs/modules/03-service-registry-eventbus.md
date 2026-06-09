# 模块 3：服务注册与事件系统

## 用途

`ServiceRegistry` 以线程安全的内存字典存储所有已知模型服务的元数据和运行时状态。`EventBus` 提供核心组件间的松耦合事件通信机制。

## 依赖

- **模块 1**：项目骨架
- **模块 2**：配置系统（使用 `ServiceRecord`、`ConfigService` 加载服务定义）

## ServiceRegistry

### 文件位置

`core/service_registry.py`

### 线程安全设计

- 所有对 `_services` 字典的写操作通过 `threading.Lock` 保护
- `set_runtime_state()` 在释放锁**之后**发布 EventBus 事件，防止死锁
- 读操作（`get()`, `list_services()`, `get_by_model_type()`）读锁或返回副本——具体选择见下方代码

### 实现

```python
import threading
from core.event_bus import bus, Event

class ServiceRegistry:
    def __init__(self):
        self._lock = threading.Lock()
        self._services: dict[str, ServiceRecord] = {}
    
    def load_from_config(self, services_list: list[dict]):
        """从 ConfigService 的 dict 列表加载/重新加载服务定义。
        已存在的服务保留 runtime_state，新增的服务初始化为 stopped。
        已不在配置中的服务被移除。
        """
        with self._lock:
            new_ids = {s["id"] for s in services_list}
            # 保留现有 runtime_state
            old_states = {sid: self._services[sid].runtime_state 
                         for sid in new_ids if sid in self._services}
            
            self._services = {}
            for svc_dict in services_list:
                record = ServiceRecord.from_dict(svc_dict)
                record.runtime_state = old_states.get(record.id, "stopped")
                self._services[record.id] = record
        
        bus.emit(Event("config_reloaded", {"service_ids": list(new_ids)}))
    
    def get(self, service_id: str) -> ServiceRecord | None:
        with self._lock:
            record = self._services.get(service_id)
            return record  # 调用者不应修改返回的 dataclass 字段
            # 注: ServiceRecord 是 dataclass，非线程安全。
            # 读操作返回引用，调用者不应修改。
    
    def list_services(self) -> list[ServiceRecord]:
        with self._lock:
            return list(self._services.values())
    
    def get_by_model_type(self, model_type: str) -> list[ServiceRecord]:
        with self._lock:
            return [s for s in self._services.values() if s.model_type == model_type]
    
    def set_runtime_state(self, service_id: str, new_state: str):
        """设置运行时状态并发布事件。线程安全。"""
        old_state = None
        with self._lock:
            record = self._services.get(service_id)
            if not record:
                return
            old_state = record.runtime_state
            record.runtime_state = new_state
        
        bus.emit(Event(
            type="service_state_changed",
            data={
                "service_id": service_id,
                "old_state": old_state,
                "new_state": new_state,
            },
            source="ServiceRegistry",
        ))
    
    def set_pid(self, service_id: str, pid: int | None):
        with self._lock:
            record = self._services.get(service_id)
            if record:
                record.pid = pid
```

## EventBus

### 文件位置

`core/event_bus.py`

### 接口

```python
from dataclasses import dataclass, field
from typing import Callable, Any
import threading

@dataclass
class Event:
    type: str                     # 事件类型
    data: dict[str, Any]          # 事件负载
    source: str = ""              # 事件来源标识，如 "ServiceRegistry"

class EventBus:
    def __init__(self):
        self._lock = threading.Lock()
        self._handlers: dict[str, list[Callable]] = {}
        # _handlers 中的 handler 签名: handler(Event) -> None
        # handler 在 EventBus 线程中同步调用，不应长时间阻塞
    
    def on(self, event_type: str, handler: Callable):
        """注册事件处理器。"""
        with self._lock:
            self._handlers.setdefault(event_type, []).append(handler)
    
    def off(self, event_type: str, handler: Callable):
        """移除事件处理器。handler 必须是之前注册的同一引用。"""
        with self._lock:
            handlers = self._handlers.get(event_type, [])
            if handler in handlers:
                handlers.remove(handler)
    
    def emit(self, event: Event):
        """发布事件，同步调用所有已注册的处理器。
        处理器按注册顺序执行。某个处理器抛出异常不影响其他处理器。
        """
        handlers = list(self._handlers.get(event.type, []))
        for handler in handlers:
            try:
                handler(event)
            except Exception:
                import logging
                logging.getLogger(__name__).exception("EventBus handler 异常")
    
    def clear(self):
        """清空所有处理器。用于测试。"""
        with self._lock:
            self._handlers.clear()

# 全局单例
bus = EventBus()
```

### 事件类型总表

| 事件类型 | 负载 data | 发布者 | 消费者 |
|---------|-----------|--------|--------|
| `service_state_changed` | `service_id, old_state, new_state` | ServiceRegistry | HealthChecker, GpuMonitor, WebUI |
| `config_reloaded` | `service_ids: list[str]` | ConfigService (间接) | ProcessManager, WebUI |
| `service_added` | `service_id, model_type` | ServiceRegistry | WebUI |
| `service_removed` | `service_id` | ServiceRegistry | ProcessManager, WebUI |
| `gpu_metrics_updated` | `gpus: list[dict]` | GpuMonitor | WebUI |
| `task_completed` | `task_id, service_id, status` | TaskScheduler | WebUI |
| `task_created` | `task_id, service_id` | TaskScheduler | WebUI |

### 事件使用注意事项

1. 事件处理器在发布者的线程中同步执行，处理器不应阻塞超过 1 秒
2. 若要执行耗时操作，处理器应将工作提交到自己的线程池或队列
3. 处理器抛出异常不影响其他处理器，但异常被 `emit()` 的 try/except 捕获并记录日志
4. 事件不保证顺序交付（在同步模型中，他们按注册顺序执行，但多个发布者可能交错）
5. 测试中通过 `bus.clear()` 重置

## 在 core/__init__.py 中的集成

```python
from core.config_service import ConfigService
from core.service_registry import ServiceRegistry
from core.event_bus import bus

# 模块级变量，在 main.py 的 setup_core() 中初始化
config: ConfigService = None       # type: ignore[assignment]
registry: ServiceRegistry = None   # type: ignore[assignment]
# ... 其他核心服务类似


def setup_core(config_dir: str = "config/") -> None:
    """初始化所有核心服务。由 main.py 在启动序列步骤 3 中调用。"""
    global config, registry
    config = ConfigService(config_dir)
    registry = ServiceRegistry()
```

> 注意：核心服务不在模块导入时自动实例化，而是通过 `core.setup_core()` 在 `main.py` 的控制下统一初始化。后台线程和 WebUI 页面通过 `from core import registry, config` 引用这些模块级变量。`setup_core()` 在 WebUI 启动前完成，因此页面代码访问 core 变量时总是已初始化状态。

## 验收标准

1. `ServiceRegistry.load_from_config()` 从合法 dict 列表正确加载
2. `get()` 返回预期的 ServiceRecord
3. `list_services()` 返回所有服务
4. `get_by_model_type("stable-diffusion")` 只返回对应类型的服务
5. `set_runtime_state()` 正确更新状态并发布 `service_state_changed` 事件
6. EventBus 的 `on()`/`emit()` 可正常通信
7. EventBus 的 `off()` 能取消注册
8. EventBus 的 `emit()` 在一个 handler 抛出异常时不中断其他 handler
9. 配置重新加载后，不在新配置中的服务从 registry 中移除
10. 配置重新加载后，已在 registry 中的服务保留现有的 `runtime_state`
