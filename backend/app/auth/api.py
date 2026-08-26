"""本地账号、RBAC、银行/账户范围与可撤销 Cookie 会话接口。"""
from __future__ import annotations

import secrets
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import audit as audit_svc
from app.core.config import settings
from app.core.database import get_db
from app.core.deps import get_current_user, require_permission
from app.core.permissions import Permission, Role, is_system_admin
from app.core.security import (
    create_access_token,
    create_refresh_secret,
    hash_password,
    hash_refresh_secret,
    validate_password,
    verify_password,
)
from app.models import Bank, BankAccount, User, UserScope, UserSession

router = APIRouter(prefix="/api/auth", tags=["auth"])

_VALID_ROLES = {role.value for role in Role}


class LoginRequest(BaseModel):
    username: str
    password: str


class PasswordChangeRequest(BaseModel):
    current_password: str
    new_password: str


class ResetPasswordRequest(BaseModel):
    new_password: str


class ScopeInput(BaseModel):
    bank_id: int | None = None
    account_id: int | None = None

    @model_validator(mode="after")
    def _has_scope_target(self):
        if self.bank_id is None and self.account_id is None:
            raise ValueError("范围授权至少指定 bank_id 或 account_id")
        return self


class UserCreateRequest(BaseModel):
    username: str = Field(min_length=3, max_length=64)
    display_name: str = Field(min_length=1, max_length=64)
    password: str
    role: str
    scopes: list[ScopeInput] = Field(default_factory=list)

    @field_validator("role")
    @classmethod
    def _valid_role(cls, value: str) -> str:
        if value not in _VALID_ROLES:
            raise ValueError("角色必须为系统管理员、财务主管、复核员、采集员或审计只读之一")
        return value


class UserUpdateRequest(BaseModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=64)
    role: str | None = None
    is_active: bool | None = None
    scopes: list[ScopeInput] | None = None

    @field_validator("role")
    @classmethod
    def _valid_role(cls, value: str | None) -> str | None:
        if value is not None and value not in _VALID_ROLES:
            raise ValueError("角色不合法")
        return value


def _ip(request: Request) -> str | None:
    return request.client.host if request.client else None


def _now() -> datetime:
    return datetime.utcnow()


def _set_cookies(response: Response, user: User, session: UserSession, refresh_secret: str) -> None:
    common = {
        "path": "/",
        "secure": settings.auth_cookie_secure,
        "samesite": settings.auth_cookie_samesite.lower(),
    }
    response.set_cookie(
        key=settings.auth_cookie_name,
        value=create_access_token(user.username, session.session_id),
        httponly=True,
        max_age=settings.access_token_expire_minutes * 60,
        **common,
    )
    response.set_cookie(
        key=settings.refresh_cookie_name,
        value=f"{session.session_id}.{refresh_secret}",
        httponly=True,
        max_age=settings.refresh_token_expire_minutes * 60,
        **common,
    )
    # 双提交 CSRF Cookie 不是身份凭据，可被前端读取后写入请求头。
    response.set_cookie(
        key=settings.csrf_cookie_name,
        value=secrets.token_urlsafe(24),
        httponly=False,
        max_age=settings.refresh_token_expire_minutes * 60,
        **common,
    )


def _clear_cookies(response: Response) -> None:
    for name in (settings.auth_cookie_name, settings.refresh_cookie_name, settings.csrf_cookie_name):
        response.delete_cookie(name, path="/", secure=settings.auth_cookie_secure, samesite=settings.auth_cookie_samesite.lower())


def _validate_csrf(request: Request) -> None:
    cookie = request.cookies.get(settings.csrf_cookie_name)
    header = request.headers.get("X-CSRF-Token")
    if not cookie or not header or not secrets.compare_digest(cookie, header):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="CSRF 校验失败")


def _new_session(db: Session, user: User, request: Request) -> tuple[UserSession, str]:
    refresh_secret = create_refresh_secret()
    session = UserSession(
        session_id=secrets.token_urlsafe(32),
        user_id=user.user_id,
        refresh_token_hash=hash_refresh_secret(refresh_secret),
        is_active=True,
        expires_at=_now() + timedelta(minutes=settings.refresh_token_expire_minutes),
        created_ip=_ip(request),
        last_seen_at=_now(),
    )
    db.add(session)
    db.flush()
    return session, refresh_secret


def _session_summary(user: User, session: UserSession) -> dict:
    return {
        "username": user.username,
        "display_name": user.display_name,
        "role": user.role,
        "session_id": session.session_id,
        "expires_at": session.expires_at.isoformat(),
        "must_change_password": user.password_changed_at is None,
    }


def _user_scopes(db: Session, user_id: int) -> list[dict]:
    rows = db.execute(
        select(UserScope).where(UserScope.user_id == user_id).order_by(UserScope.scope_id)
    ).scalars().all()
    return [{"scope_id": row.scope_id, "bank_id": row.bank_id, "account_id": row.account_id} for row in rows]


def _user_payload(db: Session, user: User) -> dict:
    return {
        "user_id": user.user_id,
        "username": user.username,
        "display_name": user.display_name,
        "role": user.role,
        "is_active": user.is_active,
        "created_at": user.created_at.isoformat() if user.created_at else None,
        "scopes": _user_scopes(db, user.user_id),
    }


def _replace_scopes(db: Session, user: User, scopes: list[ScopeInput], granted_by: str) -> None:
    seen: set[tuple[int | None, int | None]] = set()
    validated: list[tuple[int | None, int | None]] = []
    for scope in scopes:
        key = (scope.bank_id, scope.account_id)
        if key in seen:
            continue
        seen.add(key)
        bank = db.get(Bank, scope.bank_id) if scope.bank_id is not None else None
        account = db.get(BankAccount, scope.account_id) if scope.account_id is not None else None
        if scope.bank_id is not None and bank is None:
            raise HTTPException(status_code=400, detail="范围中的银行不存在")
        if scope.account_id is not None and account is None:
            raise HTTPException(status_code=400, detail="范围中的账户不存在")
        if bank is not None and account is not None and account.bank_id != bank.bank_id:
            raise HTTPException(status_code=400, detail="账户不属于指定银行")
        validated.append(key)

    db.query(UserScope).filter(UserScope.user_id == user.user_id).delete(synchronize_session=False)
    for bank_id, account_id in validated:
        db.add(UserScope(user_id=user.user_id, bank_id=bank_id, account_id=account_id, granted_by=granted_by))


def _active_admin_count(db: Session) -> int:
    return len(
        db.execute(
            select(User.user_id).where(User.is_active.is_(True), User.role.in_([Role.SYSTEM_ADMIN.value, "ADMIN"]))
        ).scalars().all()
    )


def _protect_last_admin(db: Session, target: User, *, next_role: str, next_active: bool) -> None:
    if is_system_admin(target.role) and target.is_active and (not is_system_admin(next_role) or not next_active):
        if _active_admin_count(db) <= 1:
            raise HTTPException(status_code=400, detail="不能禁用或降级最后一个系统管理员")


@router.post("/login")
def login(body: LoginRequest, response: Response, request: Request, db: Session = Depends(get_db)):
    user = db.execute(select(User).where(User.username == body.username)).scalar_one_or_none()
    now = _now()
    locked = user is not None and user.locked_until is not None and user.locked_until > now
    valid = user is not None and user.is_active and not locked and verify_password(body.password, user.password_hash)
    if not valid:
        if user is not None and user.is_active and not locked:
            user.failed_login_count += 1
            if user.failed_login_count >= settings.max_failed_logins:
                user.locked_until = now + timedelta(minutes=settings.login_lockout_minutes)
                action = "LOGIN_LOCKED"
            else:
                action = "LOGIN_DENIED"
        else:
            action = "LOGIN_LOCKED" if locked else "LOGIN_DENIED"
        audit_svc.append_audit(db, actor=body.username, action=action, entity_type="user", entity_id=body.username, detail={"locked": action == "LOGIN_LOCKED"}, ip_address=_ip(request))
        db.commit()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="账号或密码错误")
    user.failed_login_count = 0
    user.locked_until = None
    session, refresh_secret = _new_session(db, user, request)
    audit_svc.append_audit(db, actor=user.username, action="LOGIN", entity_type="session", entity_id=session.session_id, ip_address=_ip(request))
    db.commit()
    _set_cookies(response, user, session, refresh_secret)
    return _session_summary(user, session)


@router.post("/refresh")
def refresh(response: Response, request: Request, db: Session = Depends(get_db)):
    _validate_csrf(request)
    raw = request.cookies.get(settings.refresh_cookie_name, "")
    try:
        session_id, refresh_secret = raw.split(".", 1)
    except ValueError as exc:
        raise HTTPException(status_code=401, detail="刷新会话无效") from exc
    session = db.get(UserSession, session_id)
    user = db.get(User, session.user_id) if session else None
    if (
        session is None or user is None or not user.is_active or not session.is_active
        or session.revoked_at is not None or session.expires_at <= _now()
        or not secrets.compare_digest(session.refresh_token_hash, hash_refresh_secret(refresh_secret))
    ):
        raise HTTPException(status_code=401, detail="刷新会话无效")
    session.is_active = False
    session.revoked_at = _now()
    replacement, new_secret = _new_session(db, user, request)
    audit_svc.append_audit(db, actor=user.username, action="SESSION_ROTATE", entity_type="session", entity_id=replacement.session_id, ip_address=_ip(request))
    db.commit()
    _set_cookies(response, user, replacement, new_secret)
    return _session_summary(user, replacement)


@router.post("/logout")
def logout(response: Response, request: Request, user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    session = db.get(UserSession, user["session_id"])
    if session:
        session.is_active = False
        session.revoked_at = _now()
    audit_svc.append_audit(db, actor=user["username"], action="LOGOUT", entity_type="session", entity_id=user["session_id"], ip_address=_ip(request))
    db.commit()
    _clear_cookies(response)
    return {"ok": True}


@router.get("/me")
def me(user: dict = Depends(get_current_user)):
    return {key: user[key] for key in ("user_id", "username", "display_name", "role", "session_id", "must_change_password", "can_read_pii")}


@router.post("/password/change")
def change_password(body: PasswordChangeRequest, request: Request, user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    target = db.get(User, user["user_id"])
    if target is None or not verify_password(body.current_password, target.password_hash):
        raise HTTPException(status_code=400, detail="当前密码错误")
    try:
        validate_password(body.new_password)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    target.password_hash = hash_password(body.new_password)
    target.password_changed_at = _now()
    target.failed_login_count = 0
    target.locked_until = None
    db.query(UserSession).filter(UserSession.user_id == target.user_id, UserSession.session_id != user["session_id"]).update({"is_active": False, "revoked_at": _now()}, synchronize_session=False)
    audit_svc.append_audit(db, actor=user["username"], action="PASSWORD_CHANGE", entity_type="user", entity_id=str(target.user_id), ip_address=_ip(request))
    db.commit()
    return {"ok": True}


@router.get("/sessions")
def list_sessions(user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    rows = db.execute(
        select(UserSession).where(UserSession.user_id == user["user_id"]).order_by(UserSession.created_at.desc())
    ).scalars().all()
    return [{"session_id": row.session_id, "is_current": row.session_id == user["session_id"], "is_active": row.is_active, "created_ip": row.created_ip, "last_seen_at": row.last_seen_at.isoformat() if row.last_seen_at else None, "expires_at": row.expires_at.isoformat(), "created_at": row.created_at.isoformat() if row.created_at else None} for row in rows]


@router.delete("/sessions/{session_id}")
def revoke_session(session_id: str, request: Request, user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    session = db.get(UserSession, session_id)
    if session is None or session.user_id != user["user_id"]:
        raise HTTPException(status_code=404, detail="会话不存在")
    session.is_active = False
    session.revoked_at = _now()
    audit_svc.append_audit(db, actor=user["username"], action="SESSION_REVOKE", entity_type="session", entity_id=session_id, ip_address=_ip(request))
    db.commit()
    return {"ok": True}


@router.post("/sessions/revoke-all")
def revoke_all_sessions(request: Request, user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    count = db.query(UserSession).filter(UserSession.user_id == user["user_id"], UserSession.session_id != user["session_id"], UserSession.is_active.is_(True)).update({"is_active": False, "revoked_at": _now()}, synchronize_session=False)
    audit_svc.append_audit(db, actor=user["username"], action="SESSION_REVOKE_ALL", entity_type="user", entity_id=str(user["user_id"]), detail={"count": count}, ip_address=_ip(request))
    db.commit()
    return {"revoked": count, "current_session_kept": True}


@router.get("/users")
def list_users(user: dict = Depends(require_permission(Permission.USER_ADMIN.value)), db: Session = Depends(get_db)):
    rows = db.execute(select(User).order_by(User.username)).scalars().all()
    return {"items": [_user_payload(db, item) for item in rows]}


@router.post("/users", status_code=status.HTTP_201_CREATED)
def create_user(body: UserCreateRequest, request: Request, user: dict = Depends(require_permission(Permission.USER_ADMIN.value)), db: Session = Depends(get_db)):
    if db.execute(select(User.user_id).where(User.username == body.username)).scalar_one_or_none() is not None:
        raise HTTPException(status_code=409, detail="账号已存在")
    try:
        validate_password(body.password)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    target = User(username=body.username, display_name=body.display_name, password_hash=hash_password(body.password), role=body.role, is_active=True, password_changed_at=None)
    db.add(target)
    db.flush()
    _replace_scopes(db, target, body.scopes, user["username"])
    audit_svc.append_audit(db, actor=user["username"], action="USER_CREATE", entity_type="user", entity_id=str(target.user_id), detail={"role": target.role, "scope_count": len(body.scopes)}, ip_address=_ip(request))
    db.commit()
    return _user_payload(db, target)


@router.patch("/users/{user_id}")
def update_user(user_id: int, body: UserUpdateRequest, request: Request, user: dict = Depends(require_permission(Permission.USER_ADMIN.value)), db: Session = Depends(get_db)):
    target = db.get(User, user_id)
    if target is None:
        raise HTTPException(status_code=404, detail="账号不存在")
    next_role = body.role if body.role is not None else target.role
    next_active = body.is_active if body.is_active is not None else target.is_active
    _protect_last_admin(db, target, next_role=next_role, next_active=next_active)
    if body.display_name is not None:
        target.display_name = body.display_name
    target.role = next_role
    target.is_active = next_active
    if not next_active:
        target.disabled_at = _now()
        db.query(UserSession).filter(UserSession.user_id == target.user_id, UserSession.is_active.is_(True)).update({"is_active": False, "revoked_at": _now()}, synchronize_session=False)
    elif target.disabled_at is not None:
        target.disabled_at = None
    if body.scopes is not None:
        _replace_scopes(db, target, body.scopes, user["username"])
    audit_svc.append_audit(db, actor=user["username"], action="USER_UPDATE", entity_type="user", entity_id=str(target.user_id), detail={"role": target.role, "is_active": target.is_active, "scopes_changed": body.scopes is not None}, ip_address=_ip(request))
    db.commit()
    return _user_payload(db, target)


@router.post("/users/{user_id}/disable")
def disable_user(user_id: int, request: Request, user: dict = Depends(require_permission(Permission.USER_ADMIN.value)), db: Session = Depends(get_db)):
    return update_user(user_id, UserUpdateRequest(is_active=False), request, user, db)


@router.post("/users/{user_id}/password/reset")
def reset_password(user_id: int, body: ResetPasswordRequest, request: Request, user: dict = Depends(require_permission(Permission.USER_ADMIN.value)), db: Session = Depends(get_db)):
    target = db.get(User, user_id)
    if target is None:
        raise HTTPException(status_code=404, detail="账号不存在")
    try:
        validate_password(body.new_password)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    target.password_hash = hash_password(body.new_password)
    # 管理员设置的是临时密码，目标用户下次登录必须自行修改。
    target.password_changed_at = None
    target.failed_login_count = 0
    target.locked_until = None
    db.query(UserSession).filter(UserSession.user_id == target.user_id, UserSession.is_active.is_(True)).update({"is_active": False, "revoked_at": _now()}, synchronize_session=False)
    audit_svc.append_audit(db, actor=user["username"], action="PASSWORD_RESET", entity_type="user", entity_id=str(target.user_id), ip_address=_ip(request))
    db.commit()
    return {"ok": True}
