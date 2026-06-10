#!/usr/bin/env python3
# services/qwen3_asr_service.py — Qwen3ASR HTTP API 服务包装器
"""
将 Qwen3ASR 模型封装为 HTTP API 服务，供 WebUI 适配器调用。

启动方式:
    python services/qwen3_asr_service.py --port 8100 --checkpoint /path/to/model

API 端点:
    POST /v1/transcribe         提交音频转录任务
    GET  /v1/status/<task_id>   查询任务状态
    GET  /health                健康检查
"""

import argparse
import asyncio
import base64
import io
import json
import os
import sys
import time
import uuid
import logging
from pathlib import Path
from typing import Optional
from concurrent.futures import ThreadPoolExecutor

import aiohttp
from aiohttp import web

logger = logging.getLogger("qwen3_asr_service")

# ── 全局模型引用 ──
_model = None
_task_store: dict[str, dict] = {}
_executor = ThreadPoolExecutor(max_workers=4)


def load_model(checkpoint: str, device: str = "cuda:0"):
    """加载 Qwen3ASR 模型。"""
    global _model
    try:
        from qwen_asr import Qwen3ASRModel
        logger.info("正在加载 Qwen3ASR 模型: %s on %s", checkpoint, device)
        _model = Qwen3ASRModel.from_pretrained(checkpoint, device=device)
        logger.info("Qwen3ASR 模型加载完成")
        return True
    except ImportError:
        logger.warning(
            "qwen_asr 包未安装。服务将以模拟模式运行。"
            "安装: pip install qwen-asr"
        )
        _model = None
        return False
    except Exception as e:
        logger.error("模型加载失败: %s", e)
        _model = None
        return False


def _transcribe_sync(
    audio_data: bytes,
    language: Optional[str],
    return_timestamps: bool,
    return_srt: bool,
    task_id: str,
):
    """同步执行转录（在 executor 中运行）。"""
    global _model, _task_store

    if _model is None:
        _task_store[task_id] = {
            "status": "failed",
            "result": None,
            "error": "模型未加载。请确认 qwen_asr 包已安装且模型路径正确。",
        }
        return

    try:
        import numpy as np
        import soundfile as sf

        # 从 bytes 读取音频
        audio_io = io.BytesIO(audio_data)
        wav, sr = sf.read(audio_io)

        if wav.ndim > 1:
            wav = wav.mean(axis=1)

        # 重采样到 16kHz（Qwen3ASR 要求）
        if sr != 16000:
            import scipy.signal
            num_samples = int(len(wav) * 16000 / sr)
            wav = scipy.signal.resample(wav, num_samples)
            sr = 16000

        wav = wav.astype(np.float32)

        # 调用模型
        _task_store[task_id]["status"] = "running"

        result = _model.transcribe(
            wav,
            language=language,
            return_timestamps=return_timestamps,
        )

        output = {
            "text": result.get("text", ""),
            "segments": result.get("segments", []),
        }

        if return_srt and result.get("segments"):
            output["srt"] = _segments_to_srt(result["segments"])

        _task_store[task_id] = {
            "status": "completed",
            "result": output,
            "error": None,
        }

    except Exception as e:
        logger.exception("转录任务 %s 失败", task_id)
        _task_store[task_id] = {
            "status": "failed",
            "result": None,
            "error": str(e),
        }


def _segments_to_srt(segments: list[dict]) -> str:
    """将时间戳片段转换为 SRT 字幕格式。"""
    lines = []
    for i, seg in enumerate(segments, 1):
        start = seg.get("start", 0)
        end = seg.get("end", 0)
        text = seg.get("text", "").strip()

        start_str = _format_srt_time(start)
        end_str = _format_srt_time(end)

        lines.append(f"{i}")
        lines.append(f"{start_str} --> {end_str}")
        lines.append(text)
        lines.append("")
    return "\n".join(lines)


def _format_srt_time(seconds: float) -> str:
    """格式化 SRT 时间戳。"""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int((seconds % 1) * 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


# ── HTTP 处理器 ──


async def handle_health(request: web.Request) -> web.Response:
    """健康检查端点。"""
    return web.json_response({
        "status": "ok" if _model is not None else "degraded",
        "service": "qwen3-asr",
        "model_loaded": _model is not None,
    })


async def handle_transcribe(request: web.Request) -> web.Response:
    """处理转录请求。"""
    try:
        data = await request.json()

        # 获取音频数据
        audio_data = None
        if "audio" in data:
            # base64 编码的音频
            audio_str = data["audio"]
            if "," in audio_str:
                audio_str = audio_str.split(",", 1)[1]
            audio_data = base64.b64decode(audio_str)
        elif "audio_path" in data:
            # 从文件路径读取
            with open(data["audio_path"], "rb") as f:
                audio_data = f.read()
        else:
            return web.json_response(
                {"error": "需要提供 audio（base64）或 audio_path 字段"},
                status=400,
            )

        task_id = str(uuid.uuid4())
        language = data.get("language", "Auto")
        language = None if language == "Auto" else language
        return_timestamps = data.get("return_timestamps", True)
        return_srt = data.get("return_srt", False)

        # 初始化任务状态
        _task_store[task_id] = {"status": "queued", "result": None, "error": None}

        # 在线程池中执行转录
        loop = asyncio.get_event_loop()
        loop.run_in_executor(
            _executor,
            _transcribe_sync,
            audio_data,
            language,
            return_timestamps,
            return_srt,
            task_id,
        )

        return web.json_response({"task_id": task_id, "status": "queued"})

    except json.JSONDecodeError:
        return web.json_response({"error": "无效的 JSON 请求体"}, status=400)
    except Exception as e:
        logger.exception("转录请求处理失败")
        return web.json_response({"error": str(e)}, status=500)


async def handle_status(request: web.Request) -> web.Response:
    """查询任务状态。"""
    task_id = request.match_info.get("task_id", "")
    task = _task_store.get(task_id)

    if task is None:
        return web.json_response({"error": "任务未找到"}, status=404)

    return web.json_response(task)


# ── 应用启动 ──


def create_app() -> web.Application:
    app = web.Application()
    app.router.add_get("/health", handle_health)
    app.router.add_post("/v1/transcribe", handle_transcribe)
    app.router.add_get("/v1/status/{task_id}", handle_status)
    return app


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="qwen3-asr-service",
        description="Qwen3ASR HTTP API 服务包装器",
    )
    parser.add_argument("--port", type=int, default=8100, help="服务端口 (默认: 8100)")
    parser.add_argument("--host", default="0.0.0.0", help="绑定地址 (默认: 0.0.0.0)")
    parser.add_argument("--checkpoint", default="", help="Qwen3ASR 模型路径")
    parser.add_argument("--device", default="cuda:0", help="推理设备 (默认: cuda:0)")
    parser.add_argument("--log-level", default="INFO",
                        choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level.upper()),
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    if args.checkpoint:
        load_model(args.checkpoint, args.device)
    else:
        logger.warning("未指定 --checkpoint，模型不会加载。服务将以降级模式运行。")

    app = create_app()

    logger.info("Qwen3ASR 服务启动于 http://%s:%s", args.host, args.port)
    web.run_app(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
