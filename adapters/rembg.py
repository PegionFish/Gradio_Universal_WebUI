# adapters/rembg.py — RemBg 背景移除模型适配器

from typing import Optional

import aiohttp

from adapters import register_adapter
from adapters.base import BaseModelAdapter


class RemBgAdapter(BaseModelAdapter):
    """RemBg 模型适配器。

    通过 HTTP API 调用外部 RemBg 服务。支持：
    - 图片背景移除
    - 6 种 ONNX 模型选择
    - 透明背景 PNG 输出

    HTTP API 约定：
    - POST /v1/remove-bg        提交背景移除任务
    - GET  /v1/status/<task_id>  查询任务状态
    - GET  /health               健康检查
    """

    VALID_MODELS = {
        "isnet-general-use",
        "u2net",
        "u2netp",
        "u2net_human_seg",
        "u2net_cloth_seg",
        "isnet-anime",
    }

    def model_type(self) -> str:
        return "rembg"

    async def validate(self, payload: dict) -> list[str]:
        errors = []
        if not payload.get("image"):
            errors.append("image 为必填字段（base64 字符串）")

        model = payload.get("model", "isnet-general-use")
        if model not in self.VALID_MODELS:
            errors.append(
                f"model 必须是 {sorted(self.VALID_MODELS)} 之一"
            )
        return errors

    async def submit(
        self,
        service_url: str,
        payload: dict,
        target_gpu: Optional[list[int]] = None,
    ) -> str:
        url = service_url.rstrip("/") + "/v1/remove-bg"
        body = {
            "image": payload.get("image"),
            "model": payload.get("model", "isnet-general-use"),
        }

        timeout = aiohttp.ClientTimeout(total=120)
        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(url, json=body) as resp:
                    if resp.status == 202:
                        data = await resp.json()
                        return data["task_id"]
                    text = await resp.text()
                    if resp.status == 400:
                        raise ValueError(text[:200])
                    raise ConnectionError(
                        f"RemBg 服务返回 {resp.status}: {text[:200]}"
                    )
        except aiohttp.ClientError as e:
            raise ConnectionError(f"无法连接到 RemBg 服务: {e}") from e

    async def poll_status(self, service_url: str, task_ref: str) -> dict:
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


register_adapter("rembg", RemBgAdapter)
