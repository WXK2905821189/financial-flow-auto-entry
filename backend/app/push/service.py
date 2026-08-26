"""金蝶推送 + 自动制证服务：复核通过后一键推送，回写凭证号（双向绑定）。"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.contract import ProcessStatus, PushStatus
from app.models import PushRecord, TransFlow
from app.core import audit as audit_svc
from app.push.kingdee import (
    KingdeeClient,
    KingdeeIndeterminateError,
    build_voucher_model,
    get_kingdee_client,
)


def push_record(
    db: Session,
    *,
    record_id: int,
    pushed_by: str,
    ip_address: str | None = None,
    client: KingdeeClient | None = None,
) -> PushRecord:
    flow = db.get(TransFlow, record_id)
    if flow is None:
        raise ValueError(f"流水不存在：{record_id}")
    existing = _find_push(db, record_id)
    if existing and existing.push_status == PushStatus.SUCCESS.value:
        return existing
    if existing and existing.push_status == PushStatus.UNCERTAIN.value:
        raise ValueError("该流水的金蝶结果尚未确认，请先查单后再处理，禁止自动重推")
    if existing and existing.push_status == PushStatus.PENDING.value:
        raise ValueError("该流水已有待确认的推送请求，请先确认金蝶侧结果")
    if flow.process_status != ProcessStatus.REVIEW_PASSED.value:
        raise ValueError(f"流水当前状态不可推送：{flow.process_status}")

    model = build_voucher_model(flow)
    request_hash = _request_hash(model)
    push = existing or PushRecord(record_id=record_id, batch_id=flow.batch_id, retry_count=0)
    if existing is None:
        db.add(push)
    else:
        push.retry_count += 1
    push.push_status = PushStatus.PENDING.value
    push.pushed_by = pushed_by
    push.pushed_at = datetime.now()
    push.error_msg = None
    push.response_payload = _request_payload(push, model, request_hash)

    try:
        db.flush()
        _append_push_audit(
            db,
            push=push,
            actor=pushed_by,
            action="PUSH_REQUEST",
            ip_address=ip_address,
            request_hash=request_hash,
        )
        # 先持久化本地推送意图。进程崩溃或请求超时后，下一次不会盲目重推。
        db.commit()
    except IntegrityError:
        db.rollback()
        concurrent = _find_push(db, record_id)
        if concurrent is not None:
            return concurrent
        raise
    db.refresh(push)

    try:
        resp = (client or get_kingdee_client()).push_voucher(flow, idempotency_key=request_hash)
        push.push_status = PushStatus.SUCCESS.value
        push.voucher_no = resp.get("voucher_no")
        push.kingdee_doc_no = resp.get("doc_no")
        _complete_payload(push, status=PushStatus.SUCCESS.value, response=resp)
        flow.process_status = ProcessStatus.KINGDEE_POSTED.value
    except KingdeeIndeterminateError as exc:
        push.push_status = PushStatus.UNCERTAIN.value
        push.error_msg = str(exc)[:1024]
        _complete_payload(push, status=PushStatus.UNCERTAIN.value, error=push.error_msg)
    except Exception as exc:  # noqa: BLE001  推送失败留痕便于重试
        push.push_status = PushStatus.FAILED.value
        push.error_msg = str(exc)[:1024]
        _complete_payload(push, status=PushStatus.FAILED.value, error=push.error_msg)

    _append_push_audit(
        db,
        push=push,
        actor=pushed_by,
        action="PUSH_RESULT",
        ip_address=ip_address,
        request_hash=request_hash,
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


def _find_push(db: Session, record_id: int) -> PushRecord | None:
    return db.execute(
        select(PushRecord).where(PushRecord.record_id == record_id).limit(1)
    ).scalar_one_or_none()


def _request_hash(model: dict) -> str:
    body = json.dumps(model, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def _request_payload(push: PushRecord, model: dict, request_hash: str) -> dict:
    payload = dict(push.response_payload or {})
    attempts = list(payload.get("attempts") or [])
    attempts.append({"number": push.retry_count + 1, "started_at": datetime.now().isoformat(timespec="seconds")})
    payload.update({"request_hash": request_hash, "voucher_model": model, "attempts": attempts})
    return payload


def _complete_payload(
    push: PushRecord,
    *,
    status: str,
    response: dict | None = None,
    error: str | None = None,
) -> None:
    payload = dict(push.response_payload or {})
    attempts = list(payload.get("attempts") or [])
    if attempts:
        attempts[-1] = {
            **attempts[-1],
            "completed_at": datetime.now().isoformat(timespec="seconds"),
            "status": status,
            **({"response": response} if response is not None else {}),
            **({"error": error} if error else {}),
        }
    payload["attempts"] = attempts
    payload["remote_status"] = (response or {}).get("remote_status", status)
    push.response_payload = payload


def _append_push_audit(
    db: Session,
    *,
    push: PushRecord,
    actor: str,
    action: str,
    ip_address: str | None,
    request_hash: str,
) -> None:
    audit_svc.append_audit(
        db,
        actor=actor,
        action=action,
        entity_type="push",
        entity_id=str(push.push_id),
        detail={
            "record_id": push.record_id,
            "request_hash": request_hash,
            "status": push.push_status,
            "voucher_no": push.voucher_no,
            "kingdee_doc_no": push.kingdee_doc_no,
            "remote_status": (push.response_payload or {}).get("remote_status"),
            "retry_count": push.retry_count,
        },
        ip_address=ip_address,
    )
