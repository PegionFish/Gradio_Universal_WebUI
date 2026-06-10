# adapters/qwen3_streaming.py — Qwen3 ASR 流式适配器 (vLLM backend)

"""
适配 Qwen3-ASR-Stream-Docker 的 /api/start → /api/chunk → /api/finish 协议。

协议说明（与批处理 /v1/transcribe 完全不同）:
    POST /api/start              → {"session_id": "..."}
    POST /api/chunk?session_id=X → {"language": "...", "text": "..."}
        Content-Type: application/octet-stream
        Body: float32 16kHz mono raw bytes (每 500ms 一段，即 8000 samples)
    POST /api/finish?session_id=X → {"language": "...", "text": "..."}

会话 TTL: 10 分钟
"""

import struct
import logging
from typing import Optional, AsyncGenerator

import aiohttp
import numpy as np

from adapters.base import BaseModelAdapter

logger = logging.getLogger(__name__)


class Qwen3StreamingAdapter(BaseModelAdapter):
    """Qwen3 ASR 流式适配器 — vLLM 后端实时转录。

    与此项目配套的 Docker 镜像: qwen3_asr_stream:dsx001
    启动方式:
        docker compose --profile streaming up -d qwen3-stream
    或:
        docker run --gpus all -p 8000:8000 qwen3_asr_stream:dsx001
    """

    SUPPORTED_LANGUAGES = [
        "Auto", "zh", "en", "ja", "ko", "yue",
        "de", "fr", "es", "it", "pt", "ru", "ar",
    ]

    def model_type(self) -> str:
        return "qwen3-asr-streaming"

    async def validate(self, payload: dict) -> list[str]:
        errors = []
        lang = payload.get("language", "Auto")
        if lang not in self.SUPPORTED_LANGUAGES:
            errors.append(
                f"不支持的语种: '{lang}'。支持: {', '.join(self.SUPPORTED_LANGUAGES)}"
            )
        return errors

    # ── 批处理 submit/poll_status 继承基类默认实现 ──
    # 流式适配器的主要接口是下面的 session API

    async def submit(
        self,
        service_url: str,
        payload: dict,
        target_gpu: Optional[list[int]] = None,
    ) -> str:
        """流式适配器的 submit 不是真正批处理——返回占位 ID。"""
        return "streaming-not-applicable"

    # ═════════════════════════════════════════════════════════
    # 流式 API
    # ═════════════════════════════════════════════════════════

    async def start_session(self, service_url: str) -> dict:
        """创建流式转录会话。

        Args:
            service_url: 服务 URL（如 http://localhost:8000）

        Returns:
            {"session_id": "hex-string"}

        Raises:
            ConnectionError: 服务不可达
        """
        url = service_url.rstrip("/") + "/api/start"
        try:
            async with aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=10)
            ) as session:
                async with session.post(url) as resp:
                    if resp.status == 200:
                        return await resp.json()
                    text = await resp.text()
                    raise ConnectionError(
                        f"流式 ASR start 失败: HTTP {resp.status}: {text[:200]}"
                    )
        except aiohttp.ClientError as e:
            raise ConnectionError(f"无法连接流式 ASR 服务: {e}") from e

    async def send_chunk(
        self, service_url: str, session_id: str, audio_chunk: np.ndarray,
    ) -> dict:
        """发送一个音频块到流式会话。

        Args:
            service_url: 服务 URL
            session_id: 会话 ID（来自 start_session）
            audio_chunk: float32 16kHz mono 的 numpy 数组

        Returns:
            {"language": "zh", "text": "增量文本"} 或 {"error": "..."}

        Raises:
            ConnectionError, ValueError
        """
        if audio_chunk.dtype != np.float32:
            audio_chunk = audio_chunk.astype(np.float32)

        url = f"{service_url.rstrip('/')}/api/chunk?session_id={session_id}"
        raw_bytes = audio_chunk.tobytes()

        try:
            async with aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=5)
            ) as session:
                async with session.post(
                    url,
                    data=raw_bytes,
                    headers={"Content-Type": "application/octet-stream"},
                ) as resp:
                    if resp.status == 200:
                        return await resp.json()
                    text = await resp.text()
                    raise ConnectionError(
                        f"chunk 发送失败: HTTP {resp.status}: {text[:200]}"
                    )
        except aiohttp.ClientError as e:
            raise ConnectionError(f"chunk 请求异常: {e}") from e

    async def finish_session(
        self, service_url: str, session_id: str,
    ) -> dict:
        """结束流式会话，获取最终转录结果。

        Returns:
            {"language": "zh", "text": "完整转录文本"}
        """
        url = f"{service_url.rstrip('/')}/api/finish?session_id={session_id}"
        try:
            async with aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=30)
            ) as session:
                async with session.post(url) as resp:
                    if resp.status == 200:
                        return await resp.json()
                    text = await resp.text()
                    raise ConnectionError(
                        f"finish 失败: HTTP {resp.status}: {text[:200]}"
                    )
        except aiohttp.ClientError as e:
            raise ConnectionError(f"finish 请求异常: {e}") from e

    # ═════════════════════════════════════════════════════════
    # 高级接口：模拟流式转录（完整音频 → 分块发送 → 收集中间结果）
    # ═════════════════════════════════════════════════════════

    async def transcribe_streaming(
        self,
        service_url: str,
        audio_16k: np.ndarray,
        chunk_ms: int = 500,
        on_progress=None,
    ) -> dict:
        """将完整音频按块大小分片发送，模拟流式转录。

        Args:
            service_url: 服务 URL
            audio_16k: float32 16kHz mono 的完整音频 numpy 数组
            chunk_ms: 每个块的时长（毫秒），默认 500ms
            on_progress: 可选回调，签名为 on_progress(chunk_index, intermediate_result)

        Returns:
            {"language": "zh", "text": "完整转录文本", "chunks_sent": N,
             "intermediate_results": [{"text": "..."}, ...]}
        """
        sr = 16000
        chunk_samples = int(sr * chunk_ms / 1000)
        total_samples = len(audio_16k)

        # 确保类型正确
        if audio_16k.dtype != np.float32:
            audio_16k = audio_16k.astype(np.float32)

        # 启动会话
        start_result = await self.start_session(service_url)
        session_id = start_result["session_id"]

        intermediate_results = []
        pos = 0
        chunk_idx = 0

        try:
            while pos < total_samples:
                end = min(pos + chunk_samples, total_samples)
                chunk = audio_16k[pos:end]
                pos = end
                chunk_idx += 1

                result = await self.send_chunk(
                    service_url, session_id, chunk,
                )
                intermediate_results.append(result)

                if on_progress:
                    on_progress(chunk_idx, result)

            # 收尾
            final = await self.finish_session(service_url, session_id)

        except Exception:
            # 异常时尝试清理会话
            try:
                await self.finish_session(service_url, session_id)
            except Exception:
                pass
            raise

        return {
            "language": final.get("language", ""),
            "text": final.get("text", ""),
            "chunks_sent": chunk_idx,
            "intermediate_results": intermediate_results,
        }

    async def transcribe_file_streaming(
        self,
        service_url: str,
        audio_path: str,
        chunk_ms: int = 500,
        on_progress=None,
    ) -> dict:
        """从音频文件读取并流式转录。

        Args:
            service_url: 服务 URL
            audio_path: 音频文件路径（wav/mp3/flac）
            chunk_ms: 块时长（毫秒）
            on_progress: 进度回调

        Returns:
            同 transcribe_streaming()
        """
        import soundfile as sf

        wav, sr = sf.read(audio_path, dtype="float32", always_2d=False)
        if wav.ndim > 1:
            wav = wav.mean(axis=1)
        wav = wav.astype(np.float32)

        # 重采样到 16kHz
        if sr != 16000:
            import scipy.signal
            num_samples = int(len(wav) * 16000 / sr)
            wav = scipy.signal.resample(wav, num_samples)
            wav = wav.astype(np.float32)

        return await self.transcribe_streaming(
            service_url, wav, chunk_ms=chunk_ms, on_progress=on_progress,
        )


from adapters import register_adapter
register_adapter("qwen3-asr-streaming", Qwen3StreamingAdapter)
