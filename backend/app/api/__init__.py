"""API 层路由统一出口。"""
from app.api import auth, dashboard, ingest, push, review, trace

__all__ = ["auth", "dashboard", "ingest", "push", "review", "trace"]