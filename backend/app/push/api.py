"""金蝶推送接口：单笔 / 批次一键推送（复核通过后触发）。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.deps import require_flow_scope, require_permission
from app.core.database import get_db
from app.core.permissions import Permission
from app.models import FlowBatch, TransFlow
from app.push import service as push_svc

router = APIRouter(prefix="/api/push", tags=["push"])


class PushRequest(BaseModel):
    record_id: int


class PushBatchRequest(BaseModel):
    batch_id: int


@router.post("/record")
def push_one(
    body: PushRequest,
    db: Session = Depends(get_db),
    user: dict = Depends(require_permission(Permission.PUSH_WRITE.value)),
    request: Request = None,
):
    try:
        flow = db.get(TransFlow, body.record_id)
        if flow is None:
            raise ValueError(f"流水不存在：{body.record_id}")
        require_flow_scope(user, db, flow.account_id, request=request)
        p = push_svc.push_record(
            db, record_id=body.record_id, pushed_by=user["username"], ip_address=_ip(request)
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return _push_dict(p)


@router.post("/batch")
def push_batch(
    body: PushBatchRequest,
    db: Session = Depends(get_db),
    user: dict = Depends(require_permission(Permission.PUSH_WRITE.value)),
    request: Request = None,
):
    batch = db.get(FlowBatch, body.batch_id)
    if batch is None:
        raise HTTPException(status_code=404, detail="批次不存在")
    require_flow_scope(user, db, batch.account_id, request=request)
    pushed = push_svc.push_batch(
        db, batch_id=body.batch_id, pushed_by=user["username"], ip_address=_ip(request)
    )
    return {"pushed": len(pushed), "items": [_push_dict(p) for p in pushed]}


def _ip(request):
    return request.client.host if request and request.client else None


def _push_dict(p) -> dict:
    return {
        "push_id": p.push_id,
        "record_id": p.record_id,
        "push_status": p.push_status,
        "voucher_no": p.voucher_no,
        "kingdee_doc_no": p.kingdee_doc_no,
        "error_msg": p.error_msg,
    }
