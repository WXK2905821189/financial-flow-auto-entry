"""认证、RBAC 与银行/账户范围授权公共依赖。"""
from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

from fastapi import Cookie, Depends, HTTPException, Request, status
from sqlalchemy import false, select, true
from sqlalchemy.orm import Session

from app.core import audit as audit_svc
from app.core.config import settings
from app.core.database import get_db
from app.core.permissions import is_system_admin
from app.core.security import decode_access_token
from app.models import Bank, BankAccount, RolePermission, User, UserScope, UserSession


def _unauthorized(detail: str = "登录已过期或无效") -> HTTPException:
    return HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=detail)


def _audit_denial(db: Session, request: Request, *, actor: str, detail: str) -> None:
    audit_svc.append_audit(
        db,
        actor=actor,
        action="ACCESS_DENIED",
        entity_type="endpoint",
        entity_id=request.url.path,
        detail={"reason": detail, "method": request.method},
        ip_address=request.client.host if request.client else None,
    )
    db.commit()


def get_current_user(
    request: Request,
    access_token: str | None = Cookie(default=None, alias=settings.auth_cookie_name),
    csrf_token: str | None = Cookie(default=None, alias=settings.csrf_cookie_name),
    db: Session = Depends(get_db),
) -> dict:
    """逐请求校验 Cookie、账号状态、会话状态和当前数据库角色。"""
    if not access_token:
        _audit_denial(db, request, actor="anonymous", detail="未登录")
        raise _unauthorized("未登录")
    if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
        header = request.headers.get("X-CSRF-Token")
        if not csrf_token or not header or header != csrf_token:
            _audit_denial(db, request, actor="anonymous", detail="CSRF 校验失败")
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="CSRF 校验失败")
    try:
        payload = decode_access_token(access_token)
        username = payload.get("sub")
        session_id = payload.get("sid")
        if not username or not session_id:
            raise ValueError("令牌缺少会话信息")
    except Exception as exc:  # noqa: BLE001
        _audit_denial(db, request, actor="anonymous", detail="访问令牌无效")
        raise _unauthorized() from exc

    user = db.execute(select(User).where(User.username == username)).scalar_one_or_none()
    session = db.get(UserSession, session_id)
    now = datetime.utcnow()
    if (
        user is None
        or not user.is_active
        or session is None
        or session.user_id != user.user_id
        or not session.is_active
        or session.revoked_at is not None
        or session.expires_at <= now
    ):
        _audit_denial(db, request, actor=username, detail="账号或会话无效")
        raise _unauthorized()
    pii_allowed = db.execute(
        select(RolePermission.permission_id).where(
            RolePermission.role == user.role,
            RolePermission.permission_code == "pii:read",
        ).limit(1)
    ).scalar_one_or_none() is not None
    return {
        "user_id": user.user_id,
        "username": user.username,
        "display_name": user.display_name,
        "role": user.role,
        "session_id": session.session_id,
        "must_change_password": user.password_changed_at is None,
        "can_read_pii": pii_allowed,
    }


def require_permission(*permissions: str) -> Callable:
    """创建业务域可复用的权限依赖；未显式授权即默认拒绝。"""

    def dependency(
        request: Request,
        user: dict = Depends(get_current_user),
        db: Session = Depends(get_db),
    ) -> dict:
        # 权限表是运行时授权来源；表缺少映射时默认拒绝。静态矩阵仅用于播种。
        granted = set(
            db.execute(
                select(RolePermission.permission_code).where(RolePermission.role == user["role"])
            ).scalars()
        )
        if not all(permission in granted for permission in permissions):
            _audit_denial(db, request, actor=user["username"], detail=f"缺少权限：{','.join(permissions)}")
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无权执行此操作")
        if user["must_change_password"]:
            _audit_denial(db, request, actor=user["username"], detail="必须先修改初始密码")
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="首次登录必须先修改密码")
        return user

    return dependency


def allowed_account_ids(user: dict, db: Session) -> set[int] | None:
    """返回账户白名单；系统管理员返回 None 表示不限制。"""
    if is_system_admin(user["role"]):
        return None
    rows = db.execute(
        select(UserScope.bank_id, UserScope.account_id).where(UserScope.user_id == user["user_id"])
    ).all()
    account_ids = {row.account_id for row in rows if row.account_id is not None}
    bank_ids = {row.bank_id for row in rows if row.bank_id is not None}
    if bank_ids:
        account_ids.update(
            db.execute(select(BankAccount.account_id).where(BankAccount.bank_id.in_(bank_ids))).scalars()
        )
    return account_ids


def account_scope_clause(account_column, user: dict, db: Session):
    """供列表/看板查询注入账户范围条件；未授权范围时恒为 false。"""
    account_ids = allowed_account_ids(user, db)
    if account_ids is None:
        return true()
    return account_column.in_(account_ids) if account_ids else false()


def require_account_scope(user: dict, db: Session, *, bank_code: str, account_no: str, request: Request | None = None) -> None:
    """校验指定银行账号是否在当前用户的授权范围内。"""
    if is_system_admin(user["role"]):
        return
    bank = db.execute(select(Bank).where(Bank.bank_code == bank_code)).scalar_one_or_none()
    if bank is None:
        _audit_denial(db, request or _scope_request(), actor=user["username"], detail="银行不存在或无范围授权")
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="未获该银行账户范围授权")
    account = db.execute(
        select(BankAccount).where(
            BankAccount.bank_id == bank.bank_id,
            BankAccount.account_no == account_no,
        )
    ).scalar_one_or_none()
    account_ids = allowed_account_ids(user, db)
    # 新账号尚未落维表时，只有银行级授权可以进行首次采集。
    bank_scope = db.execute(
        select(UserScope.scope_id).where(
            UserScope.user_id == user["user_id"],
            UserScope.bank_id == bank.bank_id,
        ).limit(1)
    ).scalar_one_or_none()
    if bank_scope is None and (account is None or account.account_id not in (account_ids or set())):
        _audit_denial(db, request or _scope_request(), actor=user["username"], detail="未获该银行账户范围授权")
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="未获该银行账户范围授权")


def require_flow_scope(user: dict, db: Session, account_id: int, request: Request | None = None) -> None:
    account_ids = allowed_account_ids(user, db)
    if account_ids is not None and account_id not in account_ids:
        _audit_denial(db, request or _scope_request(), actor=user["username"], detail="未获该流水账户范围授权")
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="未获该流水账户范围授权")


def _scope_request() -> Request:
    """范围校验由服务函数调用，构造最小审计请求上下文。"""
    from starlette.requests import Request as StarletteRequest

    return StarletteRequest({"type": "http", "method": "GET", "path": "/api/scope/check", "headers": [], "client": None, "query_string": b""})
