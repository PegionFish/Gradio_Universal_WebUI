# adapters/fastwhisper.py — FastWhisper 模型适配器（真实实现）

from typing import Optional
import aiohttp
import asyncio
import logging
from adapters.base import BaseModelAdapter

logger = logging.getLogger(__name__)


class FastWhisperAdapter(BaseModelAdapter):
    """FastWhisper 模型适配器 — Phase 3 实现。

    通过 HTTP API 调用外部 FastWhisper 服务。相比 WhisperX，
    FastWhisper 使用 CTranslate2 后端，推理速度更快但无说话人识别。

    HTTP API 约定：
    - POST /v1/transcribe         提交转录任务
    - GET  /v1/status/<task_id>   查询任务状态
    - GET  /health                健康检查
    """

    SUPPORTED_LANGUAGES = [
        "Auto", "zh", "en", "ja", "ko", "yue",
        "de", "fr", "es", "it", "pt", "ru", "ar",
    ]

    def model_type(self) -> str:
        return "fastwhisper"

    async def validate(self, payload: dict) -> list[str]:
        errors = []
        if "audio" not in payload and "audio_path" not in payload:
            errors.append("需要提供 audio（base64）或 audio_path（文件路径）字段")

        lang = payload.get("language", "Auto")
        if lang not in self.SUPPORTED_LANGUAGES:
            errors.append(
                f"不支持的语种: '{lang}'。支持: {', '.join(self.SUPPORTED_LANGUAGES)}"
            )
        return errors

    async def submit(
        self,
        service_url: str,
        payload: dict,
        target_gpu: Optional[list[int]] = None,
    ) -> str:
        """提交音频转录任务。

        Args:
            service_url: 服务基础 URL
            payload:
                - audio: base64 编码音频
                - audio_path: 文件路径
                - language: 语种 (默认 "Auto")
                - model: 模型大小 ("tiny"|"base"|"small"|"medium"|"large-v3")
                - beam_size: beam search 大小 (默认 5)
                - vad_filter: 是否启用 VAD 过滤
                - return_srt: 是否返回 SRT 字幕
            target_gpu: 目标 GPU

        Returns:
            服务侧的任务引用 ID
        """
        url = service_url.rstrip("/") + "/v1/transcribe"

        body = {
            "language": payload.get("language", "Auto"),
            "model": payload.get("model", "large-v3"),
            "beam_size": payload.get("beam_size", 5),
            "vad_filter": payload.get("vad_filter", True),
            "return_srt": payload.get("return_srt", False),
        }

        if "audio" in payload:
            body["audio"] = payload["audio"]
        if "audio_path" in payload:
            body["audio_path"] = payload["audio_path"]
        if target_gpu:
            body["target_gpu"] = target_gpu[0]

        timeout = aiohttp.ClientTimeout(total=300)
        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(url, json=body) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        return data.get("task_id", "")
                    else:
                        text = await resp.text()
                        raise ConnectionError(
                            f"FastWhisper 服务返回 {resp.status}: {text[:200]}"
                        )
        except aiohttp.ClientError as e:
            logger.error("FastWhisper 服务请求失败: %s", e)
            raise ConnectionError(f"无法连接到 FastWhisper 服务: {e}") from e

    async def poll_status(self, service_url: str, task_ref: str) -> dict:
        """查询转录任务状态。"""
        url = f"{service_url.rstrip('/')}/v1/status/{task_ref}"

        try:
            async with aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=10)
            ) as session:
                async with session.get(url) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        return {
                            "status": data.get("status", "unknown"),
                            "result": data.get("result"),
                            "error": data.get("error"),
                            "progress": data.get("progress"),
                        }
                    elif resp.status == 404:
                        return {
                            "status": "unknown", "result": None,
                            "error": f"任务 {task_ref} 未找到", "progress": None,
                        }
                    else:
                        return {
                            "status": "failed", "result": None,
                            "error": f"查询失败: HTTP {resp.status}",
                            "progress": None,
                        }
        except (aiohttp.ClientError, asyncio.TimeoutError) as e:
            return {
                "status": "unknown", "result": None,
                "error": f"查询异常: {e}", "progress": None,
            }


from adapters import register_adapter
register_adapter("fastwhisper", FastWhisperAdapter)
