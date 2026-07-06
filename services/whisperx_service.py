#!/usr/bin/env python3
# services/whisperx_service.py — WhisperX HTTP API 服务包装器
"""
将 WhisperX 模型封装为 HTTP API 服务，供 WebUI 适配器调用。

支持：
- 音频转录（wav/mp3/flac/m4a）
- 语种检测与强制指定
- 说话人识别（diarization）
- 词级时间戳对齐

启动方式:
    python services/whisperx_service.py --port 8200 --model large-v3

API 端点:
    POST /v1/transcribe           提交转录任务
    GET  /v1/status/<task_id>     查询任务状态与结果
    GET  /health                  健康检查
"""

import argparse
import asyncio
import base64
import io
import json
import logging
import os
import uuid
from concurrent.futures import ThreadPoolExecutor

from aiohttp import web

logger = logging.getLogger("whisperx_service")

_task_store: dict[str, dict] = {}
_executor = ThreadPoolExecutor(max_workers=2)

_model = None
_align_model = None
_diarize_model = None
_model_name = "large-v3"


def load_models(model_name: str, device: str = "auto", use_auth_token: str = ""):
    global _model, _align_model, _diarize_model

    try:
        import whisperx
        logger.info("正在加载 WhisperX 模型: %s", model_name)
        _model = whisperx.load_model(model_name, device=device)
        logger.info("WhisperX 模型加载完成")

        logger.info("正在加载对齐模型...")
        _, _align_model = whisperx.load_align_model(
            language_code="en", device=device,
        )
        logger.info("对齐模型加载完成")

        if use_auth_token:
            logger.info("正在加载说话人识别模型...")
            _diarize_model = whisperx.DiarizationPipeline(
                use_auth_token=use_auth_token, device=device,
            )
            logger.info("说话人识别模型加载完成")

        return True
    except ImportError:
        logger.warning("whisperx 包未安装。请执行: pip install whisperx")
        return False
    except Exception as e:
        logger.error("模型加载失败: %s", e)
        return False


def _decode_audio(audio_field: str) -> bytes:
    if os.path.exists(audio_field):
        with open(audio_field, "rb") as f:
            return f.read()
    if "," in audio_field:
        audio_field = audio_field.split(",", 1)[1]
    return base64.b64decode(audio_field)


def _format_srt(segments) -> str:
    lines = []
    for i, seg in enumerate(segments, 1):
        start = seg.get("start", 0)
        end = seg.get("end", 0)
        text = seg.get("text", "").strip()
        speaker = seg.get("speaker", "")
        h1, m1, s1 = int(start // 3600), int((start % 3600) // 60), start % 60
        h2, m2, s2 = int(end // 3600), int((end % 3600) // 60), end % 60
        lines.append(f"{i}")
        lines.append(f"{h1:02d}:{m1:02d}:{s1:06.3f} --> {h2:02d}:{m2:02d}:{s2:06.3f}".replace(".", ","))
        speaker_prefix = f"[{speaker}] " if speaker else ""
        lines.append(f"{speaker_prefix}{text}")
        lines.append("")
    return "\n".join(lines)


def _transcribe_sync(
    task_id: str,
    audio_data: bytes,
    language: str,
    model_size: str,
    enable_diarization: bool,
    return_timestamps: bool,
    return_srt: bool,
) -> None:
    global _model, _align_model, _diarize_model

    if _model is None:
        _task_store[task_id] = {
            "status": "failed",
            "result": None,
            "error": "模型未加载。请确认 whisperx 已安装。",
        }
        return

    try:
        import whisperx
        import numpy as np

        _task_store[task_id]["status"] = "running"

        audio_io = io.BytesIO(audio_data)

        result = _model.transcribe(
            str(audio_io),
            batch_size=16,
            language=None if language == "Auto" else language,
        )

        if return_timestamps and _align_model is not None:
            result = whisperx.align(
                result["segments"],
                _align_model,
                str(audio_io),
                device="cuda" if _model.device.type == "cuda" else "cpu",
                return_char_alignments=False,
            )

        if enable_diarization and _diarize_model is not None:
            diarize_segments = _diarize_model(str(audio_io))
            result = whisperx.diarize_segments(
                result, diarize_segments,
            )

        segments = []
        for seg in result.get("segments", []):
            segment = {
                "start": seg.get("start", 0),
                "end": seg.get("end", 0),
                "text": seg.get("text", "").strip(),
            }
            if "speaker" in seg:
                segment["speaker"] = seg["speaker"]
            segments.append(segment)

        output = {
            "text": " ".join(s["text"] for s in segments),
            "segments": segments,
            "language": result.get("language", language),
        }

        if return_srt and segments:
            output["srt"] = _format_srt(segments)

        _task_store[task_id] = {
            "status": "completed",
            "result": output,
            "error": None,
        }

    except Exception as e:
        logger.exception("WhisperX 任务 %s 失败", task_id)
        _task_store[task_id] = {
            "status": "failed",
            "result": None,
            "error": str(e),
        }


async def handle_health(request: web.Request) -> web.Response:
    return web.json_response({
        "status": "ok" if _model is not None else "degraded",
        "service": "whisperx",
        "model_loaded": _model is not None,
        "model_name": _model_name,
    })


async def handle_transcribe(request: web.Request) -> web.Response:
    try:
        payload = await request.json()
    except json.JSONDecodeError:
        return web.json_response({"error": "请求体必须是 JSON"}, status=400)

    audio_field = payload.get("audio") or payload.get("audio_path")
    if not audio_field:
        return web.json_response(
            {"error": "需要提供 audio 或 audio_path 字段"}, status=400,
        )

    try:
        audio_data = _decode_audio(audio_field)
    except Exception:
        return web.json_response({"error": "无效的音频数据"}, status=400)

    task_id = str(uuid.uuid4())
    _task_store[task_id] = {"status": "queued", "result": None, "error": None}

    loop = asyncio.get_running_loop()
    loop.run_in_executor(
        _executor,
        _transcribe_sync,
        task_id,
        audio_data,
        payload.get("language", "Auto"),
        payload.get("model", _model_name),
        payload.get("enable_diarization", False),
        payload.get("return_timestamps", True),
        payload.get("return_srt", False),
    )

    return web.json_response({"task_id": task_id, "status": "queued"}, status=202)


async def handle_status(request: web.Request) -> web.Response:
    task_id = request.match_info["task_id"]
    task = _task_store.get(task_id)
    if not task:
        return web.json_response(
            {"status": "failed", "result": None, "error": "任务不存在"},
            status=404,
        )
    return web.json_response(task)


def create_app() -> web.Application:
    app = web.Application()
    app.router.add_get("/health", handle_health)
    app.router.add_post("/v1/transcribe", handle_transcribe)
    app.router.add_get("/v1/status/{task_id}", handle_status)
    return app


def main():
    parser = argparse.ArgumentParser(description="WhisperX HTTP API 服务")
    parser.add_argument("--port", type=int, default=8200, help="监听端口")
    parser.add_argument("--host", default="0.0.0.0", help="绑定地址")
    parser.add_argument("--model", default="large-v3", help="Whisper 模型大小")
    parser.add_argument("--device", default="auto", choices=["auto", "cuda", "cpu"])
    parser.add_argument("--hf-token", default="", help="HuggingFace token（用于说话人识别）")
    parser.add_argument(
        "--log-level", default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
    )
    args = parser.parse_args()

    global _model_name
    _model_name = args.model

    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    device = args.device
    if device == "auto":
        try:
            import torch
            device = "cuda" if torch.cuda.is_available() else "cpu"
        except ImportError:
            device = "cpu"

    load_models(args.model, device, args.hf_token)

    logger.info("WhisperX 服务启动于 http://%s:%s", args.host, args.port)
    web.run_app(create_app(), host=args.host, port=args.port)


if __name__ == "__main__":
    main()
