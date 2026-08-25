"""复核工作台接口：待复核列表、单笔/批量复核。"""
from __future__ import annotations

from datetime import date, time

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.deps import get_current_user
from app.core.contract import ReviewResult
from app.core.database import get_db
from app.models import Bank, BankAccount
from app.services import account_mapper as mapper_svc
from app.services import review as review_svc

router = APIRouter(prefix="/api/review", tags=["review"])


class ReviewRequest(BaseModel):
    record_id: int
    result: ReviewResult
    matched_subject: str | None = None
    comment: str | None = None


class BatchReviewRequest(BaseModel):
    record_ids: list[int]
    result: ReviewResult
    comment: str | None = None


@router.get("/pending")
def pending(
    limit: int = 100,
    offset: int = 0,
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    flows = review_svc.list_pending(db, limit=limit, offset=offset)
    return [_flow_dict(db, f) for f in flows]


@router.post("/decide")
def decide(
    body: ReviewRequest,
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
    request: Request = None,
):
    try:
        r = review_svc.review_record(
            db,
            record_id=body.record_id,
            result=body.result,
            reviewer=user["username"],
            matched_subject=body.matched_subject,
            comment=body.comment,
            ip_address=_ip(request),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"review_id": r.review_id, "result": r.review_result, "record_id": body.record_id}


@router.post("/decide-batch")
def decide_batch(
    body: BatchReviewRequest,
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
    request: Request = None,
):
    done = []
    for rid in body.record_ids:
        try:
            r = review_svc.review_record(
                db,
                record_id=rid,
                result=body.result,
                reviewer=user["username"],
                comment=body.comment,
                ip_address=_ip(request),
            )
            done.append({"record_id": rid, "result": r.review_result})
        except ValueError:
            done.append({"record_id": rid, "result": "SKIPPED"})
    return {"reviewed": len(done), "items": done}


def _ip(request):
    return request.client.host if request and request.client else None


def _flow_dict(db: Session, f) -> dict:
    bank = db.get(Bank, f.bank_id) if f.bank_id else None
    account = db.get(BankAccount, f.account_id) if f.account_id else None
    return {
        "record_id": f.record_id,
        "bank_name": bank.bank_name if bank else None,
        "account_name": account.account_name if account else None,
        "batch_id": f.batch_id,
        "txn_no": f.txn_no,
        "txn_date": f.txn_date.isoformat() if isinstance(f.txn_date, date) else str(f.txn_date),
        "txn_time": f.txn_time.isoformat(timespec="seconds") if isinstance(f.txn_time, time) else None,
        "amount": str(f.amount),
        "dc_flag": f.dc_flag,
        "currency": f.currency,
        "counterparty_name": f.counterparty_name,
        "counterparty_account": f.counterparty_account,
        "summary": f.summary,
        "process_status": f.process_status,
        "validation_status": f.validation_status,
        "exception_type": f.exception_type,
        "auto_subject": (f.ext_json or {}).get(mapper_svc.AUTO_SUBJECT_KEY),
    }