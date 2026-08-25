"""适配器注册表：以 source_type 登记，支持外部动态注册（插件扩展点）。"""
from __future__ import annotations

from app.adapters.base import BaseAdapter
from app.contract import SourceType

_registry: dict[str, type[BaseAdapter]] = {}


def register_adapter(adapter_cls: type[BaseAdapter]) -> type[BaseAdapter]:
    if getattr(adapter_cls, "source_type", None) is None:
        raise ValueError(f"{adapter_cls.__name__} 缺少 source_type 声明")
    _registry[adapter_cls.source_type.value] = adapter_cls
    return adapter_cls


def get_adapter(source_type: SourceType | str, **init_kwargs) -> BaseAdapter:
    key = source_type.value if isinstance(source_type, SourceType) else source_type
    cls = _registry.get(key)
    if cls is None:
        raise KeyError(f"未注册的采集源类型: {key}")
    return cls(**init_kwargs)


def list_adapters() -> list[str]:
    return sorted(_registry.keys())