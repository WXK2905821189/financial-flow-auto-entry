from __future__ import annotations

from decimal import Decimal

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from sqlalchemy.orm import Session

from app.adapters import get_adapter
from app.api.deps import get_current_user
from app.contract import SourceType
from app.database import get_db
from app.services import ingest as ingest_svc

router = APIRouter(prefix="/api/ingest", tags=["ingest"])


@router.post("/mock")
def ingest_mock(
    bank_code: str = "CITIC",
    account_no: str = "1100000000001",
    count: int = 50,
    begin_balance: Decimal | None = None,
    end_balance: Decimal | None = None,
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
    request: Request = None,
):
    adapter = get_adapter(SourceType.MOCK)
    txns = adapter.fetch(bank_code=bank_code, account_no=account_no, count=count)
    summary = ingest_svc.ingest(
        db, transactions=txns, source_type=SourceType.MOCK,
        source_ref=f"mock://{bank_code}/{account_no}", imported_by=user["username"],
        ip_address=_ip(request), expected_begin_balance=begin_balance, expected_end_balance=end_balance,
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
    user: dict = Depends(get_current_user),
    request: Request = None,
):
    content = await file.read()
    adapter = get_adapter(SourceType.FILE)
    try:
        txns = adapter.fetch(content=content, filename=file.filename, bank_code=bank_code, account_no=account_no)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"文件解析失败：{exc}")
    summary = ingest_svc.ingest(
        db, transactions=txns, source_type=SourceType.FILE, source_ref=file.filename,
        imported_by=user["username"], ip_address=_ip(request),
        expected_begin_balance=begin_balance, expected_end_balance=end_balance,
    )
    return _summary_dict(summary)


def _summary_dict(summary) -> dict:
    return {
        "loaded": summary.loaded, "duplicated": summary.duplicated,
        "failed": summary.failed, "warned": summary.warned,
        "batches": [{"batch_id": b.batch_id, "batch_no": b.batch_no} for b in summary.batches],
    }


def _ip(request):
    return request.client.host if request and request.client else None
