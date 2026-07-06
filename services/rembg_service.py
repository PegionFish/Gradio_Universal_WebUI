#!/usr/bin/env python3
# services/rembg_service.py — RemBg HTTP API 服务包装器
"""
将 rembg 背景移除模型封装为 HTTP API 服务，供 WebUI 适配器调用。

启动方式:
    python services/rembg_service.py --port 17920 --models-dir ./models

API 端点:
    POST /v1/remove-bg             提交背景移除任务
    GET  /v1/status/<task_id>      查询任务状态与结果
    GET  /health                   健康检查
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
from PIL import Image

logger = logging.getLogger("rembg_service")

_task_store: dict[str, dict] = {}
_executor = ThreadPoolExecutor(max_workers=2)

# 模型到 ONNX 文件的映射
MODEL_FILES = {
    "isnet-general-use": "isnet-general-use.onnx",
    "u2net": "u2net.onnx",
    "u2netp": "u2netp.onnx",
    "u2net_human_seg": "u2net_human_seg.onnx",
    "u2net_cloth_seg": "u2net_cloth_seg.onnx",
    "isnet-anime": "isnet-anime.onnx",
}

# 缓存已加载的 session，避免重复加载
_sessions: dict = {}
_models_dir = ""


def _decode_image(b64_str: str) -> Image.Image:
    if "," in b64_str:
        b64_str = b64_str.split(",", 1)[1]
    return Image.open(io.BytesIO(base64.b64decode(b64_str)))


def _encode_image(img: Image.Image) -> str:
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode("utf-8")


def _get_session(model_name: str):
    global _sessions, _models_dir
    if model_name in _sessions:
        return _sessions[model_name]

    try:
        from rembg import new_session
        session = new_session(model_name, models_dir=_models_dir)
        _sessions[model_name] = session
        logger.info("RemBg 模型 %s 加载完成", model_name)
        return session
    except ImportError:
        logger.error("rembg 包未安装，请执行: pip install rembg")
        return None
    except Exception as e:
        logger.error("RemBg 模型 %s 加载失败: %s", model_name, e)
        return None


def _remove_bg_sync(task_id: str, image_data: bytes, model_name: str) -> None:
    try:
        img = Image.open(io.BytesIO(image_data)).convert("RGBA")

        session = _get_session(model_name)
        if session is None:
            _task_store[task_id] = {
                "status": "failed",
                "result": None,
                "error": f"模型 {model_name} 未加载。请确认 rembg 已安装。",
            }
            return

        from rembg import remove
        result_img = remove(img, session=session)

        result_b64 = _encode_image(result_img)

        _task_store[task_id] = {
            "status": "completed",
            "result": {
                "image_base64": result_b64,
                "model": model_name,
            },
            "error": None,
        }
    except Exception as e:
        logger.exception("RemBg 任务 %s 执行失败", task_id)
        _task_store[task_id] = {
            "status": "failed",
            "result": None,
            "error": str(e),
        }


async def handle_health(request: web.Request) -> web.Response:
    return web.json_response({
        "status": "ok",
        "service": "rembg",
        "models_dir": _models_dir,
    })


async def handle_remove_bg(request: web.Request) -> web.Response:
    try:
        payload = await request.json()
    except json.JSONDecodeError:
        return web.json_response({"error": "请求体必须是 JSON"}, status=400)

    image_b64 = payload.get("image")
    if not image_b64:
        return web.json_response({"error": "image 为必填字段"}, status=400)

    model_name = payload.get("model", "isnet-general-use")
    if model_name not in MODEL_FILES:
        return web.json_response(
            {"error": f"不支持的模型: {model_name}"},
            status=400,
        )

    try:
        image_data = base64.b64decode(image_b64)
    except Exception:
        return web.json_response({"error": "无效的 base64 图片数据"}, status=400)

    task_id = str(uuid.uuid4())
    _task_store[task_id] = {"status": "queued", "result": None, "error": None}

    loop = asyncio.get_running_loop()
    loop.run_in_executor(
        _executor,
        _remove_bg_sync,
        task_id,
        image_data,
        model_name,
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
    app.router.add_post("/v1/remove-bg", handle_remove_bg)
    app.router.add_get("/v1/status/{task_id}", handle_status)
    return app


def main():
    parser = argparse.ArgumentParser(description="RemBg HTTP API 服务")
    parser.add_argument("--port", type=int, default=17920, help="监听端口")
    parser.add_argument("--host", default="0.0.0.0", help="绑定地址")
    parser.add_argument(
        "--models-dir",
        default="./models",
        help="ONNX 模型目录（包含 u2net.onnx 等文件）",
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
        "RemBg 服务启动于 http://%s:%s (模型目录: %s)",
        args.host, args.port, _models_dir,
    )
    web.run_app(create_app(), host=args.host, port=args.port)


if __name__ == "__main__":
    main()
