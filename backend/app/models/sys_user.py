"""应用层账号表 sys_user：简版登录（决策 D2=A 简版账号 + 角色）。

属于 Web 应用层能力，独立于数据工程师的中间池 schema，用于登录鉴权与角色分权。
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base, BIGINT_PK


class User(Base):
    __tablename__ = "sys_user"

    user_id: Mapped[int] = mapped_column(BIGINT_PK, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    display_name: Mapped[str] = mapped_column(String(64), nullable=False)
    role: Mapped[str] = mapped_column(String(16), nullable=False, default="REVIEWER")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())