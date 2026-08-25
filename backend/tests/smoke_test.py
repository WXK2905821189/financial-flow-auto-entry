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

from app.main import app  # noqa: E402

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
        token = r.json()["access_token"]
        h = {"Authorization": f"Bearer {token}"}

        # 2. 未带 token 应 401
        r = c.get("/api/review/pending")
        check("auth.deny_unauthed", r.status_code == 401, f"status={r.status_code}")

        # 3. Mock 采集
        r = c.post("/api/ingest/mock", params={"bank_code": "CITIC", "account_no": "1100000000001", "count": 60}, headers=h)
        check("ingest.mock", r.status_code == 200, f"loaded={r.json().get('loaded')}")
        assert r.status_code == 200, r.text

        # 4. 待复核列表
        r = c.get("/api/review/pending", headers=h)
        check("review.pending", r.status_code == 200, f"pending={len(r.json())}")
        pending = r.json()

        # 5. 单笔复核通过 + 推送 + 双向溯源
        if pending:
            rid = pending[0]["record_id"]
            r = c.post("/api/review/decide", json={"record_id": rid, "result": "PASS"}, headers=h)
            check("review.decide", r.status_code == 200, f"rid={rid} -> {r.json().get('result')}")

            r = c.post("/api/push/record", json={"record_id": rid}, headers=h)
            check("push.record", r.status_code == 200, f"status={r.json().get('push_status')}" if r.status_code == 200 else r.text)
            voucher = r.json().get("voucher_no") if r.status_code == 200 else None

            r = c.get("/api/trace/by-record", params={"record_id": rid}, headers=h)
            check("trace.by_record", r.status_code == 200, f"pushes={len(r.json().get('pushes', []))}")

            if voucher:
                r = c.get("/api/trace/by-voucher", params={"voucher_no": voucher}, headers=h)
                check("trace.by_voucher", r.status_code == 200, f"rid={r.json().get('flow', {}).get('record_id')}")
        else:
            check("review.pending_has_item", False, "待复核为空，Mock 阈值分布可能未触发")

        # 6. 统计卡
        r = c.get("/api/dashboard/summary", headers=h)
        check("dashboard.summary", r.status_code == 200, f"pending={r.json().get('pending_review')} auto_rate={r.json().get('auto_pass_rate')}")

        # 7. 四看板
        for ep, label in [("overview", "rows"), ("bank-distribution", "rows"), ("exceptions", "rows"), ("recon", "rows")]:
            r = c.get(f"/api/dashboard/{ep}", headers=h)
            check(f"dashboard.{ep}", r.status_code == 200, f"{label}={len(r.json())}")

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