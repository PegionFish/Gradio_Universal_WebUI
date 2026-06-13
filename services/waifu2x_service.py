#!/usr/bin/env python3
# services/waifu2x_service.py — waifu2x HTTP API 服务包装器（mock 模式）
"""
将 waifu2x 模型封装为 HTTP API 服务，供 WebUI 适配器调用。

启动方式:
    python services/waifu2x_service.py --port 17900

API 端点:
    POST /v1/upscale              提交图片放大任务
    GET  /v1/status/<task_id>     查询任务状态与结果
    GET  /health                  健康检查

当前为 mock 模式：使用 Pillow 简单 resize 模拟放大效果，
不依赖真实 waifu2x 引擎。后续替换 _upscale_sync 内部实现即可接入真实推理。
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
from typing import Optional

from aiohttp import web
from PIL import Image

logger = logging.getLogger("waifu2x_service")

# 全局状态
_task_store: dict[str, dict] = {}
_executor = ThreadPoolExecutor(max_workers=2)

# 支持的参数常量
VALID_SCALES = {1, 2, 4}
VALID_DENOISE_LEVELS = {-1, 0, 1, 2, 3}
VALID_MODEL_TYPES = {
    "cunet",
    "upconv_7_anime_style_art_rgb",
    "upconv_7_photo",
}


def _decode_image(image_field: str) -> Image.Image:
    """将 base64 字符串或本地文件路径解码为 PIL Image。"""
    if os.path.exists(image_field):
        return Image.open(image_field).convert("RGB")
    data = base64.b64decode(image_field)
    return Image.open(io.BytesIO(data)).convert("RGB")


def _encode_image(img: Image.Image, fmt: str = "PNG") -> str:
    """将 PIL Image 编码为 base64 字符串。"""
    buf = io.BytesIO()
    img.save(buf, format=fmt)
    return base64.b64encode(buf.getvalue()).decode("utf-8")


def _upscale_sync(
    task_id: str,
    image_field: str,
    scale: int,
    denoise_level: int,
    model_type: str,
    tile_size: int,
) -> None:
    """同步执行 mock 放大（在 executor 中运行）。"""
    try:
        img = _decode_image(image_field)
        new_size = (img.width * scale, img.height * scale)
        # mock 模式使用双线性插值；真实引擎替换此处即可
        upscaled = img.resize(new_size, Image.BILINEAR)
        result_b64 = _encode_image(upscaled)

        _task_store[task_id] = {
            "status": "completed",
            "result": {
                "image_base64": result_b64,
                "scale": scale,
                "denoise_level": denoise_level,
                "model_type": model_type,
                "tile_size": tile_size,
            },
            "error": None,
        }
    except Exception as e:
        logger.exception("waifu2x 任务 %s 执行失败", task_id)
        _task_store[task_id] = {
            "status": "failed",
            "result": None,
            "error": str(e),
        }


async def health(request: web.Request) -> web.Response:
    """健康检查端点。"""
    return web.json_response({"status": "ok"})


async def upscale(request: web.Request) -> web.Response:
    """提交放大任务端点。"""
    try:
        payload = await request.json()
    except json.JSONDecodeError:
        return web.json_response({"error": "请求体必须是 JSON"}, status=400)

    image_field = payload.get("image")
    if not image_field or not isinstance(image_field, str):
        return web.json_response({"error": "image 为必填字段"}, status=400)

    scale = payload.get("scale", 2)
    if scale not in VALID_SCALES:
        return web.json_response(
            {"error": f"scale 必须是 {sorted(VALID_SCALES)} 之一"}, status=400
        )

    denoise_level = payload.get("denoise_level", 0)
    if denoise_level not in VALID_DENOISE_LEVELS:
        return web.json_response(
            {"error": f"denoise_level 必须是 {sorted(VALID_DENOISE_LEVELS)} 之一"},
            status=400,
        )

    model_type = payload.get("model_type", "cunet")
    if model_type not in VALID_MODEL_TYPES:
        return web.json_response(
            {"error": f"model_type 必须是 {sorted(VALID_MODEL_TYPES)} 之一"},
            status=400,
        )

    tile_size = payload.get("tile_size", 256)
    if not isinstance(tile_size, int) or tile_size < 64 or tile_size > 2048:
        return web.json_response(
            {"error": "tile_size 必须在 64-2048 之间"}, status=400
        )

    task_id = str(uuid.uuid4())
    _task_store[task_id] = {"status": "running", "result": None, "error": None}

    loop = asyncio.get_running_loop()
    loop.run_in_executor(
        _executor,
        _upscale_sync,
        task_id,
        image_field,
        scale,
        denoise_level,
        model_type,
        tile_size,
    )

    return web.json_response({"task_id": task_id, "status": "queued"}, status=202)


async def status(request: web.Request) -> web.Response:
    """查询任务状态端点。"""
    task_id = request.match_info["task_id"]
    task = _task_store.get(task_id)
    if not task:
        return web.json_response(
            {"status": "failed", "result": None, "error": "任务不存在"},
            status=404,
        )
    return web.json_response(task)


def create_app() -> web.Application:
    """创建 aiohttp 应用（便于测试）。"""
    app = web.Application()
    app.router.add_get("/health", health)
    app.router.add_post("/v1/upscale", upscale)
    app.router.add_get("/v1/status/{task_id}", status)
    return app


def main():
    """CLI 入口。"""
    parser = argparse.ArgumentParser(description="waifu2x HTTP API 服务")
    parser.add_argument("--port", type=int, default=17900, help="监听端口")
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="日志级别",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    logger.info("waifu2x 服务启动于 http://localhost:%s", args.port)
    web.run_app(create_app(), host="0.0.0.0", port=args.port)


if __name__ == "__main__":
    main()
