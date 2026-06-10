# adapters/qwen3_asr.py — Qwen3 ASR 模型适配器（真实实现）

from typing import Optional
import aiohttp
import asyncio
import logging
from adapters.base import BaseModelAdapter

logger = logging.getLogger(__name__)


class Qwen3ASRAdapter(BaseModelAdapter):
    """Qwen3 ASR 模型适配器 — 第二阶段实现。

    通过 HTTP API 调用外部 Qwen3ASR 服务。支持：
    - 音频文件上传和转录
    - 语种选择 (Auto/zh/en/ja/ko...)
    - 时间戳对齐和 SRT 字幕输出
    - 任务状态轮询

    HTTP API 约定（适配器期望的服务端点）：
    - POST /v1/transcribe — 提交音频转录任务
    - GET  /v1/status/{task_id} — 查询任务状态
    - GET  /health — 健康检查
    """

    # 支持的语种列表
    SUPPORTED_LANGUAGES = [
        "Auto", "zh", "en", "ja", "ko", "yue",
        "de", "fr", "es", "it", "pt", "ru", "ar",
    ]

    def model_type(self) -> str:
        return "qwen3-asr"

    async def validate(self, payload: dict) -> list[str]:
        """校验请求负载。"""
        errors = []
        # audio 字段可选（可为文件路径或 base64），但转录时需要
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
        """提交音频转录任务到 Qwen3ASR 服务。

        Args:
            service_url: 服务的基础 URL（如 http://localhost:8100）
            payload: 请求参数
                - audio: base64 编码的音频数据（可选）
                - audio_path: 音频文件路径（可选）
                - language: 语种代码（默认 "Auto"）
                - return_timestamps: 是否返回时间戳（默认 True）
                - return_srt: 是否返回 SRT 字幕（默认 False）
            target_gpu: 目标 GPU 索引列表（Qwen3ASR 固定用单 GPU）

        Returns:
            服务侧的任务引用 ID

        Raises:
            ConnectionError: 服务不可达
            aiohttp.ClientError: HTTP 请求失败
        """
        url = service_url.rstrip("/") + "/v1/transcribe"

        # 构建请求体
        body = {
            "language": payload.get("language", "Auto"),
            "return_timestamps": payload.get("return_timestamps", True),
            "return_srt": payload.get("return_srt", False),
        }

        # 支持 audio（base64）或 audio_path
        if "audio" in payload:
            body["audio"] = payload["audio"]
        if "audio_path" in payload:
            body["audio_path"] = payload["audio_path"]
        if target_gpu:
            body["target_gpu"] = target_gpu[0]  # Qwen3ASR 单 GPU

        timeout = aiohttp.ClientTimeout(total=300)  # 5 分钟超时
        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(url, json=body) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        return data.get("task_id", "")
                    else:
                        text = await resp.text()
                        raise ConnectionError(
                            f"Qwen3ASR 服务返回 {resp.status}: {text[:200]}"
                        )
        except aiohttp.ClientError as e:
            logger.error("Qwen3ASR 服务请求失败: %s", e)
            raise ConnectionError(f"无法连接到 Qwen3ASR 服务: {e}") from e
        except asyncio.TimeoutError:
            raise ConnectionError("Qwen3ASR 服务请求超时（300秒）")

    async def poll_status(self, service_url: str, task_ref: str) -> dict:
        """查询 Qwen3ASR 转录任务状态。

        Args:
            service_url: 服务基础 URL
            task_ref: 任务引用 ID（来自 submit() 返回值）

        Returns:
            {
                "status": "running" | "completed" | "failed",
                "result": {
                    "text": "转录文本",
                    "segments": [...],
                    "srt": "SRT 字幕内容（可选）"
                } | None,
                "error": str | None
            }
        """
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
                        }
                    elif resp.status == 404:
                        return {
                            "status": "unknown",
                            "result": None,
                            "error": f"任务 {task_ref} 未找到",
                        }
                    else:
                        return {
                            "status": "failed",
                            "result": None,
                            "error": f"状态查询失败: HTTP {resp.status}",
                        }
        except (aiohttp.ClientError, asyncio.TimeoutError) as e:
            return {
                "status": "unknown",
                "result": None,
                "error": f"状态查询异常: {e}",
            }


from adapters import register_adapter
register_adapter("qwen3-asr", Qwen3ASRAdapter)
