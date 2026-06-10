# tests/test_event_bus.py

import pytest
from core.event_bus import EventBus, Event, bus


class TestEvent:
    """Event 数据类测试。"""

    def test_event_defaults(self):
        e = Event(type="test")
        assert e.type == "test"
        assert e.data == {}
        assert e.source == ""

    def test_event_with_data(self):
        e = Event(type="test", data={"key": "value"}, source="tests")
        assert e.data["key"] == "value"
        assert e.source == "tests"


class TestEventBusBasic:
    """验收标准 6: on/emit 正常通信。"""

    def test_on_emit(self, event_bus):
        received = []
        def handler(event):
            received.append(event)

        event_bus.on("test_event", handler)
        event_bus.emit(Event(type="test_event", data={"x": 1}))
        assert len(received) == 1
        assert received[0].data["x"] == 1

    def test_multiple_handlers(self, event_bus):
        received = []
        event_bus.on("e", lambda e: received.append("a"))
        event_bus.on("e", lambda e: received.append("b"))
        event_bus.emit(Event(type="e"))
        assert received == ["a", "b"]

    def test_handler_order_preserved(self, event_bus):
        order = []
        event_bus.on("test", lambda e: order.append(1))
        event_bus.on("test", lambda e: order.append(2))
        event_bus.on("test", lambda e: order.append(3))
        event_bus.emit(Event(type="test"))
        assert order == [1, 2, 3]

    def test_no_handler_no_error(self, event_bus):
        """无注册处理器时不报错。"""
        event_bus.emit(Event(type="unknown_event"))


class TestEventBusOff:
    """验收标准 7: off() 能取消注册。"""

    def test_off_removes_handler(self, event_bus):
        received = []
        def handler(event):
            received.append(event)

        event_bus.on("test", handler)
        event_bus.off("test", handler)
        event_bus.emit(Event(type="test"))
        assert len(received) == 0

    def test_off_nonexistent_no_error(self, event_bus):
        def handler(event):
            pass
        event_bus.off("test", handler)  # 不应报错

    def test_off_other_handlers_remain(self, event_bus):
        r1, r2 = [], []
        h1 = lambda e: r1.append(1)
        h2 = lambda e: r2.append(2)
        event_bus.on("e", h1)
        event_bus.on("e", h2)
        event_bus.off("e", h1)
        event_bus.emit(Event(type="e"))
        assert r1 == []
        assert r2 == [2]

    def test_off_different_event_type_keeps_others(self, event_bus):
        r = []
        h = lambda e: r.append(1)
        event_bus.on("type_a", h)
        event_bus.off("type_b", h)  # 不同类型，不应移除
        event_bus.emit(Event(type="type_a"))
        assert len(r) == 1


class TestEventBusExceptionIsolation:
    """验收标准 8: 一个 handler 异常不中断其他 handler。"""

    def test_exception_isolation(self, event_bus):
        results = []
        def bad_handler(event):
            raise ValueError("test error")
        def good_handler(event):
            results.append("ok")
        def another_good(event):
            results.append("also ok")

        event_bus.on("test", bad_handler)
        event_bus.on("test", good_handler)
        event_bus.on("test", another_good)
        event_bus.emit(Event(type="test"))
        assert results == ["ok", "also ok"]

    def test_multiple_exceptions_within_same_emit(self, event_bus):
        results = []
        event_bus.on("e", lambda e: (_ for _ in ()).throw(KeyError("a")))
        event_bus.on("e", lambda e: (_ for _ in ()).throw(TypeError("b")))
        event_bus.on("e", lambda e: results.append(3))
        event_bus.emit(Event(type="e"))
        assert results == [3]


class TestEventBusClear:
    """clear() 用于测试重置。"""

    def test_clear_removes_all(self, event_bus):
        r = []
        event_bus.on("e", lambda e: r.append(1))
        event_bus.clear()
        event_bus.emit(Event(type="e"))
        assert r == []


class TestGlobalBus:
    """全局单例 bus 测试。"""

    def test_global_bus_is_singleton(self):
        from core.event_bus import bus
        assert isinstance(bus, EventBus)

    def test_global_bus_works(self):
        r = []
        def handler(e):
            r.append(e)
        bus.on("__test_global__", handler)
        bus.emit(Event(type="__test_global__", data={"test": True}))
        assert len(r) == 1
        bus.off("__test_global__", handler)
        bus.clear()
