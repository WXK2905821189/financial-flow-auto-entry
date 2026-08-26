"""银企 API 采集联通测试：进程内拉起模拟银行服务，验证「HTTP采集→字段映射→落库」全链路。

用法：python test_api_adapter.py
覆盖：双银行全量拉取（翻页聚合）、单日过滤、账户错误、签名、契约映射、/api/ingest/api
      端到端落库（source_type=API 留痕）。
"""
from __future__ import annotations

import os
import pathlib
import sys
import tempfile
import threading
from contextlib import contextmanager
from datetime import date
from http.server import ThreadingHTTPServer

_here = pathlib.Path(__file__).resolve()
sys.path.insert(0, str(_here.parents[1]))
_bank_dir = _here.parents[2] / "data_engineering" / "mock_bank_api"
sys.path.insert(0, str(_bank_dir))

_tmp = pathlib.Path(tempfile.mkdtemp(prefix="wf_api_link_"))
os.environ["DATABASE_URL"] = f"sqlite:///{_tmp / 'api.db'}"
os.environ["JWT_SECRET"] = "test_secret"
os.environ["ENVIRONMENT"] = "test"

from sqlalchemy import select  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from mock_bank_api import Handler  # noqa: E402
from app.ingest.adapters import get_adapter  # noqa: E402
from app.core.config import settings  # noqa: E402
from app.core.contract import SourceType  # noqa: E402
from app.core.database import SessionLocal  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Bank, FlowBatch  # noqa: E402

_results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    _results.append((name, bool(ok), detail))
    print(("PASS" if ok else "FAIL"), name, detail)


@contextmanager
def serve():
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()


def run() -> None:
    with serve() as base:
        settings.bank_api_base_url = base
        adapter = get_adapter(SourceType.API)

        # ① 招商全量拉取（自动翻页）＋ 契映射
        cmb = adapter.fetch(bank_code="CMB", account_no="7559123456789012")
        check("api.cmb_pull", len(cmb) > 0, f"n={len(cmb)}")
        check("api.cmb_counterparty", any(t.counterparty_name for t in cmb), "对方户名已映射")
        check("api.cmb_summary", any(t.summary for t in cmb), "银行摘要已映射")
        check("api.cmb_bank", all(t.bank_code == "CMB" for t in cmb), "bank_code=CMB")

        # ② 中信全量拉取＋字段别名差异（对方账户名）
        citic = adapter.fetch(bank_code="CITIC", account_no="8110901234567890")
        check("api.citic_pull", len(citic) > 0, f"n={len(citic)}")
        check("api.citic_counterparty", any(t.counterparty_name for t in citic), "对方账户名已映射")

        # ③ 单日过滤（应 ≤ 全量）
        one = adapter.fetch(
            bank_code="CITIC", account_no="8110901234567890",
            start_date=date(2026, 8, 24), end_date=date(2026, 8, 24),
        )
        check("api.single_day", 0 < len(one) <= len(citic), f"n={len(one)}")

        # ④ 账号错误 → 明确报错
        try:
            adapter.fetch(bank_code="CITIC", account_no="9999999999999999")
            check("api.wrong_account", False)
        except ValueError:
            check("api.wrong_account", True)

        # ⑤ 端到端：/api/ingest/api → orchestrating落库
        with TestClient(app) as c:
            r = c.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
            check("api.e2e.login", r.status_code == 200, f"status={r.status_code}")
            h = {"X-CSRF-Token": c.cookies.get("wf_csrf", "")}
            r = c.post("/api/auth/password/change", json={"current_password": "admin123", "new_password": "AdminPass123!"}, headers=h)
            check("api.e2e.admin_password_changed", r.status_code == 200, f"status={r.status_code}")
            db = SessionLocal()
            try:
                bank_id = db.query(Bank).filter(Bank.bank_code == "CITIC").one().bank_id
            finally:
                db.close()
            r = c.post("/api/auth/users", json={"username": "operator", "display_name": "采集员", "password": "ValidPass123!", "role": "INGEST_OPERATOR", "scopes": [{"bank_id": bank_id}]}, headers=h)
            check("api.e2e.create_operator", r.status_code == 201, f"status={r.status_code}")

        with TestClient(app) as operator:
            operator.post("/api/auth/login", json={"username": "operator", "password": "ValidPass123!"})
            operator_h = {"X-CSRF-Token": operator.cookies.get("wf_csrf", "")}
            operator.post("/api/auth/password/change", json={"current_password": "ValidPass123!", "new_password": "OperatorPass123!"}, headers=operator_h)
            r = operator.post(
                "/api/ingest/api",
                params={"bank_code": "CITIC", "account_no": "8110901234567890"},
                headers=operator_h,
            )
            body = r.json()
            check("api.e2e.ingest", r.status_code == 200 and body.get("loaded", 0) > 0,
                  f"loaded={body.get('loaded')}")
            db = SessionLocal()
            try:
                types = set(
                    db.execute(
                        select(FlowBatch.source_type).where(FlowBatch.imported_by == "operator")
                    ).scalars()
                )
                check("api.e2e.source_type", "API" in types, f"source_types={sorted(types)}")
            finally:
                db.close()

    total = len(_results)
    failed = sum(1 for _, ok, _ in _results if not ok)
    print(f"\nTOTAL {total}   FAILED {failed}")
    raise SystemExit(1 if failed else 0)


if __name__ == "__main__":
    run()
