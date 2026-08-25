"""数据溯源接口：账→单 / 单→账 双向可查（对应工作包 7 溯源机制）。"""
from __future__ import annotations

from datetime import date, datetime, time

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.database import get_db
from app.models import Bank, BankAccount, BankRawFlow, FlowBatch, FlowReview, FlowValidation, PushRecord, TransFlow

router = APIRouter(prefix="/api/trace", tags=["trace"])


@router.get("/by-voucher")
def by_voucher(
    voucher_no: str = Query(...),
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """账 → 单：金蝶凭证号回溯原始流水、采集批次、复核与推送记录。"""
    push = db.execute(
        select(PushRecord).where(PushRecord.voucher_no == voucher_no).order_by(PushRecord.push_id.desc()).limit(1)
    ).scalar_one_or_none()
    if push is None:
        raise HTTPException(status_code=404, detail="未找到该凭证号对应的流水")
    return _record_trace(db, push.record_id)


@router.get("/by-record")
def by_record(
    record_id: int = Query(...),
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """单 → 账：原始流水回溯批次 / 校验 / 复核 / 推送 / 凭证号。"""
    return _record_trace(db, record_id)


def _record_trace(db: Session, record_id: int) -> dict:
    flow = db.get(TransFlow, record_id)
    if flow is None:
        raise HTTPException(status_code=404, detail="流水不存在")

    batch = db.get(FlowBatch, flow.batch_id)
    bank = db.get(Bank, flow.bank_id)
    account = db.get(BankAccount, flow.account_id)
    raw = db.get(BankRawFlow, flow.raw_id) if flow.raw_id else None
    validations = db.execute(
        select(FlowValidation).where(FlowValidation.record_id == record_id)
    ).scalars().all()
    reviews = db.execute(
        select(FlowReview).where(FlowReview.record_id == record_id).order_by(FlowReview.review_id)
    ).scalars().all()
    pushes = db.execute(
        select(PushRecord).where(PushRecord.record_id == record_id).order_by(PushRecord.push_id)
    ).scalars().all()

    return {
        "flow": {
            "record_id": flow.record_id,
            "dedup_key": flow.dedup_key,
            "txn_no": flow.txn_no,
            "txn_date": flow.txn_date.isoformat() if isinstance(flow.txn_date, date) else str(flow.txn_date),
            "txn_time": flow.txn_time.isoformat(timespec="seconds") if isinstance(flow.txn_time, time) else None,
            "currency": flow.currency,
            "amount": str(flow.amount),
            "dc_flag": flow.dc_flag,
            "counterparty_name": flow.counterparty_name,
            "counterparty_account": flow.counterparty_account,
            "summary": flow.summary,
            "process_status": flow.process_status,
            "validation_status": flow.validation_status,
            "exception_type": flow.exception_type,
        },
        "batch": {
            "batch_id": batch.batch_id,
            "batch_no": batch.batch_no,
            "source_type": batch.source_type,
            "source_ref": batch.source_ref,
            "contract_version": batch.contract_version,
            "imported_by": batch.imported_by,
            "imported_at": batch.imported_at.isoformat() if isinstance(batch.imported_at, datetime) else str(batch.imported_at) if batch.imported_at else None,
        },
        "bank": {"bank_code": bank.bank_code, "bank_name": bank.bank_name} if bank else None,
        "account": {"account_no": account.account_no, "account_name": account.account_name} if account else None,
        "raw": {"raw_id": raw.raw_id, "raw_hash": raw.raw_hash, "raw_content": raw.raw_content} if raw else None,
        "validations": [
            {"rule_code": v.rule_code, "rule_result": v.rule_result, "error_detail": v.error_detail}
            for v in validations
        ],
        "reviews": [
            {"reviewer": r.reviewer, "review_result": r.review_result,
             "review_time": r.review_time.isoformat() if isinstance(r.review_time, datetime) else str(r.review_time),
             "matched_subject": r.matched_subject, "comment": r.comment}
            for r in reviews
        ],
        "pushes": [{"push_id": p.push_id, "push_status": p.push_status,
                    "voucher_no": p.voucher_no, "kingdee_doc_no": p.kingdee_doc_no,
                    "pushed_by": p.pushed_by, "error_msg": p.error_msg,
                    "pushed_at": p.pushed_at.isoformat() if isinstance(p.pushed_at, datetime) else str(p.pushed_at) if p.pushed_at else None} for p in pushes],
    }