"""业务状态层 biz：人工复核留痕 / 金蝶推送与凭证关联。"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, BigInteger, DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base, BIGINT_PK


class FlowReview(Base):
    __tablename__ = "biz_flow_review"

    review_id: Mapped[int] = mapped_column(BIGINT_PK, primary_key=True, autoincrement=True)
    record_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("dwd_trans_flow.record_id"), nullable=False, index=True)
    batch_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    review_result: Mapped[str] = mapped_column(String(16), nullable=False)
    reviewer: Mapped[str] = mapped_column(String(64), nullable=False)
    review_time: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    matched_subject: Mapped[str | None] = mapped_column(String(255), nullable=True)
    comment: Mapped[str | None] = mapped_column(String(512), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class PushRecord(Base):
    __tablename__ = "biz_push_record"

    push_id: Mapped[int] = mapped_column(BIGINT_PK, primary_key=True, autoincrement=True)
    record_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("dwd_trans_flow.record_id"), nullable=False, index=True)
    batch_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    push_status: Mapped[str] = mapped_column(String(16), nullable=False, default="PENDING")
    voucher_no: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    kingdee_doc_no: Mapped[str | None] = mapped_column(String(64), nullable=True)
    pushed_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    pushed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_msg: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    response_payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())