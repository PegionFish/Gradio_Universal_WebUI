# core/event_bus.py — 事件总线，用于核心服务间的松耦合通信

from dataclasses import dataclass, field
from typing import Callable, Any
import threading
import logging


logger = logging.getLogger(__name__)


@dataclass
class Event:
    """事件数据类。"""
    type: str                     # 事件类型
    data: dict[str, Any] = field(default_factory=dict)  # 事件负载
    source: str = ""              # 事件来源标识，如 "ServiceRegistry"


class EventBus:
    """线程安全的事件总线。

    处理器在发布者的线程中同步调用，不应长时间阻塞。
    如需耗时操作，处理器应将工作提交到自己的线程池或队列。
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._handlers: dict[str, list[Callable]] = {}
        # _handlers 中的 handler 签名: handler(Event) -> None

    def on(self, event_type: str, handler: Callable):
        """注册事件处理器。

        Args:
            event_type: 事件类型字符串
            handler: 处理器函数，签名 handler(Event) -> None
        """
        with self._lock:
            self._handlers.setdefault(event_type, []).append(handler)

    def off(self, event_type: str, handler: Callable):
        """移除事件处理器。

        Args:
            event_type: 事件类型字符串
            handler: 必须是之前注册的同一函数引用
        """
        with self._lock:
            handlers = self._handlers.get(event_type, [])
            if handler in handlers:
                handlers.remove(handler)

    def emit(self, event: Event):
        """发布事件，同步调用所有已注册的处理器。

        处理器按注册顺序执行。某个处理器抛出异常不影响其他处理器，
        异常会被捕获并记录日志。
        """
        with self._lock:
            handlers = list(self._handlers.get(event.type, []))

        for handler in handlers:
            try:
                handler(event)
            except Exception:
                logger.exception(
                    "EventBus handler 异常 [event_type=%s, handler=%s]",
                    event.type,
                    getattr(handler, "__name__", handler),
                )

    def clear(self):
        """清空所有处理器。用于测试。"""
        with self._lock:
            self._handlers.clear()


# 全局单例
bus = EventBus()
