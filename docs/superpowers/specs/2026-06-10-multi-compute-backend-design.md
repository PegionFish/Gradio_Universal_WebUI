# 多计算后端抽象层设计规范

**日期**：2026-06-10
**状态**：设计完成，待实现
**版本**：1.0

---

## 1. 动机与目标

当前项目仅支持 NVIDIA GPU（通过 pynvml），`ServiceRecord`、`GpuMonitor`、`GpuAllocator` 全部硬绑定 NVIDIA 生态。对于 Whisper 类模型（WhisperX、FastWhisper），完全可以在 NPU / Intel GPU / CPU 上运行，且能效比更优。

### 目标

1. **架构层面支持多计算后端**：NVIDIA GPU、Intel GPU、Intel NPU、AMD NPU、Qualcomm NPU、CPU
2. **不同服务可使用不同后端**：例如 Stable Diffusion 跑 NVIDIA GPU，WhisperX 跑 Intel NPU，互不干扰
3. **向后兼容**：现有功能零破坏，NVIDIA 后端行为不变
4. **占位友好**：非 NVIDIA 后端只定义接口+占位实现，后续按需填充

### 非目标

- 本次不实现 NPU / Intel GPU 的真实监控逻辑（占位即可）
- 不改动 WebUI 仪表盘的 UI 布局（NPU 卡片留到后续）
- 不改变模型服务 HTTP API 的内部推理逻辑

---

## 2. 架构总览

```
                        ┌──────────────────────────────────┐
                        │         WebUI 仪表盘              │
                        │  GPU 卡片 + NPU/Intel GPU 占位    │
                        └──────────────┬───────────────────┘
                                       │ 统一查询接口
                        ┌──────────────▼───────────────────┐
                        │      ComputeAllocator            │
                        │   (原 GpuAllocator，后端无关)      │
                        │   reserve / release / recommend   │
                        └──────────────┬───────────────────┘
                                       │
                        ┌──────────────▼───────────────────┐
                        │   ComputeMonitorRegistry          │
                        │   probe_all() / get(backend_type) │
                        └──────────────┬───────────────────┘
                                       │
              ┌────────────────────────┼────────────────────────┐
              │                        │                        │
    ┌─────────▼─────────┐   ┌─────────▼─────────┐   ┌─────────▼─────────┐
    │ NvidiaGpuMonitor  │   │ IntelGpuMonitor   │   │ IntelNpuMonitor   │
    │ (pynvml, 完整)     │   │ (XPU/sysfs, 占位)  │   │ (OpenVINO, 占位)   │
    └───────────────────┘   └───────────────────┘   └───────────────────┘
              │                        │                        │
    ┌─────────▼────────────────────────▼────────────────────────▼─────────┐
    │                    ComputeMonitor (ABC)                              │
    │  initialize / shutdown / start / stop / collect / recommend         │
    └────────────────────────────────────────────────────────────────────┘
```

### 关键设计决策

| 决策 | 理由 |
|------|------|
| 每个 Monitor 各自管理后台线程 | 各后端采集周期不同，保持独立 |
| `ComputeAllocator` 不关心 backend_type | 分配逻辑与加速器无关，只需 (backend_type, device_index) 二元组 |
| `ComputeMonitorRegistry` 惰性探测 | 启动时按优先级探测可用后端，不可用时优雅降级 |
| NPU/Intel GPU 占位实现抛 `NotImplementedError` | 明确 API 契约，防止运行时意外调用未实现路径 |

---

## 3. 数据模型

### 3.1 ComputeDeviceSnapshot（统一设备快照）

替代现有 `GpuSnapshot`，所有后端共用：

```python
@dataclass
class ComputeDeviceSnapshot:
    backend_type: str           # "gpu:nvidia" | "gpu:intel" | "npu:intel" | "npu:amd" | "npu:qualcomm" | "cpu"
    device_index: int           # 该后端内的设备索引
    name: str                   # 如 "NVIDIA GeForce RTX 4090"
    memory_total_mb: int
    memory_used_mb: int
    memory_free_mb: int
    utilization_percent: int    # 0-100，后端不支持时填 -1
    temperature_celsius: int    # 后端不支持时填 -1
```

### 3.2 ComputeMetrics（聚合指标）

替代现有 `GpuMetrics`：

```python
@dataclass
class ComputeMetrics:
    available: bool
    backend_type: str
    devices: list[ComputeDeviceSnapshot]
    updated_at: str             # ISO 8601
```

### 3.3 ComputeReservation（计算资源预留）

替代现有 `GpuReservation`：

```python
@dataclass
class ComputeReservation:
    backend_type: str           # "gpu:nvidia" | ...
    device_index: int
    service_id: str
    model_type: str
    reserved_memory_gb: int
    created_at: str
```

### 3.4 ServiceRecord 新增字段

```python
compute_backend: str = "gpu:nvidia"
# 可选值: "gpu:nvidia" | "gpu:intel" | "npu:intel" | "npu:amd" | "npu:qualcomm" | "cpu"
```

`from_dict()` 从 YAML 的 `compute.backend` 读取，默认 `"gpu:nvidia"`。现有 `gpu_assignment` 和 `gpu_min_memory_gb` 字段保留，语义变为"计算设备分配"和"最低计算内存需求"。

---

## 4. ComputeMonitor 抽象基类

### 文件：`core/compute_monitor.py`

```python
from abc import ABC, abstractmethod

class ComputeMonitor(ABC):
    """计算后端监控抽象基类。

    每个具体实现负责一种加速器后端。
    降级策略：初始化失败时 available=False，不抛出异常。
    """

    @abstractmethod
    def initialize(self) -> None:
        """初始化后端驱动/库。失败不抛异常，内部标记不可用。"""
        ...

    @abstractmethod
    def shutdown(self) -> None:
        """释放后端资源。"""
        ...

    @abstractmethod
    def start(self, interval_seconds: int) -> None:
        """启动后台采集线程（daemon）。"""
        ...

    @abstractmethod
    def stop(self) -> None:
        """停止后台采集。"""
        ...

    @abstractmethod
    def collect(self) -> ComputeMetrics:
        """采集即时快照。在后台线程中调用。"""
        ...

    @abstractmethod
    def get_latest(self) -> ComputeMetrics:
        """获取最新快照。线程安全。"""
        ...

    @abstractmethod
    def recommend(
        self, min_memory_mb: int, count: int = 1
    ) -> list[ComputeDeviceSnapshot]:
        """返回按可用资源降序排列的设备列表。"""
        ...

    @property
    @abstractmethod
    def is_available(self) -> bool:
        """后端驱动是否初始化成功。"""
        ...

    @property
    @abstractmethod
    def backend_type(self) -> str:
        """返回此后端的 backend_type 字符串标识。"""
        ...
```

### 具体实现清单

| 文件 | 类名 | `backend_type` | 状态 |
|------|------|:---:|------|
| `core/compute_monitor.py` | `ComputeMonitor` (ABC) | — | **新建** |
| `core/compute/nvidia_gpu.py` | `NvidiaGpuMonitor(ComputeMonitor)` | `gpu:nvidia` | **从 `gpu_monitor.py` 重构迁移** |
| `core/compute/intel_gpu.py` | `IntelGpuMonitor(ComputeMonitor)` | `gpu:intel` | 占位 |
| `core/compute/intel_npu.py` | `IntelNpuMonitor(ComputeMonitor)` | `npu:intel` | 占位 |
| `core/compute/amd_npu.py` | `AmdNpuMonitor(ComputeMonitor)` | `npu:amd` | 占位 |
| `core/compute/qualcomm_npu.py` | `QualcommNpuMonitor(ComputeMonitor)` | `npu:qualcomm` | 占位 |
| `core/compute/cpu.py` | `CpuComputeMonitor(ComputeMonitor)` | `cpu` | 占位（psutil 即可实现） |

### NVIDIA 重构要点

- 类名 `GpuMonitor` → `NvidiaGpuMonitor`，继承 `ComputeMonitor`
- `GpuSnapshot` → `ComputeDeviceSnapshot`（`backend_type="gpu:nvidia"` 自动填充）
- `GpuMetrics` → `ComputeMetrics`
- 原有所有 pynvml 逻辑不变，仅适配新接口
- 在 `gpu_monitor.py` 原位置保留兼容性 re-export：`GpuMonitor = NvidiaGpuMonitor`

### 占位实现模板

```python
class IntelNpuMonitor(ComputeMonitor):
    @property
    def backend_type(self) -> str:
        return "npu:intel"

    def initialize(self) -> None:
        logger.warning("Intel NPU 监控尚未实现。返回空指标。")
        self._available = False

    def collect(self) -> ComputeMetrics:
        return ComputeMetrics(
            available=False, backend_type=self.backend_type,
            devices=[], updated_at="",
        )

    def recommend(self, min_memory_mb: int, count: int = 1):
        return []  # 占位：无可用设备

    # ... 其余方法同理返回空/降级值
```

---

## 5. ComputeMonitorRegistry

### 文件：`core/compute_monitor.py`（同文件）

```python
class ComputeMonitorRegistry:
    """管理所有已初始化的 ComputeMonitor 实例。"""

    def __init__(self):
        self._monitors: dict[str, ComputeMonitor] = {}

    def register(self, monitor: ComputeMonitor) -> None:
        """注册一个 Monitor 实例。"""
        self._monitors[monitor.backend_type] = monitor

    def probe_all(self) -> None:
        """按优先级探测并初始化所有已知后端。
        
        探测顺序: NVIDIA GPU → Intel GPU → Intel NPU → AMD NPU → Qualcomm NPU → CPU
        每个后端初始化失败时静默跳过。
        """
        from core.compute.nvidia_gpu import NvidiaGpuMonitor
        from core.compute.intel_gpu import IntelGpuMonitor
        from core.compute.intel_npu import IntelNpuMonitor
        from core.compute.amd_npu import AmdNpuMonitor
        from core.compute.qualcomm_npu import QualcommNpuMonitor
        from core.compute.cpu import CpuComputeMonitor

        for monitor_cls in [
            NvidiaGpuMonitor, IntelGpuMonitor, IntelNpuMonitor,
            AmdNpuMonitor, QualcommNpuMonitor, CpuComputeMonitor,
        ]:
            try:
                monitor = monitor_cls()
                monitor.initialize()
                self.register(monitor)
                if monitor.is_available:
                    logger.info("计算后端 %s 已初始化", monitor.backend_type)
            except Exception as e:
                logger.warning("计算后端 %s 初始化跳过: %s", monitor_cls.__name__, e)

    def get(self, backend_type: str) -> ComputeMonitor | None:
        return self._monitors.get(backend_type)

    def list_available(self) -> list[ComputeMonitor]:
        return [m for m in self._monitors.values() if m.is_available]

    def list_all(self) -> list[ComputeMonitor]:
        return list(self._monitors.values())
```

---

## 6. ComputeAllocator

### 文件：`core/gpu_allocator.py` → 重构为 `core/compute_allocator.py`

从 `GpuAllocator` 重构而来，核心变更：

| 旧 | 新 |
|----|----|
| `gpu_index: int` | `(backend_type: str, device_index: int)` |
| 依赖 `gpu_monitor` 模块变量 | 通过 `compute_registry.get(backend_type)` 获取对应 Monitor |
| `GpuReservation` | `ComputeReservation` |
| `_reservations: dict[int, list]` | `_reservations: dict[tuple[str, int], list]` |

关键方法签名：

```python
class ComputeAllocator:
    def reserve(
        self, backend_type: str, device_index: int,
        service_id: str, model_type: str, memory_gb: int,
    ) -> bool: ...

    def release(self, backend_type: str, device_index: int, service_id: str) -> None: ...

    def release_all_for_service(self, service_id: str) -> None: ...

    def recommend_device(
        self, backend_type: str, required_memory_gb: int,
        preferred_model_type: str | None = None,
        exclude_devices: list[int] | None = None,
    ) -> list[ComputeDeviceSnapshot]: ...

    def detect_conflicts(self) -> list[dict]: ...
```

原本从 `core.gpu_monitor` 导入全局单例的逻辑改为通过 `compute_registry` 查找对应 Monitor。`core.__init__` 中的模块级变量 `gpu_monitor` 替换为 `compute_registry` 和 `allocator`。

### 全局单例获取

```python
_allocator_instance: ComputeAllocator | None = None

def get_allocator() -> ComputeAllocator:
    global _allocator_instance
    if _allocator_instance is None:
        _allocator_instance = ComputeAllocator()
    return _allocator_instance
```

---

## 7. EventBus 事件

| 旧事件名 | 新事件名 | 变更 |
|---------|---------|------|
| `gpu_metrics_updated` | `compute_metrics_updated` | data 新增 `backend_type` 字段，`gpus` → `devices` |
| `gpu_reservation_changed` | `compute_reservation_changed` | data 中 `gpu_index` → `device_index`，新增 `backend_type` |

**向后兼容**：旧事件名保留发布 2 个版本（通过 `bus.emit` 同时发布新旧事件），过渡期后移除。

---

## 8. 核心模块变更

### `core/__init__.py`

```python
# 移除
gpu_monitor: GpuMonitor = None

# 新增
compute_registry: ComputeMonitorRegistry = None
allocator: ComputeAllocator = None
```

`setup_core()` 中：
```python
from core.compute_monitor import ComputeMonitorRegistry
from core.compute_allocator import get_allocator

compute_registry = ComputeMonitorRegistry()
compute_registry.probe_all()

allocator = get_allocator()
```

`main.py` 中启动顺序不变，但将 `gpu_monitor.start(...)` 替换为遍历 `compute_registry.list_available()` 并调用各自的 `start()`。

---

## 9. 配置文件格式

### `config/services.yaml`

```yaml
services:
  - id: whisperx
    display_name: "WhisperX ASR"
    model_type: "whisperx"
    enabled: false
    compute:
      backend: "gpu:nvidia"        # 新增字段，默认 "gpu:nvidia"
      min_memory_gb: 4             # 原 gpu.min_memory_gb
      assignment: []               # 原 gpu.assignment
    service_url: "http://localhost:8200"
    health_endpoint: "/health"
    start:
      command: "python services/whisperx_service.py --port 8200"
      working_dir: "."
      env: {}
      stop_timeout_seconds: 30
```

`ServiceRecord.from_dict()` 适配：
```python
compute = d.get("compute", {})
gpu = d.get("gpu", {})  # 向后兼容旧配置格式

backend = compute.get("backend") or "gpu:nvidia"
min_mem = compute.get("min_memory_gb") or gpu.get("min_memory_gb", 0)
assignment = compute.get("assignment") or gpu.get("assignment", [])
```

---

## 10. WebUI 影响

### 本次不改动的部分

- `webui/pages/gpu.py` — GPU 卡片布局不变
- `webui/components/gpu_dashboard.py` — 渲染逻辑不变
- `webui/pages/system.py` — 系统监控页不变

### 需要适配的部分

| 文件 | 变更 |
|------|------|
| `webui/pages/gpu.py` | `app_state` 中 `gpu_metrics` → 从 `compute_registry.get("gpu:nvidia")` 获取；变量名保持 `gpu_metrics` 不变 |
| `webui/pages/dashboard.py` | 同上，只调整数据源 |
| `main.py` | Step 7 中 `app_state` 的初始数据填充逻辑适配新结构 |

---

## 11. 目录结构

```
core/
├── __init__.py                   # 修改：变量替换
├── compute_monitor.py            # 新建：ABC + ComputeDeviceSnapshot + ComputeMetrics + Registry
├── compute/
│   ├── __init__.py               # 新建
│   ├── nvidia_gpu.py             # 从 gpu_monitor.py 重构
│   ├── intel_gpu.py              # 新建：占位
│   ├── intel_npu.py              # 新建：占位
│   ├── amd_npu.py                # 新建：占位
│   ├── qualcomm_npu.py           # 新建：占位
│   └── cpu.py                    # 新建：占位（psutil 快速实现）
├── compute_allocator.py          # 从 gpu_allocator.py 重构
├── gpu_monitor.py                # 保留兼容性 re-export（NvidiaGpuMonitor as GpuMonitor）
├── gpu_allocator.py              # 保留兼容性 re-export（ComputeAllocator as GpuAllocator）
└── ... (其他文件不变)
```

`gpu_monitor.py` 和 `gpu_allocator.py` 保留为兼容性模块（re-export），2 个版本后移除。

---

## 12. 测试策略

### 现有测试

- `tests/test_gpu_monitor.py` — 适配 `NvidiaGpuMonitor` 类名，逻辑不变
- `tests/test_gpu_allocator.py` — 适配 `ComputeAllocator` 签名
- 其余 177 个测试需保持全绿

### 新增测试

| 文件 | 覆盖内容 |
|------|---------|
| `tests/test_compute_monitor.py` | `ComputeDeviceSnapshot` 数据类、`ComputeMetrics` 序列化 |
| `tests/test_compute_monitor_registry.py` | `ComputeMonitorRegistry` 注册/查找/降级 |
| `tests/test_compute_allocator.py` | 多后端预留/释放/冲突检测 |
| `tests/test_nvidia_gpu_monitor.py` | `NvidiaGpuMonitor` 初始化和降级（mock pynvml） |
| `tests/test_service_record_compute.py` | `ServiceRecord` 解析 `compute.backend` 字段 |

---

## 13. 风险与缓解

| 风险 | 缓解 |
|------|------|
| 重构破坏现有 NVIDIA GPU 功能 | 兼容性 re-export + 全量测试回归 |
| NPU 没有统一的监控 API | 不强行统一，每个 Monitor 独立实现，不可用时返回空/降级 |
| `compute_registry` 初始化失败导致整个 `setup_core()` 崩溃 | `probe_all()` 逐后端 try/except，单后端失败不传播 |

---

## 14. 后续路线图

1. **Phase 1（本次）**：架构抽象 + NVIDIA 重构 + 占位实现
2. **Phase 2（未来）**：选择目标 NPU/Intel GPU 平台，实现真实 Monitor（至少 `collect()` 能查询设备基本信息）
3. **Phase 3（未来）**：WebUI 仪表盘展示多类型加速器卡片
4. **Phase 4（未来）**：`ComputeAllocator.recommend_device()` 支持跨后端迁移（如 GPU 繁忙时自动推荐 NPU）
