# core/gpu_monitor.py — GPU 监控器，基于 NVML 的 GPU 指标采集和推荐

import threading
import datetime
import logging
from dataclasses import dataclass, field

from core.event_bus import bus, Event

logger = logging.getLogger(__name__)


# ── 数据结构 ──


@dataclass
class GpuSnapshot:
    """单张 GPU 的即时指标快照。"""
    gpu_index: int
    name: str                         # 如 "NVIDIA GeForce RTX 4090"
    memory_total_mb: int
    memory_used_mb: int
    memory_free_mb: int
    utilization_percent: int           # 0-100
    memory_utilization_percent: int    # 0-100
    temperature_celsius: int
    power_milliwatts: int
    processes: list[dict] = field(default_factory=list)
    # processes: [{"pid": ..., "used_memory_mb": ...}]


@dataclass
class GpuMetrics:
    """所有 GPU 的聚合指标。"""
    available: bool                    # NVML 是否初始化成功
    snapshots: list[GpuSnapshot]
    updated_at: str                    # ISO 8601


# ── 监控器 ──


class GpuMonitor:
    """通过 NVML 采集 NVIDIA GPU 指标的后台监控器。

    降级处理:
    - NVML 初始化失败时 available=False，不抛出异常
    - 无 GPU 环境下 get_latest() 返回空快照
    - recommend() 在无 GPU 时返回空列表
    """

    def __init__(self):
        self._initialized = False
        self._shutdown = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._latest: GpuMetrics = GpuMetrics(
            available=False,
            snapshots=[],
            updated_at="",
        )

    # ── 生命周期 ──

    def initialize(self):
        """初始化 NVML。在后台线程启动前调用。

        若未检测到 NVIDIA 驱动，设置 available=False 并记录日志，不抛出异常。
        """
        try:
            import pynvml
            pynvml.nvmlInit()
            self._initialized = True
            logger.info("NVML 初始化成功")
        except Exception as e:
            logger.warning("NVML 初始化失败: %s。GPU 监控功能不可用。", e)
            self._initialized = False

    def shutdown(self):
        """关闭 NVML 并停止刷新线程。"""
        self._shutdown.set()
        if self._initialized:
            try:
                import pynvml
                pynvml.nvmlShutdown()
            except Exception:
                pass

    def start(self, interval_seconds: int = 5):
        """启动后台采集线程。

        Args:
            interval_seconds: 采集间隔（秒）
        """
        self.initialize()
        self._thread = threading.Thread(
            target=self._refresh_loop,
            args=(interval_seconds,),
            daemon=True,
            name="gpu-monitor",
        )
        self._thread.start()
        logger.info("GPU 监控已启动 (间隔 %ds)", interval_seconds)

    def stop(self):
        """停止后台采集线程。"""
        self._shutdown.set()

    # ── 采集循环 ──

    def _refresh_loop(self, interval: int):
        """后台采集循环。"""
        while not self._shutdown.is_set():
            metrics = self._collect()
            with self._lock:
                self._latest = metrics

            if metrics.available:
                bus.emit(Event("gpu_metrics_updated", {
                    "gpus": [
                        {
                            "index": s.gpu_index,
                            "name": s.name,
                            "memory_free_mb": s.memory_free_mb,
                            "utilization_percent": s.utilization_percent,
                            "temperature_celsius": s.temperature_celsius,
                        }
                        for s in metrics.snapshots
                    ],
                }))

            self._shutdown.wait(interval)

    def _collect(self) -> GpuMetrics:
        """采集所有 GPU 指标。在后台线程中调用。"""
        if not self._initialized:
            return GpuMetrics(available=False, snapshots=[], updated_at="")

        try:
            import pynvml

            device_count = pynvml.nvmlDeviceGetCount()
            snapshots = []

            for i in range(device_count):
                handle = pynvml.nvmlDeviceGetHandleByIndex(i)

                name_bytes = pynvml.nvmlDeviceGetName(handle)
                name = name_bytes.decode() if isinstance(name_bytes, bytes) else str(name_bytes)

                mem_info = pynvml.nvmlDeviceGetMemoryInfo(handle)
                util = pynvml.nvmlDeviceGetUtilizationRates(handle)
                temp = pynvml.nvmlDeviceGetTemperature(
                    handle, pynvml.NVML_TEMPERATURE_GPU
                )
                power = pynvml.nvmlDeviceGetPowerUsage(handle)

                # 采集运行中进程
                processes = []
                try:
                    procs = pynvml.nvmlDeviceGetComputeRunningProcesses(handle)
                    processes = [
                        {
                            "pid": p.pid,
                            "used_memory_mb": p.usedGpuMemory // (1024 * 1024),
                        }
                        for p in procs
                        if p.usedGpuMemory is not None
                    ]
                except pynvml.NVMLError:
                    pass

                snapshots.append(GpuSnapshot(
                    gpu_index=i,
                    name=name,
                    memory_total_mb=mem_info.total // (1024 * 1024),
                    memory_used_mb=mem_info.used // (1024 * 1024),
                    memory_free_mb=mem_info.free // (1024 * 1024),
                    utilization_percent=int(util.gpu),
                    memory_utilization_percent=int(util.memory),
                    temperature_celsius=int(temp),
                    power_milliwatts=int(power),
                    processes=processes,
                ))

            return GpuMetrics(
                available=True,
                snapshots=snapshots,
                updated_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),
            )

        except Exception as e:
            logger.error("GPU 指标采集失败: %s", e)
            return GpuMetrics(available=False, snapshots=[], updated_at="")

    # ── 查询 ──

    def get_latest(self) -> GpuMetrics:
        """获取最新快照。线程安全。"""
        with self._lock:
            return self._latest

    def recommend(self, min_memory_gb: int = 8) -> list[int]:
        """根据最新快照返回排序后的 GPU 推荐列表。

        排序规则:
        1. 过滤可用显存 >= min_memory_gb 的 GPU
        2. 按可用显存降序排列
        3. 平局: 按利用率升序
        4. 再平局: 按温度升序

        Args:
            min_memory_gb: 最小可用显存（GB）

        Returns:
            GPU 索引列表，如 [0, 1, 3, 2]。无可用 GPU 时返回空列表。
        """
        metrics = self.get_latest()
        if not metrics.available or not metrics.snapshots:
            return []

        min_mib = min_memory_gb * 1024

        eligible = [
            s for s in metrics.snapshots
            if s.memory_free_mb >= min_mib
        ]

        sorted_gpus = sorted(eligible, key=lambda s: (
            -s.memory_free_mb,         # 可用显存降序
            s.utilization_percent,     # 利用率升序
            s.temperature_celsius,     # 温度升序
        ))

        return [s.gpu_index for s in sorted_gpus]

    @property
    def is_available(self) -> bool:
        """NVML 是否成功初始化。"""
        return self._initialized
