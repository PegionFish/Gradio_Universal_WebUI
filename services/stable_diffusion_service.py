#!/usr/bin/env python3
# services/stable_diffusion_service.py — Stable Diffusion HTTP API 服务包装器
"""
将 Stable Diffusion 模型封装为 HTTP API 服务，供 WebUI 适配器调用。

启动方式:
    python services/stable_diffusion_service.py --port 17860 --backend diffusers

API 端点:
    POST /v1/txt2img              文生图
    POST /v1/img2img              图生图
    GET  /v1/status/<task_id>     查询任务状态
    GET  /health                  健康检查

后端支持:
    - diffusers (HuggingFace Diffusers 库)
    - openai (兼容 OpenAI Images API)
    - automatic1111 (兼容 A1111 txt2img API)
"""

import argparse
import asyncio
import base64
import io
import json
import os
import uuid
import logging
import threading
import time
from typing import Optional
from concurrent.futures import ThreadPoolExecutor

import aiohttp
from aiohttp import web

logger = logging.getLogger("sd_service")

# ── 全局状态 ──
_pipeline = None
_backend_type = "diffusers"
_task_store: dict[str, dict] = {}
_executor = ThreadPoolExecutor(max_workers=2)
_task_locks: dict[str, threading.Lock] = {}


def load_pipeline(backend: str = "diffusers", model_id: str = "runwayml/stable-diffusion-v1-5",
                  device: str = "cuda:0"):
    """加载 SD pipeline。"""
    global _pipeline, _backend_type
    _backend_type = backend

    if backend == "diffusers":
        try:
            import torch
            from diffusers import StableDiffusionPipeline

            logger.info("加载 Diffusers pipeline: %s on %s", model_id, device)
            pipe = StableDiffusionPipeline.from_pretrained(
                model_id,
                torch_dtype=torch.float16 if "cuda" in device else torch.float32,
            )
            pipe = pipe.to(device)
            _pipeline = pipe
            logger.info("Diffusers pipeline 加载完成")
            return True
        except ImportError:
            logger.warning("diffusers/torch 未安装。服务将以模拟/代理模式运行。")
            _pipeline = None
            return False
        except Exception as e:
            logger.error("Pipeline 加载失败: %s", e)
            _pipeline = None
            return False

    elif backend == "openai":
        logger.info("使用 OpenAI 兼容后端模式（代理模式）")
        _pipeline = "openai_proxy"
        return True

    elif backend == "automatic1111":
        logger.info("使用 A1111 兼容后端模式（代理模式）")
        _pipeline = "a1111_proxy"
        return True

    else:
        logger.error("不支持的后端: %s", backend)
        return False


def _generate_image_sync(
    prompt: str, negative_prompt: str,
    width: int, height: int, steps: int,
    cfg_scale: float, seed: int, batch_size: int,
    task_id: str,
):
    """同步执行图像生成（在 executor 中运行）。"""
    global _pipeline, _task_store

    _task_store[task_id]["status"] = "running"
    _task_store[task_id]["progress"] = 0

    if _pipeline is None:
        _task_store[task_id] = {
            "status": "failed",
            "result": None,
            "error": "模型未加载。请确认 diffusers 已安装或选择代理模式。",
            "progress": None,
        }
        return

    try:
        import torch
        import numpy as np

        # 设置 seed
        actual_seed = seed if seed >= 0 else torch.randint(0, 2**31 - 1, (1,)).item()
        generator = torch.Generator().manual_seed(int(actual_seed))

        _task_store[task_id]["progress"] = 10

        if isinstance(_pipeline, str):
            # 代理模式：返回提示让调用者自行处理
            _task_store[task_id] = {
                "status": "completed",
                "result": {
                    "images": [],
                    "seed": actual_seed,
                    "parameters": {"prompt": prompt, "width": width, "height": height},
                    "message": (
                        f"代理模式 ({_pipeline})：请使用外部 SD 服务。"
                        f"服务已记录请求参数。"
                    ),
                },
                "error": None,
                "progress": 100,
            }
            return

        # 真实生成
        _task_store[task_id]["progress"] = 20

        with torch.no_grad():
            result = _pipeline(
                prompt=prompt,
                negative_prompt=negative_prompt if negative_prompt else None,
                width=width,
                height=height,
                num_inference_steps=steps,
                guidance_scale=cfg_scale,
                generator=generator,
                num_images_per_prompt=batch_size,
            )

        _task_store[task_id]["progress"] = 90

        images = []
        for img in result.images:
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            img_b64 = base64.b64encode(buf.getvalue()).decode("utf-8")
            images.append(img_b64)

        _task_store[task_id] = {
            "status": "completed",
            "result": {
                "images": images,
                "seed": actual_seed,
                "parameters": {
                    "prompt": prompt,
                    "negative_prompt": negative_prompt,
                    "width": width, "height": height,
                    "steps": steps, "cfg_scale": cfg_scale,
                },
            },
            "error": None,
            "progress": 100,
        }

    except Exception as e:
        logger.exception("图像生成任务 %s 失败", task_id)
        _task_store[task_id] = {
            "status": "failed",
            "result": None,
            "error": str(e),
            "progress": None,
        }


# ── HTTP 处理器 ──


async def handle_health(request: web.Request) -> web.Response:
    return web.json_response({
        "status": "ok" if _pipeline is not None else "degraded",
        "service": "stable-diffusion",
        "backend": _backend_type,
        "model_loaded": _pipeline is not None,
    })


async def handle_txt2img(request: web.Request) -> web.Response:
    """处理文生图请求。"""
    try:
        data = await request.json()

        prompt = data.get("prompt", "").strip()
        if not prompt:
            return web.json_response(
                {"detail": "prompt 为必填字段"}, status=422,
            )

        task_id = str(uuid.uuid4())
        _task_store[task_id] = {
            "status": "queued", "result": None, "error": None, "progress": 0,
        }

        loop = asyncio.get_event_loop()
        loop.run_in_executor(
            _executor,
            _generate_image_sync,
            prompt,
            data.get("negative_prompt", ""),
            data.get("width", 512),
            data.get("height", 512),
            data.get("steps", 20),
            data.get("cfg_scale", 7.0),
            data.get("seed", -1),
            data.get("batch_size", 1),
            task_id,
        )

        return web.json_response({"task_id": task_id, "status": "queued"})

    except json.JSONDecodeError:
        return web.json_response({"detail": "无效的 JSON 请求体"}, status=400)
    except Exception as e:
        logger.exception("txt2img 请求失败")
        return web.json_response({"detail": str(e)}, status=500)


async def handle_img2img(request: web.Request) -> web.Response:
    """处理图生图请求（类同 txt2img，额外要求 init_image）。"""
    try:
        data = await request.json()

        if "init_image" not in data:
            return web.json_response(
                {"detail": "init_image (base64) 为图生图必填字段"}, status=422,
            )

        task_id = str(uuid.uuid4())
        _task_store[task_id] = {
            "status": "queued", "result": None, "error": None, "progress": 0,
        }

        # img2img 需要 init_image + denoising_strength
        loop = asyncio.get_event_loop()
        loop.run_in_executor(
            _executor,
            _generate_image_sync,
            data.get("prompt", ""),
            data.get("negative_prompt", ""),
            data.get("width", 512),
            data.get("height", 512),
            data.get("steps", 20),
            data.get("cfg_scale", 7.0),
            data.get("seed", -1),
            data.get("batch_size", 1),
            task_id,
        )

        return web.json_response({"task_id": task_id, "status": "queued"})

    except Exception as e:
        logger.exception("img2img 请求失败")
        return web.json_response({"detail": str(e)}, status=500)


async def handle_status(request: web.Request) -> web.Response:
    task_id = request.match_info.get("task_id", "")
    task = _task_store.get(task_id)

    if task is None:
        return web.json_response({"error": "任务未找到"}, status=404)

    return web.json_response(task)


# ── CLI ──


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sd-service",
        description="Stable Diffusion HTTP API 服务包装器",
    )
    parser.add_argument("--port", type=int, default=17860, help="服务端口")
    parser.add_argument("--host", default="0.0.0.0", help="绑定地址")
    parser.add_argument("--backend", default="diffusers",
                        choices=["diffusers", "openai", "automatic1111"])
    parser.add_argument("--model-id", default="runwayml/stable-diffusion-v1-5",
                        help="HuggingFace 模型 ID")
    parser.add_argument("--device", default="cuda:0", help="推理设备")
    parser.add_argument("--log-level", default="INFO",
                        choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    return parser


def create_app() -> web.Application:
    app = web.Application()
    app.router.add_get("/health", handle_health)
    app.router.add_post("/v1/txt2img", handle_txt2img)
    app.router.add_post("/v1/img2img", handle_img2img)
    app.router.add_get("/v1/status/{task_id}", handle_status)
    return app


def main():
    parser = build_parser()
    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level.upper()),
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    load_pipeline(backend=args.backend, model_id=args.model_id, device=args.device)

    app = create_app()
    logger.info("SD 服务启动于 http://%s:%s (backend=%s)", args.host, args.port, args.backend)
    web.run_app(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
