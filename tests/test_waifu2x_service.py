# tests/test_waifu2x_service.py
import base64
import io

import pytest
from PIL import Image
from aiohttp.test_utils import AioHTTPTestCase

from services import waifu2x_service


def _make_image_b64() -> str:
    """生成一张 64x64 红色 PNG 图片的 base64 编码。"""
    img = Image.new("RGB", (64, 64), color=(255, 0, 0))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode("utf-8")


class TestWaifu2xService(AioHTTPTestCase):
    """waifu2x 服务包装器端点测试。"""

    async def get_application(self):
        """返回待测 aiohttp 应用。"""
        return waifu2x_service.create_app()

    async def test_health(self):
        """健康检查返回 200 和 ok 状态。"""
        resp = await self.client.request("GET", "/health")
        assert resp.status == 200
        body = await resp.json()
        assert body["status"] == "ok"

    async def test_upscale_returns_task_id(self):
        """提交合法任务返回 task_id 和 queued 状态。"""
        payload = {
            "image": _make_image_b64(),
            "scale": 2,
            "denoise_level": 0,
            "model_type": "cunet",
            "tile_size": 256,
        }
        resp = await self.client.request("POST", "/v1/upscale", json=payload)
        assert resp.status == 202
        body = await resp.json()
        assert "task_id" in body
        assert body["status"] == "queued"

    async def test_status_completed(self):
        """提交后查询状态应最终为 completed。"""
        payload = {
            "image": _make_image_b64(),
            "scale": 2,
        }
        resp = await self.client.request("POST", "/v1/upscale", json=payload)
        body = await resp.json()
        task_id = body["task_id"]

        # mock 模式任务执行很快，直接查询应已完成
        resp2 = await self.client.request("GET", f"/v1/status/{task_id}")
        body2 = await resp2.json()
        assert body2["status"] == "completed"
        assert "image_base64" in body2["result"]

    async def test_upscale_invalid_scale(self):
        """不支持的 scale 返回 400。"""
        payload = {
            "image": _make_image_b64(),
            "scale": 3,
        }
        resp = await self.client.request("POST", "/v1/upscale", json=payload)
        assert resp.status == 400

    async def test_status_not_found(self):
        """查询不存在的任务返回 404。"""
        resp = await self.client.request("GET", "/v1/status/not-exist")
        assert resp.status == 404
        body = await resp.json()
        assert body["status"] == "failed"
