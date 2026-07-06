#!/usr/bin/env python3
# services/qwen3_tts_service.py — Qwen3 TTS HTTP API 服务包装器
"""
将 Qwen3 TTS 模型封装为 HTTP API 服务，供 WebUI 适配器调用。

支持三种模式：
- voice-design: 通过自然语言描述创建音色
- voice-clone: 基于参考音频复刻声音
- custom-voice: 使用预设说话人 + 情感控制

启动方式:
    python services/qwen3_tts_service.py --port 17910 --models-dir ./models

API 端点:
    POST /v1/tts                  提交语音合成任务
    GET  /v1/status/<task_id>     查询任务状态与结果
    GET  /health                  健康检查
"""

import argparse
import asyncio
import base64
import gc
import io
import json
import logging
import os
import uuid
import wave
from concurrent.futures import ThreadPoolExecutor

from aiohttp import web

logger = logging.getLogger("qwen3_tts_service")

_task_store: dict[str, dict] = {}
_executor = ThreadPoolExecutor(max_workers=1)

# 当前加载的模型
_current_model = None
_current_mode = None
_models_dir = ""

MODEL_DIRS = {
    "voice-design": "Qwen3-TTS-12Hz-1.7B-VoiceDesign",
    "voice-clone": "Qwen3-TTS-12Hz-1.7B-Base",
    "custom-voice": "Qwen3-TTS-12Hz-1.7B-CustomVoice",
}


def _unload_model():
    global _current_model, _current_mode
    if _current_model is not None:
        logger.info("释放模型: %s", _current_mode)
        del _current_model
        _current_model = None
        _current_mode = None
        gc.collect()
        try:
            import torch
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except ImportError:
            pass


def _load_model(mode: str):
    global _current_model, _current_mode, _models_dir

    if _current_mode == mode:
        return _current_model

    _unload_model()

    model_dir = MODEL_DIRS.get(mode)
    if not model_dir:
        logger.error("未知模式: %s", mode)
        return None

    model_path = os.path.join(_models_dir, model_dir)
    if not os.path.exists(model_path):
        logger.error("模型路径不存在: %s", model_path)
        return None

    try:
        from qwen_tts import Qwen3TTSModel
        import torch

        attn_mode = "sdpa"
        compute_dtype = torch.float16

        if torch.cuda.is_available() and torch.cuda.is_bf16_supported():
            compute_dtype = torch.bfloat16

        try:
            import flash_attn
            attn_mode = "flash_attention_2"
            logger.info("检测到 Flash-Attention，已开启高性能模式")
        except ImportError:
            pass

        logger.info("正在加载模型: %s (%s)", mode, model_path)
        _current_model = Qwen3TTSModel.from_pretrained(
            model_path,
            device_map="cuda",
            attn_implementation=attn_mode,
            dtype=compute_dtype,
            local_files_only=True,
        )
        _current_mode = mode
        logger.info("模型加载完成: %s", mode)
        return _current_model

    except ImportError as e:
        logger.error("qwen_tts 包未安装: %s", e)
        return None
    except Exception as e:
        logger.error("模型加载失败: %s", e)
        return None


def _wav_to_base64(wavs, sr: int) -> str:
    import numpy as np
    audio = wavs[0]
    if isinstance(audio, list):
        audio = audio[0]

    audio_np = np.array(audio)
    if audio_np.ndim > 1:
        audio_np = audio_np.mean(axis=1)

    audio_int16 = (audio_np * 32767).astype(np.int16)

    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        wf.writeframes(audio_int16.tobytes())

    return base64.b64encode(buf.getvalue()).decode("utf-8")


def _tts_sync(
    task_id: str,
    text: str,
    mode: str,
    language: str,
    instruct: str,
    speaker: str,
    ref_audio_b64: str,
    ref_text: str,
) -> None:
    try:
        model = _load_model(mode)
        if model is None:
            _task_store[task_id] = {
                "status": "failed",
                "result": None,
                "error": f"无法加载 {mode} 模型。请确认模型文件存在。",
            }
            return

        _task_store[task_id]["status"] = "running"

        if mode == "voice-design":
            wavs, sr = model.generate_voice_design(
                text=text, language=language, instruct=instruct,
            )
        elif mode == "voice-clone":
            if not ref_audio_b64:
                _task_store[task_id] = {
                    "status": "failed",
                    "result": None,
                    "error": "语音克隆模式需要提供参考音频",
                }
                return

            import tempfile
            ref_audio_bytes = base64.b64decode(ref_audio_b64)
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
                tmp.write(ref_audio_bytes)
                ref_audio_path = tmp.name

            try:
                use_x_vector = not ref_text or ref_text.strip() == ""
                wavs, sr = model.generate_voice_clone(
                    text=text,
                    language=language,
                    ref_audio=ref_audio_path,
                    ref_text=ref_text,
                    x_vector_only_mode=use_x_vector,
                )
            finally:
                os.unlink(ref_audio_path)
        elif mode == "custom-voice":
            wavs, sr = model.generate_custom_voice(
                text=text, language=language, speaker=speaker, instruct=instruct,
            )
        else:
            _task_store[task_id] = {
                "status": "failed",
                "result": None,
                "error": f"未知模式: {mode}",
            }
            return

        audio_b64 = _wav_to_base64(wavs, sr)

        _task_store[task_id] = {
            "status": "completed",
            "result": {
                "audio_base64": audio_b64,
                "sample_rate": sr,
                "mode": mode,
            },
            "error": None,
        }

    except Exception as e:
        logger.exception("TTS 任务 %s 失败", task_id)
        _task_store[task_id] = {
            "status": "failed",
            "result": None,
            "error": str(e),
        }


async def handle_health(request: web.Request) -> web.Response:
    return web.json_response({
        "status": "ok",
        "service": "qwen3-tts",
        "current_model": _current_mode,
    })


async def handle_tts(request: web.Request) -> web.Response:
    try:
        payload = await request.json()
    except json.JSONDecodeError:
        return web.json_response({"error": "请求体必须是 JSON"}, status=400)

    text = payload.get("text")
    if not text:
        return web.json_response({"error": "text 为必填字段"}, status=400)

    mode = payload.get("mode", "voice-design")
    if mode not in MODEL_DIRS:
        return web.json_response(
            {"error": f"mode 必须是 {list(MODEL_DIRS.keys())} 之一"},
            status=400,
        )

    task_id = str(uuid.uuid4())
    _task_store[task_id] = {"status": "queued", "result": None, "error": None}

    loop = asyncio.get_running_loop()
    loop.run_in_executor(
        _executor,
        _tts_sync,
        task_id,
        text,
        mode,
        payload.get("language", "Auto"),
        payload.get("instruct", ""),
        payload.get("speaker", "Vivian"),
        payload.get("ref_audio", ""),
        payload.get("ref_text", ""),
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
    app.router.add_post("/v1/tts", handle_tts)
    app.router.add_get("/v1/status/{task_id}", handle_status)
    return app


def main():
    parser = argparse.ArgumentParser(description="Qwen3 TTS HTTP API 服务")
    parser.add_argument("--port", type=int, default=17910, help="监听端口")
    parser.add_argument("--host", default="0.0.0.0", help="绑定地址")
    parser.add_argument(
        "--models-dir",
        default="./models",
        help="模型目录（包含 Qwen3-TTS-12Hz-1.7B-* 子目录）",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
    )
    args = parser.parse_args()

    global _models_dir
    _models_dir = os.path.abspath(args.models_dir)

    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    logger.info(
        "Qwen3 TTS 服务启动于 http://%s:%s (模型目录: %s)",
        args.host, args.port, _models_dir,
    )
    web.run_app(create_app(), host=args.host, port=args.port)


if __name__ == "__main__":
    main()
