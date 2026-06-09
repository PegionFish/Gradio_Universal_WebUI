# adapters/whisperx.py — WhisperX 模型适配器（占位）

from typing import Optional
from adapters.base import BaseModelAdapter


class WhisperXAdapter(BaseModelAdapter):
    """WhisperX 模型适配器。

    当前为占位实现，submit() 抛出 NotImplementedError。
    第二阶段将实现完整的 HTTP 语音识别调用。
    """

    def model_type(self) -> str:
        return "whisperx"

    async def submit(
        self,
        service_url: str,
        payload: dict,
        target_gpu: Optional[list[int]] = None,
    ) -> str:
        raise NotImplementedError(
            "WhisperX 适配器当前为占位状态。"
            "模型推理功能将在未来阶段实现。"
        )


from adapters import register_adapter
register_adapter("whisperx", WhisperXAdapter)
