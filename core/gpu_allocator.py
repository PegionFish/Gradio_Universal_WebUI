# core/gpu_allocator.py — GPU 智能分配引擎

import threading
import logging
from dataclasses import dataclass, field

from core.event_bus import bus, Event

logger = logging.getLogger(__name__)


@dataclass
class GpuReservation:
    """GPU 预留记录。"""
    gpu_index: int
    service_id: str
    model_type: str
    reserved_memory_gb: int   # 预留的显存 (GB)
    created_at: str


class GpuAllocator:
    """GPU 智能分配器。

    追踪每张 GPU 的预留情况，检测冲突，并提供最优分配建议。

    分配策略:
    1. 优先分配空闲显存最多的 GPU
    2. 避免 GPU 超卖 (overcommit) ——总预留不超过总显存的 90%
    3. 同服务优先复用已分配的 GPU
    4. 按温度/利用率作为平局打破因素
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._reservations: dict[int, list[GpuReservation]] = {}
        # {gpu_index: [GpuReservation, ...]}

    # ── 预留管理 ──

    def reserve(
        self,
        gpu_index: int,
        service_id: str,
        model_type: str,
        memory_gb: int,
    ) -> bool:
        """在 GPU 上预留显存。

        Args:
            gpu_index: GPU 索引
            service_id: 服务 ID
            model_type: 模型类型
            memory_gb: 预留的显存 (GB)

        Returns:
            True 如果预留成功，False 如果超出容量
        """
        import datetime

        # 检查是否超卖
        if not self._can_fit(gpu_index, memory_gb):
            logger.warning(
                "GPU %d 显存不足: 需要 %d GB, 当前已预留 %d GB",
                gpu_index, memory_gb,
                self.get_reserved_memory(gpu_index),
            )
            return False

        reservation = GpuReservation(
            gpu_index=gpu_index,
            service_id=service_id,
            model_type=model_type,
            reserved_memory_gb=memory_gb,
            created_at=datetime.datetime.now(
                datetime.timezone.utc
            ).isoformat(),
        )

        with self._lock:
            if gpu_index not in self._reservations:
                self._reservations[gpu_index] = []
            self._reservations[gpu_index].append(reservation)

        logger.info(
            "GPU %d: 已为 %s 预留 %d GB",
            gpu_index, service_id, memory_gb,
        )
        bus.emit(Event("gpu_reservation_changed", {
            "gpu_index": gpu_index,
            "service_id": service_id,
            "action": "reserve",
            "reserved_memory_gb": memory_gb,
        }))
        return True

    def release(self, gpu_index: int, service_id: str):
        """释放服务在 GPU 上的预留。"""
        with self._lock:
            if gpu_index not in self._reservations:
                return
            self._reservations[gpu_index] = [
                r for r in self._reservations[gpu_index]
                if r.service_id != service_id
            ]

        logger.info("GPU %d: 已释放 %s 的预留", gpu_index, service_id)
        bus.emit(Event("gpu_reservation_changed", {
            "gpu_index": gpu_index,
            "service_id": service_id,
            "action": "release",
        }))

    def release_all_for_service(self, service_id: str):
        """释放该服务在所有 GPU 上的预留。"""
        with self._lock:
            for gpu_index in list(self._reservations.keys()):
                self._reservations[gpu_index] = [
                    r for r in self._reservations[gpu_index]
                    if r.service_id != service_id
                ]

    # ── 查询 ──

    def get_reserved_memory(self, gpu_index: int) -> int:
        """获取 GPU 上已预留的总显存 (GB)。"""
        with self._lock:
            return sum(
                r.reserved_memory_gb
                for r in self._reservations.get(gpu_index, [])
            )

    def get_reservations(self, gpu_index: int) -> list[GpuReservation]:
        with self._lock:
            return list(self._reservations.get(gpu_index, []))

    def get_service_gpus(self, service_id: str) -> list[int]:
        """获取某服务占用的 GPU 列表。"""
        with self._lock:
            result = set()
            for gpu_idx, reservations in self._reservations.items():
                for r in reservations:
                    if r.service_id == service_id:
                        result.add(gpu_idx)
            return sorted(result)

    def _can_fit(self, gpu_index: int, required_gb: int) -> bool:
        """检查 GPU 是否能容纳额外的预留。"""
        from core import gpu_monitor

        if gpu_monitor is None:
            return True

        metrics = gpu_monitor.get_latest()

        if not metrics.available:
            return True  # 无 GPU 信息时不限制

        snap = next(
            (s for s in metrics.snapshots if s.gpu_index == gpu_index),
            None,
        )
        if not snap:
            return True

        total_mb = snap.memory_total_mb
        total_gb = total_mb / 1024

        current_reserved = self.get_reserved_memory(gpu_index)

        # 最多预留 90% 的总显存
        max_reservable = int(total_gb * 0.9)
        return (current_reserved + required_gb) <= max_reservable

    # ── 推荐 ──

    def recommend_gpu(
        self,
        required_memory_gb: int,
        preferred_model_type: str | None = None,
        exclude_gpus: list[int] | None = None,
    ) -> list[int]:
        """推荐最优 GPU 用于新服务分配。

        排序规则:
        1. 过滤: 可容纳 required_memory_gb 的 GPU
        2. 排除 exclude_gpus
        3. 如果 preferred_model_type 已有同型号分配 → 提升该 GPU 排名
        4. 按可用显存降序 (总显存 - 已用 - 已预留)
        5. 平局: 利用率升序
        6. 平局: 温度升序

        Returns:
            GPU 索引的排序列表，第一个为最优推荐。
        """
        from core import gpu_monitor
        metrics = gpu_monitor.get_latest()
        if not metrics.available or not metrics.snapshots:
            return []

        exclude_gpus = exclude_gpus or []
        candidates = []

        for snap in metrics.snapshots:
            if snap.gpu_index in exclude_gpus:
                continue

            free_mb = snap.memory_free_mb
            reserved_mb = self.get_reserved_memory(snap.gpu_index) * 1024
            available_mb = free_mb - reserved_mb

            if available_mb < required_memory_gb * 1024:
                continue

            # 检查是否有同型号已分配
            same_model_bonus = -1000  # 排序 bonus（越小越好）
            if preferred_model_type:
                for r in self.get_reservations(snap.gpu_index):
                    if r.model_type == preferred_model_type:
                        same_model_bonus = -2000
                        break

            candidates.append((
                snap.gpu_index,
                available_mb,
                snap.utilization_percent + same_model_bonus,
                snap.temperature_celsius,
            ))

        ranked = sorted(
            candidates,
            key=lambda x: (-x[1], x[2], x[3]),
        )

        return [gpu_idx for gpu_idx, *_ in ranked]

    # ── 冲突检测 ──

    def detect_conflicts(self) -> list[dict]:
        """检测 GPU 分配冲突。

        Returns:
            [{"gpu_index": int, "total_reserved_gb": int, "total_capacity_gb": int,
              "services": [...], "severity": "warning"|"critical"}, ...]
        """
        from core import gpu_monitor
        metrics = gpu_monitor.get_latest()

        conflicts = []
        for snap in metrics.snapshots:
            gpu_idx = snap.gpu_index
            total_gb = snap.memory_total_mb / 1024
            reserved_gb = self.get_reserved_memory(gpu_idx)

            usage_pct = (reserved_gb / total_gb * 100) if total_gb > 0 else 0

            if usage_pct > 100:
                severity = "critical"
            elif usage_pct > 80:
                severity = "warning"
            else:
                continue

            conflicts.append({
                "gpu_index": gpu_idx,
                "total_reserved_gb": reserved_gb,
                "total_capacity_gb": total_gb,
                "usage_percent": usage_pct,
                "services": [
                    {"service_id": r.service_id, "model_type": r.model_type}
                    for r in self.get_reservations(gpu_idx)
                ],
                "severity": severity,
            })

        return conflicts


# ── 全局单例 ──
_allocator: GpuAllocator | None = None


def get_allocator() -> GpuAllocator:
    global _allocator
    if _allocator is None:
        _allocator = GpuAllocator()
    return _allocator
