# tests/test_gpu_monitor.py

import pytest
from unittest.mock import patch, MagicMock
from core.gpu_monitor import (
    GpuMonitor, GpuSnapshot, GpuMetrics,
)
from core.gpu_allocator import GpuAllocator, GpuReservation


class TestGpuSnapshot:
    def test_gpu_snapshot_fields(self):
        snap = GpuSnapshot(
            gpu_index=0,
            name="NVIDIA GeForce RTX 4090",
            memory_total_mb=24564,
            memory_used_mb=8192,
            memory_free_mb=16372,
            utilization_percent=45,
            memory_utilization_percent=33,
            temperature_celsius=62,
            power_milliwatts=250000,
            processes=[{"pid": 1234, "used_memory_mb": 4096}],
        )
        assert snap.gpu_index == 0
        assert snap.name == "NVIDIA GeForce RTX 4090"
        assert snap.memory_free_mb == 16372
        assert snap.utilization_percent == 45
        assert len(snap.processes) == 1

    def test_gpu_snapshot_default_processes(self):
        snap = GpuSnapshot(0, "Test", 8192, 1024, 7168, 10, 5, 40, 100000)
        assert snap.processes == []


class TestGpuMetrics:
    def test_gpu_metrics_structure(self):
        snap = GpuSnapshot(0, "GPU0", 8192, 4096, 4096, 50, 30, 60, 150000)
        metrics = GpuMetrics(
            available=True,
            snapshots=[snap],
            updated_at="2026-06-10T00:00:00Z",
        )
        assert metrics.available is True
        assert len(metrics.snapshots) == 1

    def test_gpu_metrics_unavailable(self):
        metrics = GpuMetrics(available=False, snapshots=[], updated_at="")
        assert metrics.available is False
        assert metrics.snapshots == []


class TestGpuMonitorDegraded:
    """验收标准 1: initialize 在无 NVIDIA GPU 环境下降级不抛异常。"""

    def test_initialize_degraded(self):
        monitor = GpuMonitor()
        monitor.initialize()
        assert monitor.is_available is False

    def test_initialize_with_no_pynvml(self):
        """确认在无 pynvml 时降级而非崩溃。"""
        with patch("core.gpu_monitor.GpuMonitor.initialize",
                   side_effect=ImportError("No pynvml")):
            monitor = GpuMonitor()
            try:
                monitor.initialize()
            except ImportError:
                pass
            # 即使 initialize 失败，monitor 不应崩溃

    def test_get_latest_on_degraded(self):
        monitor = GpuMonitor()
        monitor.initialize()
        metrics = monitor.get_latest()
        assert metrics.available is False
        assert metrics.snapshots == []

    def test_recommend_on_degraded(self):
        monitor = GpuMonitor()
        monitor.initialize()
        assert monitor.recommend() == []
        assert monitor.recommend(min_memory_gb=4) == []

    def test_shutdown_degraded(self):
        monitor = GpuMonitor()
        monitor.initialize()
        monitor.shutdown()  # 不应报错


class TestGpuMonitorRecommend:
    """验收标准 3-4: recommend 排序和过滤。"""

    def make_monitor_with_snapshots(self, snapshots):
        """辅助: 创建已注入快照的 monitor。"""
        monitor = GpuMonitor()
        monitor._initialized = True
        monitor._latest = GpuMetrics(
            available=True,
            snapshots=snapshots,
            updated_at="2026-06-10T00:00:00Z",
        )
        return monitor

    def test_recommend_orders_by_free_memory_desc(self):
        monitor = self.make_monitor_with_snapshots([
            GpuSnapshot(0, "GPU0", 8192, 4096, 4096, 80, 50, 75, 200000),
            GpuSnapshot(1, "GPU1", 8192, 1024, 7168, 10, 10, 40, 100000),
            GpuSnapshot(2, "GPU2", 8192, 7168, 1024, 30, 80, 60, 150000),
        ])
        # GPU2 只有 1024 MB free -> 4GB filter 排除
        # GPU1 7168 free > GPU0 4096 free
        rec = monitor.recommend(min_memory_gb=4)
        assert rec == [1, 0]

    def test_recommend_filters_by_min_memory(self):
        monitor = self.make_monitor_with_snapshots([
            GpuSnapshot(0, "GPU0", 8192, 1024, 7168, 10, 10, 40, 100000),
            GpuSnapshot(1, "GPU1", 8192, 6144, 2048, 30, 50, 50, 150000),
        ])
        rec = monitor.recommend(min_memory_gb=8)
        assert rec == []  # 没有 GPU 有 8GB 空闲显存

    def test_recommend_tiebreak_utilization(self):
        # 两个 GPU 空闲显存相同，利用率低的排名更前
        monitor = self.make_monitor_with_snapshots([
            GpuSnapshot(0, "GPU0", 8192, 1024, 7168, 80, 50, 70, 200000),
            GpuSnapshot(1, "GPU1", 8192, 1024, 7168, 20, 30, 60, 100000),
        ])
        rec = monitor.recommend(min_memory_gb=4)
        assert rec == [1, 0]  # GPU1 利用率更低

    def test_recommend_tiebreak_temperature(self):
        monitor = self.make_monitor_with_snapshots([
            GpuSnapshot(0, "GPU0", 8192, 1024, 7168, 20, 30, 80, 200000),
            GpuSnapshot(1, "GPU1", 8192, 1024, 7168, 20, 30, 50, 100000),
        ])
        rec = monitor.recommend(min_memory_gb=4)
        assert rec == [1, 0]  # GPU1 温度更低


class TestGpuCollect:
    """测试 _collect 在有 NVML 时的行为。"""

    def test_collect_with_nvml_mock(self):
        """模拟 NVML 返回 1 张 GPU 的数据。"""
        mock_pynvml = MagicMock()
        mock_pynvml.nvmlDeviceGetCount.return_value = 1
        mock_handle = MagicMock()
        mock_pynvml.nvmlDeviceGetHandleByIndex.return_value = mock_handle
        mock_pynvml.nvmlDeviceGetName.return_value = b"Test GPU"
        mock_pynvml.nvmlDeviceGetMemoryInfo.return_value = MagicMock(
            total=8589934592, used=4294967296, free=4294967296,
        )
        mock_pynvml.nvmlDeviceGetUtilizationRates.return_value = MagicMock(
            gpu=50, memory=30,
        )
        mock_pynvml.nvmlDeviceGetTemperature.return_value = 65
        mock_pynvml.nvmlDeviceGetPowerUsage.return_value = 150000
        mock_pynvml.NVML_TEMPERATURE_GPU = 0

        # Mock running processes
        mock_proc = MagicMock()
        mock_proc.pid = 1234
        mock_proc.usedGpuMemory = 4294967296  # 4 GiB in bytes
        mock_pynvml.nvmlDeviceGetComputeRunningProcesses.return_value = [mock_proc]
        mock_pynvml.NVMLError = Exception

        with patch.dict("sys.modules", {"pynvml": mock_pynvml}):
            monitor = GpuMonitor()
            monitor._initialized = True
            metrics = monitor._collect()

        assert metrics.available is True
        assert len(metrics.snapshots) == 1
        snap = metrics.snapshots[0]
        assert snap.gpu_index == 0
        assert snap.memory_total_mb == 8192  # 8 GiB
        assert snap.memory_used_mb == 4096   # 4 GiB
        assert snap.memory_free_mb == 4096
        assert snap.utilization_percent == 50
        assert snap.temperature_celsius == 65
        assert len(snap.processes) == 1
        assert snap.processes[0]["pid"] == 1234
        assert snap.processes[0]["used_memory_mb"] == 4096

    def test_collect_with_nvml_error(self):
        mock_pynvml = MagicMock()
        mock_pynvml.nvmlDeviceGetCount.side_effect = RuntimeError("NVML error")

        with patch.dict("sys.modules", {"pynvml": mock_pynvml}):
            monitor = GpuMonitor()
            monitor._initialized = True
            metrics = monitor._collect()

        assert metrics.available is False
