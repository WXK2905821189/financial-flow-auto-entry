"""金蝶推送 + 自动制证服务：复核通过后一键推送，回写凭证号（双向绑定）。"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.contract import ProcessStatus, PushStatus
from app.models import PushRecord, TransFlow
from app.core import audit as audit_svc
from app.services.kingdee import get_kingdee_client


def push_record(
    db: Session,
    *,
    record_id: int,
    pushed_by: str,
    ip_address: str | None = None,
) -> PushRecord:
    flow = db.get(TransFlow, record_id)
    if flow is None:
        raise ValueError(f"流水不存在：{record_id}")
    if flow.process_status != ProcessStatus.REVIEW_PASSED.value:
        raise ValueError(f"流水当前状态不可推送：{flow.process_status}")

    push = PushRecord(
        record_id=record_id,
        batch_id=flow.batch_id,
        push_status=PushStatus.PENDING.value,
        pushed_by=pushed_by,
        pushed_at=datetime.now(),
        retry_count=0,
    )
    db.add(push)
    db.flush()

    try:
        resp = get_kingdee_client().push_voucher(flow)
        push.push_status = PushStatus.SUCCESS.value
        push.voucher_no = resp.get("voucher_no")
        push.kingdee_doc_no = resp.get("doc_no")
        push.response_payload = resp
        flow.process_status = ProcessStatus.KINGDEE_POSTED.value
    except Exception as exc:  # noqa: BLE001  推送失败留痕便于重试
        push.push_status = PushStatus.FAILED.value
        push.error_msg = str(exc)[:1024]
        push.retry_count += 1

    audit_svc.append_audit(
        db,
        actor=pushed_by,
        action="PUSH",
        entity_type="record",
        entity_id=str(record_id),
        detail={"voucher_no": push.voucher_no, "status": push.push_status},
        ip_address=ip_address,
    )
    db.commit()
    db.refresh(push)
    return push


def push_batch(
    db: Session,
    *,
    batch_id: int,
    pushed_by: str,
    ip_address: str | None = None,
) -> list[PushRecord]:
    flows = db.execute(
        select(TransFlow).where(
            TransFlow.batch_id == batch_id,
            TransFlow.process_status == ProcessStatus.REVIEW_PASSED.value,
        )
    ).scalars().all()
    pushed = []
    for f in flows:
        pushed.append(
            push_record(db, record_id=f.record_id, pushed_by=pushed_by, ip_address=ip_address)
        )
    return pushed