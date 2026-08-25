"""采集适配层统一出口：import 本包即触发三类适配器注册。"""
from app.adapters import api_adapter  # noqa: F401
from app.adapters import file_adapter  # noqa: F401
from app.adapters import mock_adapter  # noqa: F401
from app.adapters.base import BaseAdapter
from app.adapters.registry import get_adapter, list_adapters, register_adapter

__all__ = ["BaseAdapter", "register_adapter", "get_adapter", "list_adapters"]