# core/system_monitor.py — 系统健康监控 (磁盘/CPU/内存)

import os
import threading
import datetime
import logging
from dataclasses import dataclass, field

from core.event_bus import bus, Event

logger = logging.getLogger(__name__)


@dataclass
class DiskSnapshot:
    """磁盘分区快照。"""
    mountpoint: str
    device: str
    total_gb: float
    used_gb: float
    free_gb: float
    percent_used: float  # 0-100


@dataclass
class MemorySnapshot:
    """内存快照。"""
    total_gb: float
    available_gb: float
    used_gb: float
    percent_used: float  # 0-100
    swap_total_gb: float
    swap_used_gb: float


@dataclass
class CpuSnapshot:
    """CPU 快照。"""
    percent_used: float   # 0-100
    core_count: int
    load_avg_1min: float  # 仅 Linux
    load_avg_5min: float
    load_avg_15min: float


@dataclass
class SystemMetrics:
    """系统聚合指标。"""
    available: bool
    disks: list[DiskSnapshot] = field(default_factory=list)
    memory: MemorySnapshot | None = None
    cpu: CpuSnapshot | None = None
    updated_at: str = ""


class SystemMonitor:
    """后台系统健康监控器。

    通过 psutil 采集磁盘/CPU/内存指标。
    psutil 不可用时优雅降级（available=False）。
    """

    def __init__(self):
        self._initialized = False
        self._shutdown = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._latest = SystemMetrics(available=False)

    def initialize(self):
        """初始化 psutil。"""
        try:
            import psutil  # noqa: F401
            self._initialized = True
            logger.info("系统监控已初始化 (psutil)")
        except ImportError:
            logger.warning(
                "psutil 未安装。系统监控功能不可用。"
                "安装: pip install psutil"
            )
            self._initialized = False

    def start(self, interval_seconds: int = 30):
        """启动后台采集线程。"""
        self.initialize()
        self._thread = threading.Thread(
            target=self._refresh_loop,
            args=(interval_seconds,),
            daemon=True,
            name="sys-monitor",
        )
        self._thread.start()
        logger.info("系统监控已启动 (间隔 %ds)", interval_seconds)

    def stop(self):
        self._shutdown.set()

    def _refresh_loop(self, interval: int):
        while not self._shutdown.is_set():
            metrics = self._collect()
            with self._lock:
                self._latest = metrics

            if metrics.available:
                bus.emit(Event("system_metrics_updated", {
                    "cpu_percent": metrics.cpu.percent_used if metrics.cpu else 0,
                    "memory_percent": metrics.memory.percent_used if metrics.memory else 0,
                    "worst_disk_percent": max(
                        (d.percent_used for d in metrics.disks), default=0,
                    ),
                }))

            self._shutdown.wait(interval)

    def _collect(self) -> SystemMetrics:
        if not self._initialized:
            return SystemMetrics(available=False)

        try:
            import psutil

            # 磁盘
            disks = []
            for part in psutil.disk_partitions(all=False):
                try:
                    usage = psutil.disk_usage(part.mountpoint)
                    disks.append(DiskSnapshot(
                        mountpoint=part.mountpoint,
                        device=part.device,
                        total_gb=usage.total / (1024**3),
                        used_gb=usage.used / (1024**3),
                        free_gb=usage.free / (1024**3),
                        percent_used=usage.percent,
                    ))
                except PermissionError:
                    continue

            # 内存
            mem = psutil.virtual_memory()
            swap = psutil.swap_memory()
            memory = MemorySnapshot(
                total_gb=mem.total / (1024**3),
                available_gb=mem.available / (1024**3),
                used_gb=mem.used / (1024**3),
                percent_used=mem.percent,
                swap_total_gb=swap.total / (1024**3),
                swap_used_gb=swap.used / (1024**3),
            )

            # CPU
            cpu_percent = psutil.cpu_percent(interval=1)
            core_count = psutil.cpu_count(logical=True) or 0
            cpu = CpuSnapshot(
                percent_used=cpu_percent,
                core_count=core_count,
                load_avg_1min=0,
                load_avg_5min=0,
                load_avg_15min=0,
            )

            # Linux load average
            try:
                if hasattr(os, "getloadavg"):
                    la1, la5, la15 = os.getloadavg()
                    cpu.load_avg_1min = la1
                    cpu.load_avg_5min = la5
                    cpu.load_avg_15min = la15
            except OSError:
                pass

            return SystemMetrics(
                available=True,
                disks=disks,
                memory=memory,
                cpu=cpu,
                updated_at=datetime.datetime.now(
                    datetime.timezone.utc
                ).isoformat(),
            )

        except Exception as e:
            logger.error("系统指标采集失败: %s", e)
            return SystemMetrics(available=False)

    def get_latest(self) -> SystemMetrics:
        """获取最新快照。"""
        with self._lock:
            return self._latest

    # ── 告警阈值检查 ──

    def check_alerts(self) -> list[dict]:
        """检查是否触发告警阈值。

        Returns:
            [{"level": "warning"|"critical", "resource": str, "message": str}, ...]
        """
        metrics = self.get_latest()
        if not metrics.available:
            return []

        alerts = []

        # 磁盘告警
        for disk in metrics.disks:
            if disk.percent_used >= 95:
                alerts.append({
                    "level": "critical",
                    "resource": "disk",
                    "message": f"{disk.mountpoint} 磁盘使用率 {disk.percent_used:.0f}%"
                               f"（仅剩 {disk.free_gb:.1f} GB）",
                })
            elif disk.percent_used >= 85:
                alerts.append({
                    "level": "warning",
                    "resource": "disk",
                    "message": f"{disk.mountpoint} 磁盘使用率 {disk.percent_used:.0f}%",
                })

        # 内存告警
        if metrics.memory and metrics.memory.percent_used >= 95:
            alerts.append({
                "level": "critical",
                "resource": "memory",
                "message": f"内存使用率 {metrics.memory.percent_used:.0f}%",
            })
        elif metrics.memory and metrics.memory.percent_used >= 85:
            alerts.append({
                "level": "warning",
                "resource": "memory",
                "message": f"内存使用率 {metrics.memory.percent_used:.0f}%",
            })

        return alerts
