# adapters/__init__.py — 适配器注册表

from adapters.base import BaseModelAdapter

_ADAPTER_REGISTRY: dict[str, type[BaseModelAdapter]] = {}


def register_adapter(model_type: str, adapter_cls: type[BaseModelAdapter]):
    """注册模型适配器。

    Args:
        model_type: 模型类型标识符（如 "stable-diffusion"）
        adapter_cls: 适配器类（BaseModelAdapter 子类）
    """
    _ADAPTER_REGISTRY[model_type] = adapter_cls


def get_adapter(model_type: str) -> BaseModelAdapter:
    """获取指定模型类型的适配器实例。

    Args:
        model_type: 模型类型标识符

    Returns:
        BaseModelAdapter 实例

    Raises:
        ValueError: model_type 未注册
    """
    cls = _ADAPTER_REGISTRY.get(model_type)
    if not cls:
        raise ValueError(
            f"未知的 model_type: '{model_type}'，没有注册对应的适配器"
        )
    return cls()


def get_registered_types() -> list[str]:
    """返回所有已注册的 model_type。"""
    return list(_ADAPTER_REGISTRY.keys())


def is_registered(model_type: str) -> bool:
    """检查 model_type 是否已注册。"""
    return model_type in _ADAPTER_REGISTRY


__all__ = [
    "BaseModelAdapter",
    "register_adapter",
    "get_adapter",
    "get_registered_types",
    "is_registered",
]
