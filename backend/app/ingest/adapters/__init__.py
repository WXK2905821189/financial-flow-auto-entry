from app.ingest.adapters import api_adapter  # noqa: F401
from app.ingest.adapters import file_adapter  # noqa: F401
from app.ingest.adapters import mock_adapter  # noqa: F401
from app.ingest.adapters.base import BaseAdapter
from app.ingest.adapters.registry import get_adapter, list_adapters, register_adapter

__all__ = [
    "BaseAdapter",
    "get_adapter",
    "list_adapters",
    "register_adapter",
]