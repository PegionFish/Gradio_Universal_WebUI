# adapters/whisperx.py — WhisperX 模型适配器（真实实现）

from typing import Optional
import aiohttp
import asyncio
import logging
from adapters.base import BaseModelAdapter

logger = logging.getLogger(__name__)


class WhisperXAdapter(BaseModelAdapter):
    """WhisperX 模型适配器 — Phase 3 实现。

    通过 HTTP API 调用外部 WhisperX 服务。支持：
    - 音频转录（wav/mp3/flac/m4a）
    - 语种检测（Auto/zh/en/ja/ko/...）
    - 说话人识别（diarization）
    - 词级时间戳对齐

    HTTP API 约定：
    - POST /v1/transcribe         提交转录任务
    - GET  /v1/status/<task_id>   查询任务状态
    - GET  /health                健康检查
    """

    SUPPORTED_LANGUAGES = [
        "Auto", "zh", "en", "ja", "ko", "yue",
        "de", "fr", "es", "it", "pt", "ru", "ar", "nl", "sv",
    ]

    def model_type(self) -> str:
        return "whisperx"

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
                - audio_path: 文件路径（二选一）
                - language: 语种 (默认 "Auto")
                - model: whisper 模型名 (如 "large-v3")
                - enable_diarization: 是否启用说话人识别
                - return_timestamps: 是否返回时间戳
                - return_srt: 是否返回 SRT 字幕
            target_gpu: 目标 GPU

        Returns:
            服务侧的任务引用 ID
        """
        url = service_url.rstrip("/") + "/v1/transcribe"

        body = {
            "language": payload.get("language", "Auto"),
            "model": payload.get("model", "large-v3"),
            "enable_diarization": payload.get("enable_diarization", False),
            "return_timestamps": payload.get("return_timestamps", True),
            "return_srt": payload.get("return_srt", False),
        }

        if "audio" in payload:
            body["audio"] = payload["audio"]
        if "audio_path" in payload:
            body["audio_path"] = payload["audio_path"]
        if target_gpu:
            body["target_gpu"] = target_gpu[0]

        timeout = aiohttp.ClientTimeout(total=600)
        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(url, json=body) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        return data.get("task_id", "")
                    else:
                        text = await resp.text()
                        raise ConnectionError(
                            f"WhisperX 服务返回 {resp.status}: {text[:200]}"
                        )
        except aiohttp.ClientError as e:
            logger.error("WhisperX 服务请求失败: %s", e)
            raise ConnectionError(f"无法连接到 WhisperX 服务: {e}") from e

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
register_adapter("whisperx", WhisperXAdapter)
