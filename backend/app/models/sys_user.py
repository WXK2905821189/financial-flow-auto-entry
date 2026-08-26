"""应用层账号表 sys_user：简版登录（决策 D2=A 简版账号 + 角色）。

属于 Web 应用层能力，独立于数据工程师的中间池 schema，用于登录鉴权与角色分权。
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base, BIGINT_PK


class User(Base):
    __tablename__ = "sys_user"

    user_id: Mapped[int] = mapped_column(BIGINT_PK, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    display_name: Mapped[str] = mapped_column(String(64), nullable=False)
    role: Mapped[str] = mapped_column(String(32), nullable=False, default="REVIEWER")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    password_changed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    disabled_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    failed_login_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


class RolePermission(Base):
    """固定角色到权限点的映射；权限判定由 core.deps 统一执行。"""

    __tablename__ = "sys_role_permission"

    permission_id: Mapped[int] = mapped_column(BIGINT_PK, primary_key=True, autoincrement=True)
    role: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    permission_code: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class UserScope(Base):
    """用户可访问的银行或账户范围。bank_id 授权覆盖该银行下所有账户。"""

    __tablename__ = "sys_user_scope"

    scope_id: Mapped[int] = mapped_column(BIGINT_PK, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("sys_user.user_id"), nullable=False, index=True)
    bank_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("dim_bank.bank_id"), nullable=True, index=True)
    account_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("dim_bank_account.account_id"), nullable=True, index=True)
    granted_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class UserSession(Base):
    """可撤销的刷新会话；refresh_token_hash 只保存散列，轮换时创建新会话。"""

    __tablename__ = "sys_user_session"

    session_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("sys_user.user_id"), nullable=False, index=True)
    refresh_token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    created_ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
