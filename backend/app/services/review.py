"""人工复核服务：低置信/超阈值流水的人工兜底（human-in-the-loop）。"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.contract import ProcessStatus, ReviewResult
from app.models import FlowReview, TransFlow
from app.core import audit as audit_svc


def review_record(
    db: Session,
    *,
    record_id: int,
    result: ReviewResult,
    reviewer: str,
    matched_subject: str | None = None,
    comment: str | None = None,
    ip_address: str | None = None,
) -> FlowReview:
    flow = db.get(TransFlow, record_id)
    if flow is None:
        raise ValueError(f"流水不存在：{record_id}")

    review = FlowReview(
        record_id=record_id,
        batch_id=flow.batch_id,
        review_result=result.value,
        reviewer=reviewer,
        review_time=datetime.now(),
        matched_subject=matched_subject,
        comment=comment,
    )
    db.add(review)

    if result == ReviewResult.PASS:
        flow.process_status = ProcessStatus.REVIEW_PASSED.value
    elif result == ReviewResult.REJECT:
        flow.process_status = ProcessStatus.REJECTED.value
    else:  # ADJUST：调整后视为通过，记录人工匹配科目
        flow.process_status = ProcessStatus.REVIEW_PASSED.value
        if matched_subject:
            flow.ext_json = {**(flow.ext_json or {}), "matched_subject": matched_subject}

    audit_svc.append_audit(
        db,
        actor=reviewer,
        action="REVIEW",
        entity_type="record",
        entity_id=str(record_id),
        detail={"result": result.value, "comment": comment, "matched_subject": matched_subject},
        ip_address=ip_address,
    )
    db.commit()
    db.refresh(review)
    return review


def list_pending(db: Session, *, limit: int = 100, offset: int = 0) -> list[TransFlow]:
    q = (
        select(TransFlow)
        .where(TransFlow.process_status == ProcessStatus.REVIEW_READY.value)
        .order_by(TransFlow.txn_date, TransFlow.record_id)
        .limit(limit)
        .offset(offset)
    )
    return list(db.execute(q).scalars().all())