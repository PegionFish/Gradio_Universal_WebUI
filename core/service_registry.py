# core/service_registry.py — 服务注册中心，存储所有已知模型服务

import threading
from core.event_bus import bus, Event
from core.service_record import ServiceRecord


class ServiceRegistry:
    """线程安全的内存服务注册中心。

    所有对 _services 字典的写操作通过 threading.Lock 保护。
    set_runtime_state() 在释放锁之后发布 EventBus 事件，防止死锁。
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._services: dict[str, ServiceRecord] = {}

    # ── 加载/重载 ──

    def load_from_config(self, services_list: list[dict]):
        """从 ConfigService 的 dict 列表加载/重新加载服务定义。

        已存在的服务保留 runtime_state，新增的服务初始化为 stopped。
        已不在配置中的服务被移除。发布 config_reloaded 事件。
        """
        with self._lock:
            new_ids = {s["id"] for s in services_list}

            # 保留现有 runtime_state
            old_states = {
                sid: self._services[sid].runtime_state
                for sid in new_ids
                if sid in self._services
            }

            self._services = {}
            for svc_dict in services_list:
                record = ServiceRecord.from_dict(svc_dict)
                record.runtime_state = old_states.get(record.id, "stopped")
                self._services[record.id] = record

        bus.emit(Event(
            type="config_reloaded",
            data={"service_ids": list(new_ids)},
            source="ServiceRegistry",
        ))

    # ── 读取 ──

    def get(self, service_id: str) -> ServiceRecord | None:
        """获取指定服务记录。

        注意: ServiceRecord 是 dataclass，非线程安全。
        读操作返回引用，调用者不应修改返回对象的字段。
        """
        with self._lock:
            return self._services.get(service_id)

    def list_services(self) -> list[ServiceRecord]:
        """返回所有服务的列表。"""
        with self._lock:
            return list(self._services.values())

    def get_by_model_type(self, model_type: str) -> list[ServiceRecord]:
        """返回指定 model_type 的所有服务。"""
        with self._lock:
            return [s for s in self._services.values() if s.model_type == model_type]

    # ── 写入 ──

    def set_runtime_state(self, service_id: str, new_state: str):
        """设置运行时状态并发布 service_state_changed 事件。

        事件在释放锁之后发布，防止死锁。
        """
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
        """设置服务的进程 PID。"""
        with self._lock:
            record = self._services.get(service_id)
            if record:
                record.pid = pid
