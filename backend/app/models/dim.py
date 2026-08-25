from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, BigInteger, Boolean, DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base, BIGINT_PK


class Bank(Base):
    __tablename__ = "dim_bank"
    bank_id: Mapped[int] = mapped_column(BIGINT_PK, primary_key=True, autoincrement=True)
    bank_code: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)
    bank_name: Mapped[str] = mapped_column(String(128), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())
    accounts: Mapped[list["BankAccount"]] = relationship(back_populates="bank")


class BankAccount(Base):
    __tablename__ = "dim_bank_account"
    account_id: Mapped[int] = mapped_column(BIGINT_PK, primary_key=True, autoincrement=True)
    bank_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("dim_bank.bank_id"), nullable=False)
    account_no: Mapped[str] = mapped_column(String(64), nullable=False)
    account_name: Mapped[str] = mapped_column(String(128), nullable=False)
    account_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    default_currency: Mapped[str] = mapped_column(String(3), nullable=False, default="CNY")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())
    bank: Mapped["Bank"] = relationship(back_populates="accounts")


class ValidationRule(Base):
    __tablename__ = "dim_validation_rule"
    rule_code: Mapped[str] = mapped_column(String(32), primary_key=True)
    rule_name: Mapped[str] = mapped_column(String(128), nullable=False)
    rule_level: Mapped[str] = mapped_column(String(8), nullable=False, default="ERROR")
    is_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    threshold_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    description: Mapped[str | None] = mapped_column(String(512), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class AccountMapping(Base):
    """对方科目映射规则（决策 P1：规则命中自动预填 + 其余批量人工指定）。"""
    __tablename__ = "dim_account_mapping"
    mapping_id: Mapped[int] = mapped_column(BIGINT_PK, primary_key=True, autoincrement=True)
    pattern: Mapped[str] = mapped_column(String(128), nullable=False)
    match_type: Mapped[str] = mapped_column(String(8), nullable=False, default="KEYWORD")
    direction: Mapped[str] = mapped_column(String(8), nullable=False, default="BOTH")
    subject_code: Mapped[str] = mapped_column(String(32), nullable=False)
    subject_name: Mapped[str] = mapped_column(String(128), nullable=False)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    is_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())
