"""标准化中间层 dwd：采集批次 / 统一流水主表 / 校验留痕。"""
from __future__ import annotations

from datetime import date, datetime, time
from decimal import Decimal

from sqlalchemy import (
    DECIMAL,
    JSON,
    BigInteger,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Time,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base, BIGINT_PK


class FlowBatch(Base):
    __tablename__ = "dwd_flow_batch"

    batch_id: Mapped[int] = mapped_column(BIGINT_PK, primary_key=True, autoincrement=True)
    batch_no: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    source_type: Mapped[str] = mapped_column(String(16), nullable=False)
    bank_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("dim_bank.bank_id"), nullable=False)
    account_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("dim_bank_account.account_id"), nullable=False)
    source_ref: Mapped[str | None] = mapped_column(String(512), nullable=True)
    contract_version: Mapped[str] = mapped_column(String(16), nullable=False, default="v1")
    flow_date_start: Mapped[date | None] = mapped_column(Date, nullable=True)
    flow_date_end: Mapped[date | None] = mapped_column(Date, nullable=True)
    total_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_amount: Mapped[Decimal] = mapped_column(DECIMAL(20, 2), nullable=False, default=0)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="IMPORTING")
    imported_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    imported_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


class TransFlow(Base):
    __tablename__ = "dwd_trans_flow"

    record_id: Mapped[int] = mapped_column(BIGINT_PK, primary_key=True, autoincrement=True)
    dedup_key: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    batch_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("dwd_flow_batch.batch_id"), nullable=False, index=True)
    bank_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("dim_bank.bank_id"), nullable=False)
    account_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("dim_bank_account.account_id"), nullable=False)
    raw_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    contract_version: Mapped[str] = mapped_column(String(16), nullable=False, default="v1")

    # 统一流水契约核心字段
    txn_no: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    txn_date: Mapped[date] = mapped_column(Date, nullable=False)
    txn_time: Mapped[time | None] = mapped_column(Time, nullable=True)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="CNY")
    amount: Mapped[Decimal] = mapped_column(DECIMAL(20, 2), nullable=False)
    dc_flag: Mapped[str] = mapped_column(String(1), nullable=False)
    counterparty_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    counterparty_account: Mapped[str | None] = mapped_column(String(64), nullable=True)
    summary: Mapped[str | None] = mapped_column(String(512), nullable=True)

    # 状态与校验
    process_status: Mapped[str] = mapped_column(String(32), nullable=False, default="LOADED", index=True)
    validation_status: Mapped[str] = mapped_column(String(16), nullable=False, default="PENDING")
    exception_type: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # 扩展
    ext_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


class FlowValidation(Base):
    __tablename__ = "dwd_flow_validation"

    validation_id: Mapped[int] = mapped_column(BIGINT_PK, primary_key=True, autoincrement=True)
    record_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("dwd_trans_flow.record_id"), nullable=False, index=True)
    batch_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    rule_code: Mapped[str] = mapped_column(String(32), nullable=False)
    rule_result: Mapped[str] = mapped_column(String(8), nullable=False)
    error_detail: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())