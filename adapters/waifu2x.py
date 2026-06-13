# adapters/waifu2x.py — waifu2x 模型适配器

import asyncio
import base64
import io
import logging
from typing import Optional

import aiohttp
from PIL import Image

from adapters import register_adapter
from adapters.base import BaseModelAdapter

logger = logging.getLogger(__name__)


class Waifu2xAdapter(BaseModelAdapter):
    """waifu2x 模型适配器 — mock 阶段实现。

    通过 HTTP API 调用外部 waifu2x 服务。支持：
    - 图片超分放大（scale: 1/2/4）
    - 降噪等级（denoise_level: -1/0/1/2/3）
    - 模型类型选择（cunet / upconv_7_anime_style_art_rgb / upconv_7_photo）

    HTTP API 约定：
    - POST /v1/upscale          提交放大任务
    - GET  /v1/status/<task_id> 查询任务状态
    - GET  /health              健康检查
    """

    VALID_SCALES = {1, 2, 4}
    VALID_DENOISE_LEVELS = {-1, 0, 1, 2, 3}
    VALID_MODEL_TYPES = {
        "cunet",
        "upconv_7_anime_style_art_rgb",
        "upconv_7_photo",
    }

    def model_type(self) -> str:
        """返回适配器标识符。"""
        return "waifu2x"

    async def validate(self, payload: dict) -> list[str]:
        """校验请求负载。

        返回校验错误列表，空列表表示校验通过。
        """
        errors = []
        image = payload.get("image")
        if not image or not isinstance(image, str):
            errors.append("image 为必填字段（base64 字符串或文件路径）")

        scale = payload.get("scale", 2)
        if scale not in self.VALID_SCALES:
            errors.append(f"scale 必须是 {sorted(self.VALID_SCALES)} 之一")

        denoise_level = payload.get("denoise_level", 0)
        if denoise_level not in self.VALID_DENOISE_LEVELS:
            errors.append(
                f"denoise_level 必须是 {sorted(self.VALID_DENOISE_LEVELS)} 之一"
            )

        model_type = payload.get("model_type", "cunet")
        if model_type not in self.VALID_MODEL_TYPES:
            errors.append(
                f"model_type 必须是 {sorted(self.VALID_MODEL_TYPES)} 之一"
            )

        tile_size = payload.get("tile_size", 256)
        if not isinstance(tile_size, int) or tile_size < 64 or tile_size > 2048:
            errors.append("tile_size 必须在 64-2048 之间")

        return errors

    async def submit(
        self,
        service_url: str,
        payload: dict,
        target_gpu: Optional[list[int]] = None,
    ) -> str:
        """提交放大任务到 waifu2x 服务。

        Args:
            service_url: 服务基础 URL（如 http://localhost:17900）
            payload: 请求参数
            target_gpu: 目标 GPU 索引列表（waifu2x 固定用单 GPU）

        Returns:
            服务侧任务引用 ID

        Raises:
            ConnectionError: 服务不可达
            ValueError: 参数校验失败
        """
        url = service_url.rstrip("/") + "/v1/upscale"
        body = {
            "image": payload.get("image"),
            "scale": payload.get("scale", 2),
            "denoise_level": payload.get("denoise_level", 0),
            "model_type": payload.get("model_type", "cunet"),
            "tile_size": payload.get("tile_size", 256),
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=body) as resp:
                    text = await resp.text()
                    if resp.status == 202:
                        data = await resp.json()
                        return data["task_id"]
                    if resp.status == 400:
                        data = await resp.json()
                        raise ValueError(
                            f"参数校验失败: {data.get('error', 'unknown')}"
                        )
                    raise ConnectionError(
                        f"waifu2x 服务返回 {resp.status}: {text[:200]}"
                    )
        except aiohttp.ClientError as e:
            raise ConnectionError(f"无法连接到 waifu2x 服务: {e}") from e

    async def poll_status(self, service_url: str, task_ref: str) -> dict:
        """查询任务执行状态。

        Returns:
            {"status": "running" | "completed" | "failed",
             "result": {...} | None,
             "error": str | None}
        """
        url = f"{service_url.rstrip('/')}/v1/status/{task_ref}"
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url) as resp:
                    if resp.status == 200:
                        return await resp.json()
                    if resp.status == 404:
                        return {
                            "status": "failed",
                            "result": None,
                            "error": f"任务 {task_ref} 未找到",
                        }
                    text = await resp.text()
                    return {
                        "status": "failed",
                        "result": None,
                        "error": f"状态查询失败: HTTP {resp.status}",
                    }
        except aiohttp.ClientError as e:
            return {
                "status": "failed",
                "result": None,
                "error": f"状态查询异常: {e}",
            }


register_adapter("waifu2x", Waifu2xAdapter)
