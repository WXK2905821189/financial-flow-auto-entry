"""端到端冒烟测试：用 SQLite 覆盖数据库，验证「登录→采集→复核→推送→溯源→看板」链路。

用法：python smoke_test.py
主键类型 BIGINT_PK 已针对 sqlite 降级为 INTEGER，故本脚本无需 MySQL。
"""
from __future__ import annotations

import os
import pathlib
import sys
import tempfile

_here = pathlib.Path(__file__).resolve()
sys.path.insert(0, str(_here.parents[1]))

_tmp = pathlib.Path(tempfile.mkdtemp(prefix="wf_smoke_"))
os.environ["DATABASE_URL"] = f"sqlite:///{_tmp / 'smoke.db'}"
os.environ["JWT_SECRET"] = "smoke_test_secret"
os.environ["ENVIRONMENT"] = "test"  # 关闭 SQLAlchemy echo，便于读结果

from fastapi.testclient import TestClient  # noqa: E402

from app.core.database import SessionLocal  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Bank  # noqa: E402

_results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    _results.append((name, bool(ok), detail))
    print(("PASS" if ok else "FAIL"), name, detail)


def run() -> None:
    with TestClient(app) as c:
        # 0. 静态资源（内网 Web 复核台）
        r = c.get("/")
        check("static.index", r.status_code == 200 and "复核工作台" in r.text, f"status={r.status_code}")
        for p in ["/css/app.css", "/js/main.js", "/js/review.js", "/js/dashboards.js", "/js/trace.js", "/js/ui.js", "/js/api.js"]:
            r = c.get(p)
            check(f"static.{p.split('/')[-1]}", r.status_code == 200, f"status={r.status_code}")

        # 1. 登录
        r = c.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
        check("auth.login", r.status_code == 200, f"status={r.status_code}")
        assert r.status_code == 200, r.text
        h = {"X-CSRF-Token": c.cookies.get("wf_csrf", "")}
        r = c.get("/api/auth/me")
        check("auth.me", r.status_code == 200 and r.json().get("must_change_password") is True, f"status={r.status_code}")
        r = c.post("/api/auth/password/change", json={"current_password": "admin123", "new_password": "AdminPass123!"}, headers=h)
        check("auth.initial_password_change", r.status_code == 200, f"status={r.status_code}")

        # 2. 未带 token 应 401
        with TestClient(app) as anonymous:
            r = anonymous.get("/api/review/pending")
        check("auth.deny_unauthed", r.status_code == 401, f"status={r.status_code}")

        db = SessionLocal()
        try:
            bank_id = db.query(Bank).filter(Bank.bank_code == "CITIC").one().bank_id
        finally:
            db.close()
        for username, display_name, role in [
            ("operator", "采集员", "INGEST_OPERATOR"),
            ("reviewer", "复核员", "REVIEWER"),
            ("manager", "财务主管", "FINANCE_MANAGER"),
        ]:
            r = c.post("/api/auth/users", json={"username": username, "display_name": display_name, "password": "ValidPass123!", "role": role, "scopes": [{"bank_id": bank_id}]}, headers=h)
            check(f"auth.create_{username}", r.status_code == 201, f"status={r.status_code}")

        # 3. 采集员采集
        with TestClient(app) as operator:
            operator.post("/api/auth/login", json={"username": "operator", "password": "ValidPass123!"})
            operator_h = {"X-CSRF-Token": operator.cookies.get("wf_csrf", "")}
            operator.post("/api/auth/password/change", json={"current_password": "ValidPass123!", "new_password": "OperatorPass123!"}, headers=operator_h)
            r = operator.post("/api/ingest/mock", params={"bank_code": "CITIC", "account_no": "1100000000001", "count": 60}, headers=operator_h)
        check("ingest.mock", r.status_code == 200, f"loaded={r.json().get('loaded')}")
        assert r.status_code == 200, r.text

        with TestClient(app) as reviewer:
            reviewer.post("/api/auth/login", json={"username": "reviewer", "password": "ValidPass123!"})
            reviewer_h = {"X-CSRF-Token": reviewer.cookies.get("wf_csrf", "")}
            reviewer.post("/api/auth/password/change", json={"current_password": "ValidPass123!", "new_password": "ReviewerPass123!"}, headers=reviewer_h)
            r = reviewer.get("/api/review/pending")
            check("review.pending", r.status_code == 200, f"pending={len(r.json())}")
            pending = r.json()
            if pending:
                rid = pending[0]["record_id"]
                r = reviewer.post("/api/review/decide", json={"record_id": rid, "result": "ADJUST", "matched_subject": "6603"}, headers=reviewer_h)
                check("review.decide", r.status_code == 200, f"rid={rid} -> {r.json().get('result')}")
            else:
                rid = None
                check("review.pending_has_item", False, "待复核为空，Mock 阈值分布可能未触发")
            r = reviewer.get("/api/trace/by-record", params={"record_id": rid}) if rid else None

            # 6. 复核员可读取业务看板与溯源
            if rid:
                check("trace.by_record", r.status_code == 200, f"pushes={len(r.json().get('pushes', []))}")
            for ep, label in [("summary", "summary"), ("overview", "rows"), ("bank-distribution", "rows"), ("exceptions", "rows"), ("recon", "rows")]:
                r = reviewer.get(f"/api/dashboard/{ep}")
                check(f"dashboard.{ep}", r.status_code == 200, f"{label}={len(r.json()) if isinstance(r.json(), list) else 'ok'}")

        if rid:
            with TestClient(app) as manager:
                manager.post("/api/auth/login", json={"username": "manager", "password": "ValidPass123!"})
                manager_h = {"X-CSRF-Token": manager.cookies.get("wf_csrf", "")}
                manager.post("/api/auth/password/change", json={"current_password": "ValidPass123!", "new_password": "ManagerPass123!"}, headers=manager_h)
                r = manager.post("/api/push/record", json={"record_id": rid}, headers=manager_h)
                check("push.record", r.status_code == 200, f"status={r.json().get('push_status')}" if r.status_code == 200 else r.text)

    failed = [s for s in _results if not s[1]]
    print("=" * 60)
    print(f"TOTAL {len(_results)}   FAILED {len(failed)}")
    for name, _, detail in failed:
        print("  X", name, detail)
    if failed:
        sys.exit(1)
    print("SMOKE TEST OK")


if __name__ == "__main__":
    run()
