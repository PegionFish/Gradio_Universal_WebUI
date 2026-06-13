# tests/test_waifu2x_adapter.py
import asyncio

import pytest

# 导入触发自动注册
import adapters.waifu2x  # noqa: F401
from adapters import get_adapter, is_registered


class TestWaifu2xAdapter:
    """waifu2x 模型适配器测试。"""

    def test_model_type(self):
        """适配器 model_type 为 waifu2x。"""
        adapter = get_adapter("waifu2x")
        assert adapter.model_type() == "waifu2x"

    def test_registered_in_factory(self):
        """waifu2x 已在注册表中。"""
        assert is_registered("waifu2x") is True

    def test_get_adapter_returns_new_instance(self):
        """每次 get_adapter 返回新实例。"""
        a1 = get_adapter("waifu2x")
        a2 = get_adapter("waifu2x")
        assert a1 is not a2

    @pytest.mark.asyncio
    async def test_validate_missing_image(self):
        """缺少 image 字段时校验失败。"""
        adapter = get_adapter("waifu2x")
        errors = await adapter.validate({"scale": 2})
        assert any("image" in e for e in errors)

    @pytest.mark.asyncio
    async def test_validate_invalid_scale(self):
        """不支持的 scale 被拒绝。"""
        adapter = get_adapter("waifu2x")
        errors = await adapter.validate({"image": "...", "scale": 3})
        assert any("scale" in e for e in errors)

    @pytest.mark.asyncio
    async def test_validate_invalid_denoise(self):
        """不支持的 denoise_level 被拒绝。"""
        adapter = get_adapter("waifu2x")
        errors = await adapter.validate({"image": "...", "denoise_level": 5})
        assert any("denoise" in e for e in errors)

    @pytest.mark.asyncio
    async def test_validate_invalid_model_type(self):
        """不支持的 model_type 被拒绝。"""
        adapter = get_adapter("waifu2x")
        errors = await adapter.validate({"image": "...", "model_type": "unknown"})
        assert any("model_type" in e for e in errors)

    @pytest.mark.asyncio
    async def test_validate_invalid_tile_size(self):
        """tile_size 越界被拒绝。"""
        adapter = get_adapter("waifu2x")
        errors = await adapter.validate({"image": "...", "tile_size": 32})
        assert any("tile_size" in e for e in errors)

    @pytest.mark.asyncio
    async def test_validate_ok(self):
        """合法参数校验通过。"""
        adapter = get_adapter("waifu2x")
        errors = await adapter.validate(
            {
                "image": "iVBORw0KGgo=",
                "scale": 2,
                "denoise_level": 0,
                "model_type": "cunet",
                "tile_size": 256,
            }
        )
        assert errors == []

    def test_adapter_has_real_submit(self):
        """waifu2x 适配器 submit 为真实实现，不抛出 NotImplementedError。"""
        import inspect
        adapter = get_adapter("waifu2x")
        source = inspect.getsource(adapter.submit)
        assert "raise NotImplementedError" not in source

    def test_poll_status_returns_dict(self):
        """poll_status 返回包含 status 字段的字典。"""
        adapter = get_adapter("waifu2x")
        result = asyncio.run(adapter.poll_status("http://localhost", "task-1"))
        assert "status" in result
        assert isinstance(result["status"], str)
