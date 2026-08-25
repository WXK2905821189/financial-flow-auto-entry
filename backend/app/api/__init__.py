"""API 层路由统一出口。"""
from app.api import auth, dashboard, push, review, trace

__all__ = ["auth", "dashboard", "push", "review", "trace"]