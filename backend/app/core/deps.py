"""FastAPI 公共依赖：解析 Bearer Token → 当前用户。"""
from __future__ import annotations

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.security import decode_access_token

_bearer = HTTPBearer(auto_error=False)


def get_current_user(cred: HTTPAuthorizationCredentials | None = Depends(_bearer)) -> dict:
    if cred is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="未登录")
    try:
        payload = decode_access_token(cred.credentials)
    except Exception:  # noqa: BLE001
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="登录已过期或无效")
    return {"username": payload.get("sub"), "role": payload.get("role", "REVIEWER")}