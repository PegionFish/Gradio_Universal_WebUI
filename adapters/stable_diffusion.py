# adapters/stable_diffusion.py — Stable Diffusion 模型适配器（占位）

from typing import Optional
from adapters.base import BaseModelAdapter


class StableDiffusionAdapter(BaseModelAdapter):
    """Stable Diffusion 模型适配器。

    当前为占位实现，submit() 抛出 NotImplementedError。
    第二阶段将实现完整的 HTTP 推理调用。

    预留字段（第二阶段）:
        prompt: str, 必填
        negative_prompt: str, 可选
        width: int, 默认 512
        height: int, 默认 512
        steps: int, 默认 20
        cfg_scale: float, 默认 7.0
        seed: int, -1=随机
        batch_size: int, 默认 1
    """

    def model_type(self) -> str:
        return "stable-diffusion"

    async def validate(self, payload: dict) -> list[str]:
        errors = []
        if "prompt" not in payload:
            errors.append("prompt 为必填字段")
        return errors

    async def submit(
        self,
        service_url: str,
        payload: dict,
        target_gpu: Optional[list[int]] = None,
    ) -> str:
        raise NotImplementedError(
            "Stable Diffusion 适配器当前为占位状态。"
            "模型推理功能将在未来阶段实现。"
            "请在服务管理标签页中配置并启动一个兼容的服务。"
        )


from adapters import register_adapter
register_adapter("stable-diffusion", StableDiffusionAdapter)
