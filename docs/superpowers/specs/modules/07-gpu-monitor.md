# 模块 7：GPU 监控

## 用途

通过 NVML 采集 NVIDIA GPU 指标，提供 GPU 状态仪表盘数据和推荐排序逻辑。

## 依赖

- **模块 1**：项目骨架
- **模块 3**：EventBus（`gpu_metrics_updated` 事件）
- Python 包：`nvidia-ml-py>=12.0`（pynvml）
- 运行环境：NVIDIA GPU + 驱动程序

## GpuMonitor

### 文件位置

`core/gpu_monitor.py`

### 数据结构

```python
from dataclasses import dataclass
from typing import Optional


@dataclass
class GpuSnapshot:
    gpu_index: int
    name: str                         # 如 "NVIDIA GeForce RTX 4090"
    memory_total_mb: int
    memory_used_mb: int
    memory_free_mb: int
    utilization_percent: int           # 0-100
    memory_utilization_percent: int    # 0-100
    temperature_celsius: int
    power_milliwatts: int
    processes: list[dict]              # [{"pid": ..., "used_memory_mb": ...}]


@dataclass
class GpuMetrics:
    available: bool                    # NVML 是否初始化成功
    snapshots: list[GpuSnapshot]
    updated_at: str                    # ISO 8601
```

### 实现

```python
import threading
import datetime
import logging
from typing import Optional
from core.event_bus import bus, Event

logger = logging.getLogger("core.gpu_monitor")


class GpuMonitor:
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
        """启动后台采集线程。"""
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
        self._shutdown.set()
    
    def _refresh_loop(self, interval: int):
        while not self._shutdown.is_set():
            snapshot = self._collect()
            with self._lock:
                self._latest = snapshot
            
            if snapshot.available:
                bus.emit(Event("gpu_metrics_updated", {
                    "gpus": [
                        {"index": s.gpu_index, "name": s.name,
                         "memory_free_mb": s.memory_free_mb,
                         "utilization_percent": s.utilization_percent,
                         "temperature_celsius": s.temperature_celsius}
                        for s in snapshot.snapshots
                    ],
                }))
            
            self._shutdown.wait(interval)
    
    def _collect(self) -> GpuMetrics:
        """采集所有 GPU 指标。调用者在后台线程中调用。"""
        if not self._initialized:
            return GpuMetrics(available=False, snapshots=[], updated_at="")
        
        try:
            import pynvml
            
            device_count = pynvml.nvmlDeviceGetCount()
            snapshots = []
            
            for i in range(device_count):
                handle = pynvml.nvmlDeviceGetHandleByIndex(i)
                
                name = pynvml.nvmlDeviceGetName(handle)
                mem_info = pynvml.nvmlDeviceGetMemoryInfo(handle)
                util = pynvml.nvmlDeviceGetUtilizationRates(handle)
                temp = pynvml.nvmlDeviceGetTemperature(handle, pynvml.NVML_TEMPERATURE_GPU)
                power = pynvml.nvmlDeviceGetPowerUsage(handle)
                
                processes = []
                try:
                    procs = pynvml.nvmlDeviceGetComputeRunningProcesses(handle)
                    processes = [
                        {"pid": p.pid, "used_memory_mb": p.usedGpuMemory // (1024*1024)}
                        for p in procs if p.usedGpuMemory is not None
                    ]
                except pynvml.NVMLError:
                    pass
                
                snapshots.append(GpuSnapshot(
                    gpu_index=i,
                    name=name.decode() if isinstance(name, bytes) else str(name),
                    memory_total_mb=mem_info.total // (1024*1024),
                    memory_used_mb=mem_info.used // (1024*1024),
                    memory_free_mb=mem_info.free // (1024*1024),
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
        
        返回 GPU 索引列表，如 [0, 1, 3, 2]。
        推荐仅为建议，不阻止用户选择其他 GPU。
        """
        metrics = self.get_latest()
        if not metrics.available or not metrics.snapshots:
            return []
        
        min_mib = min_memory_gb * 1024
        
        eligible = [s for s in metrics.snapshots if s.memory_free_mb >= min_mib]
        sorted_gpus = sorted(eligible, key=lambda s: (
            -s.memory_free_mb,    # 可用显存降序
            s.utilization_percent, # 利用率升序
            s.temperature_celsius   # 温度升序
        ))
        
        return [s.gpu_index for s in sorted_gpus]
```

## 采集指标总表

| 指标 | NVML 函数 | 返回单位 | 在 snapshot 中的字段 |
|------|-----------|---------|-------------------|
| GPU 索引 | `nvmlDeviceGetIndex` | int | `gpu_index` |
| GPU 名称 | `nvmlDeviceGetName` | string | `name` |
| 总显存 | `nvmlDeviceGetMemoryInfo.total` | bytes → MiB | `memory_total_mb` |
| 已用显存 | `nvmlDeviceGetMemoryInfo.used` | bytes → MiB | `memory_used_mb` |
| 空闲显存 | `nvmlDeviceGetMemoryInfo.free` | bytes → MiB | `memory_free_mb` |
| GPU 利用率 | `nvmlDeviceGetUtilizationRates.gpu` | percentage | `utilization_percent` |
| 显存利用率 | `nvmlDeviceGetUtilizationRates.memory` | percentage | `memory_utilization_percent` |
| 温度 | `nvmlDeviceGetTemperature(GPU)` | Celsius | `temperature_celsius` |
| 功耗 | `nvmlDeviceGetPowerUsage` | milliwatts | `power_milliwatts` |
| 运行中进程 | `nvmlDeviceGetComputeRunningProcesses` | (pid, usedMem) | `processes` |

## 降级处理

NVML 初始化失败时：
- `get_latest()` 返回 `available=False` 的快照
- `recommend()` 返回空列表
- GPU 监控标签页显示：**"未检测到 NVIDIA GPU。GPU 监控功能不可用。"**
- 任务提交流程正常进行，不附带 GPU 推荐或警告

此判定在 GpuMonitor 初始化时只做一次，不在每次采集时重复。首次 initialize 失败后 `self._initialized = False` 永久保持。

## 集成点

在 `main.py` 步骤 5 中：

```python
from core.gpu_monitor import GpuMonitor

gpu_monitor = GpuMonitor()
gpu_monitor.start(interval_seconds=config.get_refresh_setting("gpu_metrics_seconds", 5))
```

## 验收标准

1. `GpuMonitor.initialize()` 在无 NVIDIA GPU 环境下降级（不抛出异常）
2. 有 GPU 时 `get_latest()` 返回正确的 GPU 数量和指标
3. `recommend(min_memory_gb=8)` 排序正确：可用显存优先
4. `recommend()` 返回的列表不包含不满足显存要求的 GPU
5. 后台线程每 interval 秒刷新一次指标
6. 无 NVIDIA 环境时 UI 显示降级提示
7. 线程安全：`get_latest()` 在不同线程调用不产生竞态

## 测试注意事项

测试文件中 `test_gpu_monitor.py` 需 mock `pynvml` 模块：

```python
# tests/test_gpu_monitor.py
from unittest.mock import patch, MagicMock

# 使用 @patch("core.gpu_monitor.pynvml") 模拟 NVML 调用
# 测试 initialize() / get_latest() / recommend() / 降级路径
```
