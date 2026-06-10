# adapters/stable_diffusion.py — Stable Diffusion 模型适配器（真实实现）

from typing import Optional
import aiohttp
import asyncio
import logging
from adapters.base import BaseModelAdapter

logger = logging.getLogger(__name__)


class StableDiffusionAdapter(BaseModelAdapter):
    """Stable Diffusion 模型适配器 — Phase 3 实现。

    通过 HTTP API 调用外部 Stable Diffusion 服务。支持：
    - txt2img 文生图
    - img2img 图生图
    - 全参数控制（prompt/negative_prompt/width/height/steps/cfg_scale/seed）

    HTTP API 约定（适配器期望的服务端点）：
    - POST /v1/txt2img         文生图
    - POST /v1/img2img         图生图（可选）
    - GET  /v1/status/<task_id> 查询任务状态
    - GET  /health              健康检查
    """

    def model_type(self) -> str:
        return "stable-diffusion"

    async def validate(self, payload: dict) -> list[str]:
        """校验请求负载。"""
        errors = []
        if "prompt" not in payload or not payload.get("prompt", "").strip():
            errors.append("prompt 为必填字段（不能为空）")

        width = payload.get("width", 512)
        if not isinstance(width, int) or width < 64 or width > 2048:
            errors.append("width 必须在 64-2048 之间")
        if width % 64 != 0:
            errors.append("width 必须是 64 的倍数")

        height = payload.get("height", 512)
        if not isinstance(height, int) or height < 64 or height > 2048:
            errors.append("height 必须在 64-2048 之间")
        if height % 64 != 0:
            errors.append("height 必须是 64 的倍数")

        steps = payload.get("steps", 20)
        if not isinstance(steps, int) or steps < 1 or steps > 150:
            errors.append("steps 必须在 1-150 之间")

        cfg_scale = payload.get("cfg_scale", 7.0)
        if not isinstance(cfg_scale, (int, float)) or cfg_scale < 1.0 or cfg_scale > 30.0:
            errors.append("cfg_scale 必须在 1.0-30.0 之间")

        seed = payload.get("seed", -1)
        if not isinstance(seed, int):
            errors.append("seed 必须为整数（-1 表示随机）")

        return errors

    async def submit(
        self,
        service_url: str,
        payload: dict,
        target_gpu: Optional[list[int]] = None,
    ) -> str:
        """提交文生图/图生图任务到 Stable Diffusion 服务。

        Args:
            service_url: 服务的基础 URL（如 http://localhost:17860）
            payload: 请求参数
                - prompt: str, 必填
                - negative_prompt: str, 可选
                - width: int, 默认 512
                - height: int, 默认 512
                - steps: int, 默认 20
                - cfg_scale: float, 默认 7.0
                - seed: int, -1=随机
                - batch_size: int, 默认 1
                - init_image: str (base64), 可选 — 图生图模式
                - denoising_strength: float, 可选 — 图生图去噪强度
            target_gpu: 目标 GPU 索引列表

        Returns:
            服务侧的任务引用 ID

        Raises:
            ConnectionError: 服务不可达
            aiohttp.ClientError: HTTP 请求失败
        """
        # 根据参数决定使用 txt2img 还是 img2img
        endpoint = "/v1/img2img" if "init_image" in payload else "/v1/txt2img"
        url = service_url.rstrip("/") + endpoint

        body = {
            "prompt": payload["prompt"],
            "negative_prompt": payload.get("negative_prompt", ""),
            "width": payload.get("width", 512),
            "height": payload.get("height", 512),
            "steps": payload.get("steps", 20),
            "cfg_scale": payload.get("cfg_scale", 7.0),
            "seed": payload.get("seed", -1),
            "batch_size": payload.get("batch_size", 1),
        }

        if target_gpu:
            body["target_gpu"] = target_gpu[0]

        if "init_image" in payload:
            body["init_image"] = payload["init_image"]
            body["denoising_strength"] = payload.get("denoising_strength", 0.75)

        timeout = aiohttp.ClientTimeout(total=600)  # 10 分钟超时
        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(url, json=body) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        return data.get("task_id", "")
                    elif resp.status == 422:
                        detail = await resp.json()
                        raise ValueError(
                            f"参数校验失败: {detail.get('detail', 'unknown')}"
                        )
                    else:
                        text = await resp.text()
                        raise ConnectionError(
                            f"Stable Diffusion 服务返回 {resp.status}: {text[:200]}"
                        )
        except aiohttp.ClientError as e:
            logger.error("SD 服务请求失败: %s", e)
            raise ConnectionError(f"无法连接到 SD 服务: {e}") from e
        except asyncio.TimeoutError:
            raise ConnectionError("SD 服务请求超时（600秒）")

    async def poll_status(self, service_url: str, task_ref: str) -> dict:
        """查询 SD 任务状态和结果。

        Args:
            service_url: 服务基础 URL
            task_ref: 任务引用 ID

        Returns:
            {
                "status": "running" | "completed" | "failed",
                "result": {
                    "images": ["base64_image_1", ...],
                    "seed": 12345,
                    "parameters": {...}
                } | None,
                "error": str | None,
                "progress": float | None  # 0-100 进度百分比
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
                            "error": f"状态查询失败: HTTP {resp.status}",
                            "progress": None,
                        }
        except (aiohttp.ClientError, asyncio.TimeoutError) as e:
            return {
                "status": "unknown", "result": None,
                "error": f"状态查询异常: {e}", "progress": None,
            }


from adapters import register_adapter
register_adapter("stable-diffusion", StableDiffusionAdapter)
