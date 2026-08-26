"""系统对接状态查询（只读）：银行/金蝶/数据库当前对接情况，供财务侧在 UAT 前核对。

安全约束：仅返回 base_url、布尔状态与掩码信息，绝不回传任何密钥/凭据
（含 bank_api_sign_secret、KINGDEE_APP_SECRET、JWT），且不将配置写入数据库。
"""
from __future__ import annotations

import re
from datetime import datetime

from fastapi import APIRouter, Depends
from sqlalchemy import text

from app.core.deps import require_permission
from app.core.config import settings
from app.core.database import SessionLocal
from app.core.permissions import Permission

router = APIRouter(prefix="/api/settings", tags=["settings"])


def _db_info() -> dict:
    url = settings.database_url
    if url.startswith("sqlite"):
        kind = "sqlite"
        display = "SQLite 演示库（waterflow.db）"
    else:
        m = re.match(r".*?://[^:/@]+@([^:/]+):(\d+)/([^?]+)", url)
        kind = "mysql"
        display = f"MySQL · {m.group(1)}:{m.group(2)}/{m.group(3)}" if m else url
    ok = False
    try:
        sess = SessionLocal()
        sess.execute(text("SELECT 1"))
        sess.close()
        ok = True
    except Exception:  # noqa: BLE001 仅探测联通性
        pass
    return {"kind": kind, "display": display, "ok": ok,
            "status": "连接正常" if ok else "连接异常",
            "badge": "b-pass" if ok else "b-err"}


def _bank_check() -> dict:
    from app.ingest.adapters.api_adapter import MockBankApiAdapter

    url = settings.bank_api_base_url
    signed = bool(settings.bank_api_sign_secret)
    label = "银企直连（模拟 mock_bank_api）" if "127.0.0.1:8080" in url else "银企直连（真实/内网地址）"
    reachable = False
    try:
        MockBankApiAdapter(base_url=url)._check_health()
        reachable = True
    except Exception:  # noqa: BLE001 服务未启/欠费/连不通
        pass
    status = "服务可达 · 可采集" if reachable else ("已配置 · 服务未就绪" if signed else "未配置对接")
    badge = "b-pass" if reachable else ("b-wait" if signed else "b-err")
    return {"mode": "API", "label": label, "base_url": url,
            "signed": signed, "reachable": reachable,
            "status": status, "badge": badge}


def _kingdee_check() -> dict:
    has_real = all(
        [settings.kingdee_base_url, settings.kingdee_app_id,
         settings.kingdee_app_secret, settings.kingdee_acct_id]
    )
    mode = "MOCK" if settings.kingdee_mock_enabled else ("REAL" if has_real else "UNCONFIGURED")
    status = {
        "MOCK": "Mock 推送（凭据未就绪）",
        "REAL": "真实 OpenAPI 已配置",
        "UNCONFIGURED": "未配置且未开 Mock",
    }[mode]
    badge = {"MOCK": "b-wait", "REAL": "b-pass", "UNCONFIGURED": "b-err"}[mode]
    return {"mode": mode, "label": "金蝶云星空 OpenAPI",
            "base_url": settings.kingdee_base_url or "—",
            "mock_enabled": settings.kingdee_mock_enabled,
            "configured": has_real, "status": status, "badge": badge}


@router.get("/status")
def status(user: dict = Depends(require_permission(Permission.SETTINGS_READ.value))):
    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "environment": settings.environment,
        "bank": _bank_check(),
        "kingdee": _kingdee_check(),
        "database": _db_info(),
        "rules": {
            "review_amount_threshold": float(settings.review_amount_threshold),
            "auto_pass_enabled": settings.auto_pass_enabled,
        },
    }
