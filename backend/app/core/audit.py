"""审计留痕服务：只追加 + 哈希链防篡改（对应 aud_audit_log）。"""
from __future__ import annotations

import hashlib
import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AuditLog


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _serialize(detail: dict | None) -> str:
    return json.dumps(detail, ensure_ascii=False, sort_keys=True, default=str) if detail else ""


def append_audit(
    db: Session,
    *,
    actor: str,
    action: str,
    entity_type: str,
    entity_id: str,
    detail: dict | None = None,
    ip_address: str | None = None,
) -> AuditLog:
    """追加一条审计日志，计算哈希链（本行内容 + 前一行 row_hash）。"""
    prev = db.execute(select(AuditLog).order_by(AuditLog.log_id.desc()).limit(1)).scalar_one_or_none()
    prev_hash = prev.row_hash if prev else None
    row_hash = _sha256(
        f"{prev_hash or ''}|{actor}|{action}|{entity_type}|{entity_id}|{_serialize(detail)}"
    )
    log = AuditLog(
        actor=actor,
        action=action,
        entity_type=entity_type,
        entity_id=str(entity_id),
        detail=detail,
        ip_address=ip_address,
        row_hash=row_hash,
        prev_hash=prev_hash,
    )
    db.add(log)
    return log


def verify_chain(db: Session) -> tuple[bool, int]:
    """回放校验哈希链是否完整，返回 (是否完整, 校验行数)。"""
    rows = db.execute(select(AuditLog).order_by(AuditLog.log_id.asc())).scalars().all()
    prev = None
    for r in rows:
        expect = _sha256(
            f"{prev or ''}|{r.actor}|{r.action}|{r.entity_type}|{r.entity_id}|{_serialize(r.detail)}"
        )
        if r.row_hash != expect:
            return False, len(rows)
        prev = r.row_hash
    return True, len(rows)