# core/ws_bridge.py — 事件转发桥，将 EventBus 事件缓冲供 WebUI 实时消费

import threading
import time
import datetime
import logging
from typing import Optional
from collections import deque

from core.event_bus import bus, Event

logger = logging.getLogger(__name__)

# 每种事件类型保留的最大数量
MAX_BUFFER_PER_TYPE = 100


class EventBuffer:
    """线程安全的环形事件缓冲区。

    订阅 EventBus 的所有事件，供 WebUI 页面周期性拉取。
    每个消费者通过 cursor 跟踪自己的读取位置，实现增量拉取。
    """

    def __init__(self, max_events: int = 500):
        self._lock = threading.Lock()
        self._events: deque[dict] = deque(maxlen=max_events)
        self._sequence: int = 0  # 全局递增序号

    def start(self):
        """订阅 EventBus 所有事件类型。"""
        # 使用通配订阅——监听所有核心事件
        bus.on("service_state_changed", self._on_event)
        bus.on("config_reloaded", self._on_event)
        bus.on("task_created", self._on_event)
        bus.on("task_completed", self._on_event)
        bus.on("gpu_metrics_updated", self._on_event)
        logger.info("EventBuffer 已启动，监听所有 EventBus 事件")

    def stop(self):
        """取消所有订阅。"""
        bus.off("service_state_changed", self._on_event)
        bus.off("config_reloaded", self._on_event)
        bus.off("task_created", self._on_event)
        bus.off("task_completed", self._on_event)
        bus.off("gpu_metrics_updated", self._on_event)

    def _on_event(self, event: Event):
        """EventBus 回调：将事件加入缓冲区。"""
        with self._lock:
            self._sequence += 1
            self._events.append({
                "seq": self._sequence,
                "type": event.type,
                "data": event.data,
                "source": event.source,
                "timestamp": datetime.datetime.now(
                    datetime.timezone.utc
                ).isoformat(),
            })

    def poll(self, since_seq: int = 0) -> dict:
        """拉取自 since_seq（不含）之后的所有新事件。

        Args:
            since_seq: 上次请求的序列号（0 表示拉取最近的事件）

        Returns:
            {
                "events": [...],
                "latest_seq": int,
                "has_more": bool   # True 如果事件被截断
            }
        """
        with self._lock:
            if since_seq == 0:
                # 初始请求：返回最近 20 条
                recent = list(self._events)[-20:]
                return {
                    "events": recent,
                    "latest_seq": self._sequence,
                    "has_more": len(self._events) > 20,
                }

            new_events = [
                e for e in self._events if e["seq"] > since_seq
            ]
            # 取最后 50 条（避免一次返回太多）
            truncated = new_events[-50:] if len(new_events) > 50 else new_events

            return {
                "events": truncated,
                "latest_seq": (
                    truncated[-1]["seq"] if truncated else since_seq
                ),
                "has_more": len(new_events) > 50,
            }

    def get_stats(self) -> dict:
        """获取缓冲区统计信息。"""
        with self._lock:
            return {
                "total_buffered": len(self._events),
                "latest_seq": self._sequence,
            }


# ── 全局单例 ──
_buffer: Optional[EventBuffer] = None


def get_buffer() -> EventBuffer:
    """获取全局 EventBuffer 实例（懒初始化）。"""
    global _buffer
    if _buffer is None:
        _buffer = EventBuffer()
        _buffer.start()
    return _buffer


def shutdown_buffer():
    """关闭全局缓冲区。"""
    global _buffer
    if _buffer:
        _buffer.stop()
        _buffer = None


# ═════════════════════════════════════════════════════════
# 实时状态快照构建器
# ═════════════════════════════════════════════════════════


def build_live_status_payload() -> dict:
    """构建完整的实时状态负载（供 WebUI 消费）。

    从所有核心服务拉取最新数据，组装为统一字典。
    """
    from core import registry, scheduler, gpu_monitor

    # 服务列表
    svc_list = registry.list_services()
    services = [
        {
            "id": s.id,
            "display_name": s.display_name,
            "model_type": s.model_type,
            "runtime_state": s.runtime_state,
            "gpu_assignment": s.gpu_assignment,
            "service_url": s.service_url,
        }
        for s in svc_list
    ]

    # 最近任务
    tasks = [
        {
            "id": t["id"],
            "service_id": t.get("service_id", ""),
            "model_type": t.get("model_type", ""),
            "status": t.get("status", ""),
            "created_at": t.get("created_at", "")[:19],
            "error_summary": (t.get("error_summary", "") or "")[:40],
        }
        for t in scheduler.list_tasks(limit=10)
    ]

    # GPU 指标
    gpu = gpu_monitor.get_latest()
    gpu_data = {
        "available": gpu.available,
        "snapshots": [
            {
                "gpu_index": s.gpu_index,
                "name": s.name,
                "memory_total_mb": s.memory_total_mb,
                "memory_used_mb": s.memory_used_mb,
                "memory_free_mb": s.memory_free_mb,
                "utilization_percent": s.utilization_percent,
                "temperature_celsius": s.temperature_celsius,
                "power_milliwatts": s.power_milliwatts,
                "processes": s.processes,
            }
            for s in gpu.snapshots
        ],
        "updated_at": gpu.updated_at,
    }

    # 事件缓冲统计
    buf = get_buffer()
    buf_stats = buf.get_stats()

    return {
        "services": services,
        "tasks": tasks,
        "gpu_metrics": gpu_data,
        "event_seq": buf_stats["latest_seq"],
        "last_refresh": datetime.datetime.now().strftime("%H:%M:%S"),
    }
