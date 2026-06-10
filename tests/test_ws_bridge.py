# tests/test_ws_bridge.py — Phase 4 事件桥测试

from core.event_bus import Event, bus
from core.ws_bridge import EventBuffer


class TestEventBuffer:
    def test_start_stop(self):
        buf = EventBuffer(max_events=100)
        buf.start()
        assert buf.get_stats()["total_buffered"] == 0
        buf.stop()

    def test_poll_initial(self):
        buf = EventBuffer(max_events=100)
        result = buf.poll(since_seq=0)
        assert result["events"] == []
        assert result["latest_seq"] == 0

    def test_poll_with_events(self):
        buf = EventBuffer(max_events=100)
        buf.start()

        # Emit events that the buffer is subscribed to
        bus.emit(Event("task_created", {"task_id": "t1"}, "test"))
        bus.emit(Event("task_completed", {"task_id": "t1"}, "test"))

        result = buf.poll(since_seq=0)
        assert len(result["events"]) >= 1, f"Expected >=1 events, got {len(result['events'])}"
        assert result["latest_seq"] >= 1
        buf.stop()
        bus.clear()

    def test_poll_incremental(self):
        buf = EventBuffer(max_events=100)
        buf.start()

        bus.emit(Event("task_created", {"task_id": "t1"}))
        first = buf.poll(since_seq=0)
        seq1 = first["latest_seq"]

        bus.emit(Event("task_completed", {"task_id": "t1"}))
        second = buf.poll(since_seq=seq1)
        assert len(second["events"]) >= 1, f"Expected >=1 new events, got {len(second['events'])}"
        assert second["latest_seq"] >= seq1

        buf.stop()
        bus.clear()
