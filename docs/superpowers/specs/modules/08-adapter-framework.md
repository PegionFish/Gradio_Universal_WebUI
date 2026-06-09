# 模块 8：适配器框架

## 用途

定义模型服务的标准调用接口，隔离 WebUI 主程序与具体模型推理逻辑。第一阶段提供占位实现，第二阶段替换为真实 HTTP 模型服务调用。

## 依赖

- **模块 3**：ServiceRegistry（获取服务 URL、model_type 映射）

### 适配器注册

```python
# adapters/__init__.py

_ADAPTER_REGISTRY: dict[str, type["BaseModelAdapter"]] = {}

def register_adapter(model_type: str, adapter_cls: type["BaseModelAdapter"]):
    _ADAPTER_REGISTRY[model_type] = adapter_cls

def get_adapter(model_type: str) -> "BaseModelAdapter":
    cls = _ADAPTER_REGISTRY.get(model_type)
    if not cls:
        raise ValueError(f"未知的 model_type: {model_type}，没有注册对应的适配器")
    return cls()
```

注册在模块导入时自动完成：

```python
# adapters/stable_diffusion.py 末尾
from adapters import register_adapter
register_adapter("stable-diffusion", StableDiffusionAdapter)

# adapters/qwen3_asr.py 末尾
register_adapter("qwen3-asr", Qwen3ASRAdapter)

# adapters/whisperx.py 末尾
register_adapter("whisperx", WhisperXAdapter)

# adapters/fastwhisper.py 末尾
register_adapter("fastwhisper", FastWhisperAdapter)
```

确保在 `webui/app.py` 或 `main.py` 中导入适配器模块以触发注册：

```python
# main.py 步骤 4 之后
import adapters.stable_diffusion
import adapters.qwen3_asr
import adapters.whisperx
import adapters.fastwhisper
```

## BaseModelAdapter

### 文件位置

`adapters/base.py`

### 抽象基类

```python
from abc import ABC, abstractmethod
from typing import Optional


class BaseModelAdapter(ABC):
    """模型适配器基类。所有模型适配器必须实现此接口。"""
    
    @abstractmethod
    def model_type(self) -> str:
        """返回唯一标识符，与 ServiceRegistry 中的 model_type 匹配。"""
        ...
    
    async def validate(self, payload: dict) -> list[str]:
        """校验请求负载。
        返回校验错误列表，空列表表示校验通过。
        基类默认实现不校验任何字段。
        """
        return []
    
    @abstractmethod
    async def submit(
        self,
        service_url: str,
        payload: dict,
        target_gpu: Optional[list[int]] = None,
    ) -> str:
        """提交任务到模型服务。
        
        参数:
            service_url: 服务的基础 URL（来自 ServiceRegistry）
            payload: 请求参数（模型特定）
            target_gpu: 目标 GPU 索引列表，或 None
        
        返回:
            服务侧的任务引用 ID（用于 poll_status）
        
        可能抛出:
            NotImplementedError: 占位适配器
            ConnectionError: 服务不可达
            ValueError: 无效参数
        """
        ...
    
    async def poll_status(self, service_url: str, task_ref: str) -> dict:
        """查询任务执行状态。
        
        第一阶段无实际调用者（任务状态通过 SQLite 查询）。
        为第二阶段预留的接口。
        
        返回:
            {"status": "running" | "completed" | "failed",
             "result": {...} | None,
             "error": str | None}
        """
        return {"status": "unknown", "result": None, "error": "poll_status 未实现"}
```

## 占位适配器

所有四个占位适配器行为相同：`submit()` 抛出 `NotImplementedError`。

### StableDiffusionAdapter

```python
# adapters/stable_diffusion.py
from adapters.base import BaseModelAdapter

class StableDiffusionAdapter(BaseModelAdapter):
    def model_type(self) -> str:
        return "stable-diffusion"
    
    async def validate(self, payload: dict) -> list[str]:
        errors = []
        if "prompt" not in payload:
            errors.append("prompt 为必填字段")
        return errors
    
    async def submit(self, service_url, payload, target_gpu=None):
        raise NotImplementedError(
            "Stable Diffusion 适配器当前为占位状态。"
            "模型推理功能将在未来阶段实现。"
            "请在服务管理标签页中配置并启动一个兼容的服务。"
        )

# 模块末尾注册
from adapters import register_adapter
register_adapter("stable-diffusion", StableDiffusionAdapter)
```

### Qwen3ASRAdapter

```python
# adapters/qwen3_asr.py
from adapters.base import BaseModelAdapter

class Qwen3ASRAdapter(BaseModelAdapter):
    def model_type(self) -> str:
        return "qwen3-asr"
    
    async def submit(self, service_url, payload, target_gpu=None):
        raise NotImplementedError(
            "Qwen3ASR 适配器当前为占位状态。"
            "模型推理功能将在未来阶段实现。"
        )

from adapters import register_adapter
register_adapter("qwen3-asr", Qwen3ASRAdapter)
```

WhisperX 和 FastWhisper 适配器结构同上，仅 `model_type()` 返回值和文件位置不同。

## 任务错误处理路径

当用户通过 WebUI 提交任务且适配器是占位状态时，完整的错误处理路径：

```text
1. 用户点击"提交"按钮
2. Gradio 回调函数被调用（在 Gradio 线程池中）
3. 回调调用 adapter.submit()
   → 抛出 NotImplementedError
4. 回调中的 try/except 捕获异常
5. scheduler.update_task_status(task_id, "failed",
      error_summary="Stable Diffusion 适配器当前为占位状态",
      error_detail=traceback)
6. result_mgr.save_log(task_id, "error.log", traceback)
7. result_mgr.save_response(task_id, {"error": "...", "status": "failed"})
8. WebUI 显示失败状态和错误摘要
```

```python
# WebUI 页面回调示例
async def on_submit(service_id, prompt, target_gpu):
    task_id = scheduler.create_task(...)
    result_mgr.ensure_task_dir(task_id)
    result_mgr.save_request(task_id, {"prompt": prompt})
    
    try:
        adapter = get_adapter(registry.get(service_id).model_type)
        service_url = registry.get(service_id).service_url
        task_ref = await adapter.submit(service_url, {"prompt": prompt}, target_gpu)
        # 第二阶段: 后续轮询
        scheduler.update_task_status(task_id, "running")
        return task_id, "运行中", ""
        
    except NotImplementedError as e:
        scheduler.update_task_status(task_id, "failed", error_summary=str(e))
        return task_id, "失败", str(e)
    except Exception as e:
        scheduler.update_task_status(task_id, "failed", error_summary=f"提交失败: {e}")
        return task_id, "错误", f"提交失败: {e}"
```

## Stable Diffusion 适配器预留字段

为第二阶段设计，第一阶段仅在代码注释中记录：

```python
# Stable Diffusion 适配器第二阶段将支持的请求负载字段:
# {
#     "prompt": "a cat",           # str, 必填
#     "negative_prompt": "",       # str, 可选
#     "width": 512,                # int, 默认 512
#     "height": 512,               # int, 默认 512
#     "steps": 20,                 # int, 默认 20
#     "cfg_scale": 7.0,           # float, 默认 7.0
#     "seed": -1,                  # int, -1=随机
#     "batch_size": 1,             # int, 默认 1
#     "target_gpu": [0],           # list[int], 可选
# }
```

## 验收标准

1. `BaseModelAdapter` 抽象类实例化时报 `TypeError`
2. `StableDiffusionAdapter().model_type()` 返回 `"stable-diffusion"`
3. 占位适配器的 `submit()` 抛出 `NotImplementedError`
4. 占位适配器的 `poll_status()` 返回 `{"status": "unknown"}`
5. `get_adapter("stable-diffusion")` 返回 `StableDiffusionAdapter` 实例
6. `get_adapter("unknown-model")` 抛出 `ValueError`
7. 适配器注册在模块导入时自动完成（不依赖显式调用）
8. `validate()` 返回正确的校验错误列表
