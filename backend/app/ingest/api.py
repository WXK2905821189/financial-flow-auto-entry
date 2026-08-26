"""采集入库接口：触发采集（Mock/文件/API）→ 批次落库。"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from sqlalchemy.orm import Session

from app.ingest.adapters import get_adapter
from app.core.deps import require_account_scope, require_permission
from app.core.contract import SourceType
from app.core.database import get_db
from app.core.permissions import Permission
from app.ingest import service as ingest_svc

router = APIRouter(prefix="/api/ingest", tags=["ingest"])


@router.post("/mock")
def ingest_mock(
    bank_code: str = "CITIC",
    account_no: str = "1100000000001",
    count: int = 50,
    begin_balance: Decimal | None = None,
    end_balance: Decimal | None = None,
    db: Session = Depends(get_db),
    user: dict = Depends(require_permission(Permission.INGEST_WRITE.value)),
    request: Request = None,
):
    require_account_scope(user, db, bank_code=bank_code, account_no=account_no, request=request)
    adapter = get_adapter(SourceType.MOCK)
    txns = adapter.fetch(bank_code=bank_code, account_no=account_no, count=count)
    summary = ingest_svc.ingest(
        db,
        transactions=txns,
        source_type=SourceType.MOCK,
        source_ref=f"mock://{bank_code}/{account_no}",
        imported_by=user["username"],
        ip_address=_ip(request),
        expected_begin_balance=begin_balance,
        expected_end_balance=end_balance,
    )
    return _summary_dict(summary)


@router.post("/api")
def ingest_api(
    bank_code: str = "CITIC",
    account_no: str = "",
    start_date: date | None = None,
    end_date: date | None = None,
    begin_balance: Decimal | None = None,
    end_balance: Decimal | None = None,
    db: Session = Depends(get_db),
    user: dict = Depends(require_permission(Permission.INGEST_WRITE.value)),
    request: Request = None,
):
    require_account_scope(user, db, bank_code=bank_code, account_no=account_no, request=request)
    adapter = get_adapter(SourceType.API)
    try:
        txns = adapter.fetch(
            bank_code=bank_code, account_no=account_no,
            start_date=start_date, end_date=end_date,
        )
    except Exception as exc:  # noqa: BLE001 银企远端异常统一转 400，便于调用方识别
        raise HTTPException(status_code=400, detail=f"银企采集失败：{exc}")
    summary = ingest_svc.ingest(
        db,
        transactions=txns,
        source_type=SourceType.API,
        source_ref=f"api://{bank_code}/{account_no}",
        imported_by=user["username"],
        ip_address=_ip(request),
        expected_begin_balance=begin_balance,
        expected_end_balance=end_balance,
    )
    return _summary_dict(summary)


@router.post("/file")
async def ingest_file(
    file: UploadFile = File(...),
    bank_code: str = Form("CITIC"),
    account_no: str = Form(""),
    begin_balance: Decimal | None = Form(None),
    end_balance: Decimal | None = Form(None),
    db: Session = Depends(get_db),
    user: dict = Depends(require_permission(Permission.INGEST_WRITE.value)),
    request: Request = None,
):
    require_account_scope(user, db, bank_code=bank_code, account_no=account_no, request=request)
    content = await file.read()
    adapter = get_adapter(SourceType.FILE)
    diagnostics: dict = {}
    try:
        txns = adapter.fetch(
            content=content, filename=file.filename, bank_code=bank_code, account_no=account_no,
            diagnostics=diagnostics,
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"文件解析失败：{exc}")
    summary = ingest_svc.ingest(
        db,
        transactions=txns,
        source_type=SourceType.FILE,
        source_ref=file.filename,
        imported_by=user["username"],
        ip_address=_ip(request),
        expected_begin_balance=begin_balance,
        expected_end_balance=end_balance,
    )
    payload = _summary_dict(summary)
    payload["skipped"] = diagnostics.get("skipped")
    return payload


def _summary_dict(summary) -> dict:
    return {
        "loaded": summary.loaded,
        "duplicated": summary.duplicated,
        "failed": summary.failed,
        "warned": summary.warned,
        "batches": [
            {"batch_id": b.batch_id, "batch_no": b.batch_no} for b in summary.batches
        ],
    }


def _ip(request):
    return request.client.host if request and request.client else None
