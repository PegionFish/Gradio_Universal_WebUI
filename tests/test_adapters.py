# tests/test_adapters.py

import pytest

# 导入触发自动注册
import adapters.stable_diffusion
import adapters.qwen3_asr
import adapters.whisperx
import adapters.fastwhisper
from adapters import (
    register_adapter, get_adapter, get_registered_types, is_registered,
)
from adapters.base import BaseModelAdapter


class TestBaseModelAdapter:
    """验收标准 1: BaseModelAdapter 抽象类实例化时报 TypeError。"""

    def test_cannot_instantiate_abstract(self):
        with pytest.raises(TypeError):
            BaseModelAdapter()

    def test_poll_status_default(self):
        """基类 poll_status 返回未知状态。"""
        class TestAdapter(BaseModelAdapter):
            def model_type(self):
                return "test"
            async def submit(self, service_url, payload, target_gpu=None):
                return "task-1"
        adapter = TestAdapter()
        import asyncio
        result = asyncio.run(adapter.poll_status("http://localhost", "task-1"))
        assert result == {"status": "unknown", "result": None,
                          "error": "poll_status 未实现"}


class TestAdapterRegistration:
    """验收标准 5-7: get_adapter 返回正确实例、未知类型抛出异常、自动注册。"""

    def test_all_four_adapters_registered(self):
        types = get_registered_types()
        assert "stable-diffusion" in types
        assert "qwen3-asr" in types
        assert "whisperx" in types
        assert "fastwhisper" in types

    def test_get_adapter_stable_diffusion(self):
        adapter = get_adapter("stable-diffusion")
        assert adapter.model_type() == "stable-diffusion"

    def test_get_adapter_returns_new_instance_each_time(self):
        a1 = get_adapter("stable-diffusion")
        a2 = get_adapter("stable-diffusion")
        assert a1 is not a2

    def test_get_adapter_invalid_type(self):
        with pytest.raises(ValueError, match="未知的 model_type"):
            get_adapter("nonexistent-model")

    def test_is_registered(self):
        assert is_registered("stable-diffusion") is True
        assert is_registered("llama-7b") is False

    def test_manual_register_new_type(self):
        class CustomAdapter(BaseModelAdapter):
            def model_type(self):
                return "custom-type"
            async def submit(self, service_url, payload, target_gpu=None):
                return "task-1"
        register_adapter("custom-type", CustomAdapter)
        adapter = get_adapter("custom-type")
        assert adapter.model_type() == "custom-type"


class TestPlaceholderAdapters:
    """验收标准 2-3: model_type 正确、submit 抛出 NotImplementedError。"""

    @pytest.fixture
    def adapters(self):
        return {
            "stable-diffusion": get_adapter("stable-diffusion"),
            "qwen3-asr": get_adapter("qwen3-asr"),
            "whisperx": get_adapter("whisperx"),
            "fastwhisper": get_adapter("fastwhisper"),
        }

    def test_model_types_correct(self, adapters):
        expected = {
            "stable-diffusion": "stable-diffusion",
            "qwen3-asr": "qwen3-asr",
            "whisperx": "whisperx",
            "fastwhisper": "fastwhisper",
        }
        for key, adapter in adapters.items():
            assert adapter.model_type() == expected[key]

    def test_submit_raises_not_implemented(self, adapters):
        import asyncio
        for key, adapter in adapters.items():
            with pytest.raises(NotImplementedError):
                asyncio.run(adapter.submit("http://localhost", {}))

    def test_poll_status_returns_unknown(self, adapters):
        import asyncio
        for adapter in adapters.values():
            result = asyncio.run(adapter.poll_status("http://localhost", "t"))
            assert result["status"] == "unknown"


class TestStableDiffusionValidate:
    """验收标准 8: validate 返回正确的校验错误列表。"""

    def test_validate_passes_with_prompt(self):
        adapter = get_adapter("stable-diffusion")
        import asyncio
        errors = asyncio.run(adapter.validate({"prompt": "a cat"}))
        assert errors == []

    def test_validate_fails_without_prompt(self):
        adapter = get_adapter("stable-diffusion")
        import asyncio
        errors = asyncio.run(adapter.validate({}))
        assert len(errors) == 1
        assert "prompt" in errors[0].lower()

    def test_other_adapters_no_validation_by_default(self):
        import asyncio
        for mt in ("qwen3-asr", "whisperx", "fastwhisper"):
            adapter = get_adapter(mt)
            errors = asyncio.run(adapter.validate({}))
            assert errors == []  # 默认无校验错误
