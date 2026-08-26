"""人工复核服务：低置信/超阈值流水的人工兜底（human-in-the-loop）。"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.contract import APPROVED_SUBJECT_KEY, AUTO_SUBJECT_KEY, ProcessStatus, ReviewResult
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
    if flow.process_status != ProcessStatus.REVIEW_READY.value:
        raise ValueError(f"流水当前状态不可复核：{flow.process_status}")

    approved_subject = _resolve_approved_subject(flow, result, matched_subject)

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
    if approved_subject:
        flow.ext_json = {
            **(flow.ext_json or {}),
            APPROVED_SUBJECT_KEY: approved_subject,
        }

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


def _resolve_approved_subject(
    flow: TransFlow,
    result: ReviewResult,
    matched_subject: str | None,
) -> dict[str, str | None] | None:
    """把规则预填或人工调整统一为制证可消费的科目结构。"""
    if result == ReviewResult.REJECT:
        return None
    if result == ReviewResult.ADJUST:
        code = (matched_subject or "").strip()
        if not code:
            raise ValueError("调整后通过必须填写科目编码")
        return {"subject_code": code, "subject_name": None, "source": "MANUAL"}

    auto_subject = (flow.ext_json or {}).get(AUTO_SUBJECT_KEY)
    if not isinstance(auto_subject, dict) or not str(auto_subject.get("subject_code") or "").strip():
        raise ValueError("复核通过前必须存在有效科目；请使用调整后通过填写科目编码")
    return {
        "subject_code": str(auto_subject["subject_code"]).strip(),
        "subject_name": str(auto_subject.get("subject_name") or "").strip() or None,
        "source": "RULE",
    }


def list_pending(db: Session, *, account_ids: set[int] | None = None, limit: int = 100, offset: int = 0) -> list[TransFlow]:
    q = (
        select(TransFlow)
        .where(TransFlow.process_status == ProcessStatus.REVIEW_READY.value)
        .order_by(TransFlow.txn_date, TransFlow.record_id)
        .limit(limit)
        .offset(offset)
    )
    if account_ids is not None:
        q = q.where(TransFlow.account_id.in_(account_ids))
    return list(db.execute(q).scalars().all())


def list_records(
    db: Session,
    *,
    account_ids: set[int] | None = None,
    status: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[TransFlow]:
    """Return review history, optionally narrowed to one process status."""
    q = select(TransFlow).order_by(TransFlow.txn_date.desc(), TransFlow.record_id.desc())
    if status:
        q = q.where(TransFlow.process_status == status)
    if account_ids is not None:
        q = q.where(TransFlow.account_id.in_(account_ids))
    q = q.limit(limit).offset(offset)
    return list(db.execute(q).scalars().all())
