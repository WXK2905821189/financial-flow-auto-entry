"""原始层 ods：银行原始流水原样归档（JSON 留痕 + 哈希）。"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, BigInteger, DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base, BIGINT_PK


class BankRawFlow(Base):
    __tablename__ = "ods_bank_raw_flow"

    raw_id: Mapped[int] = mapped_column(BIGINT_PK, primary_key=True, autoincrement=True)
    batch_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    record_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    source_file_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    source_uri: Mapped[str | None] = mapped_column(String(512), nullable=True)
    raw_content: Mapped[dict] = mapped_column(JSON, nullable=False)
    raw_hash: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())