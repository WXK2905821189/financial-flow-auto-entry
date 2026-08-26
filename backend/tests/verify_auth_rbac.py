"""认证与授权回归：Cookie 会话、CSRF、五角色、范围、撤销与最后管理员保护。"""
from __future__ import annotations

import os
import pathlib
import sys
import tempfile

_here = pathlib.Path(__file__).resolve()
sys.path.insert(0, str(_here.parents[1]))

_tmp = pathlib.Path(tempfile.mkdtemp(prefix="wf_auth_rbac_"))
os.environ["DATABASE_URL"] = f"sqlite:///{_tmp / 'auth.db'}"
os.environ["JWT_SECRET"] = "auth_rbac_test_secret"
os.environ["ENVIRONMENT"] = "test"

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

_results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    _results.append((name, bool(ok), detail))
    print(("PASS" if ok else "FAIL"), name, detail)


def csrf(client: TestClient) -> dict[str, str]:
    return {"X-CSRF-Token": client.cookies.get("wf_csrf", "")}


def login(client: TestClient, username: str, password: str) -> dict:
    response = client.post("/api/auth/login", json={"username": username, "password": password})
    check(f"login.{username}", response.status_code == 200, f"status={response.status_code}")
    return response.json() if response.status_code == 200 else {}


def run() -> None:
    with TestClient(app) as admin:
        login_response = admin.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
        check("login.admin", login_response.status_code == 200, f"status={login_response.status_code}")
        admin_session = login_response.json() if login_response.status_code == 200 else {}
        set_cookies = login_response.headers.get_list("set-cookie")
        check(
            "auth.http_only_cookies",
            any("wf_access=" in item and "HttpOnly" in item for item in set_cookies)
            and any("wf_refresh=" in item and "HttpOnly" in item for item in set_cookies),
        )
        check("auth.me", admin.get("/api/auth/me").status_code == 200)

        changed = admin.post(
            "/api/auth/password/change",
            json={"current_password": "admin123", "new_password": "AdminPass123!"},
            headers=csrf(admin),
        )
        check("auth.initial_password_change", changed.status_code == 200, f"status={changed.status_code}")

        refreshed = admin.post("/api/auth/refresh", headers=csrf(admin))
        check(
            "auth.refresh_rotates",
            refreshed.status_code == 200 and refreshed.json().get("session_id") != admin_session.get("session_id"),
            f"status={refreshed.status_code}",
        )

        no_csrf = admin.post("/api/auth/users", json={})
        check("auth.csrf_required", no_csrf.status_code == 403, f"status={no_csrf.status_code}")

        admin_business = admin.get("/api/dashboard/summary")
        check("rbac.admin_denied_business", admin_business.status_code == 403, f"status={admin_business.status_code}")

        users = admin.get("/api/auth/users").json()["items"]
        admin_id = next(item["user_id"] for item in users if item["username"] == "admin")
        from app.core.database import SessionLocal
        from app.models import Bank, RolePermission

        db = SessionLocal()
        try:
            bank = db.query(Bank).filter(Bank.bank_code == "CITIC").one()
            bank_id = bank.bank_id
            seeded_roles = set(db.query(RolePermission.role).all())
            admin_business_permissions = db.query(RolePermission).filter(
                RolePermission.role == "SYSTEM_ADMIN",
                RolePermission.permission_code == "review:read",
            ).count()
        finally:
            db.close()

        check(
            "rbac.permission_matrix_seeded",
            {"SYSTEM_ADMIN", "FINANCE_MANAGER", "REVIEWER", "INGEST_OPERATOR", "AUDITOR"}.issubset(
                {role for (role,) in seeded_roles}
            ),
        )
        check(
            "rbac.admin_governance_only",
            admin_business_permissions == 0,
        )

        for role, username in [
            ("FINANCE_MANAGER", "manager"),
            ("REVIEWER", "reviewer"),
            ("INGEST_OPERATOR", "operator"),
            ("AUDITOR", "auditor"),
        ]:
            response = admin.post(
                "/api/auth/users",
                json={
                    "username": username,
                    "display_name": username,
                    "password": "ValidPass123!",
                    "role": role,
                    "scopes": [{"bank_id": bank_id}],
                },
                headers=csrf(admin),
            )
            check(f"rbac.create_{role.lower()}", response.status_code == 201, f"status={response.status_code}")

        locked_user = admin.post(
            "/api/auth/users",
            json={"username": "locked", "display_name": "locked", "password": "ValidPass123!", "role": "AUDITOR", "scopes": [{"bank_id": bank_id}]},
            headers=csrf(admin),
        )
        check("auth.create_locked_user", locked_user.status_code == 201, f"status={locked_user.status_code}")
        for _ in range(5):
            admin.post("/api/auth/login", json={"username": "locked", "password": "wrong-password"})
        locked_login = admin.post("/api/auth/login", json={"username": "locked", "password": "ValidPass123!"})
        check("auth.login_lockout", locked_login.status_code == 401, f"status={locked_login.status_code}")

        reset = admin.post(
            f"/api/auth/users/{locked_user.json().get('user_id')}/password/reset",
            json={"new_password": "ResetPass123!"},
            headers=csrf(admin),
        )
        check("auth.admin_reset_password", reset.status_code == 200, f"status={reset.status_code}")
        with TestClient(app) as reset_user:
            reset_login = reset_user.post("/api/auth/login", json={"username": "locked", "password": "ResetPass123!"})
            check("auth.reset_requires_change", reset_login.status_code == 200 and reset_login.json().get("must_change_password") is True, f"status={reset_login.status_code}")

        last_admin = admin.patch(f"/api/auth/users/{admin_id}", json={"role": "REVIEWER"}, headers=csrf(admin))
        check("rbac.last_admin_protected", last_admin.status_code == 400, f"status={last_admin.status_code}")

        with TestClient(app) as reviewer:
            login(reviewer, "reviewer", "ValidPass123!")
            initial_denied = reviewer.get("/api/review/pending")
            check("auth.initial_password_required", initial_denied.status_code == 403, f"status={initial_denied.status_code}")
            changed = reviewer.post(
                "/api/auth/password/change",
                json={"current_password": "ValidPass123!", "new_password": "ReviewerPass123!"},
                headers=csrf(reviewer),
            )
            check("auth.reviewer_password_changed", changed.status_code == 200, f"status={changed.status_code}")
            denied = reviewer.post("/api/ingest/mock", params={"bank_code": "CITIC", "account_no": "1100000000001"}, headers=csrf(reviewer))
            check("rbac.reviewer_denied_ingest", denied.status_code == 403, f"status={denied.status_code}")
            allowed = reviewer.get("/api/review/pending")
            check("rbac.reviewer_allowed_review", allowed.status_code == 200, f"status={allowed.status_code}")

        with TestClient(app) as operator:
            login(operator, "operator", "ValidPass123!")
            changed = operator.post(
                "/api/auth/password/change",
                json={"current_password": "ValidPass123!", "new_password": "OperatorPass123!"},
                headers=csrf(operator),
            )
            check("auth.operator_password_changed", changed.status_code == 200, f"status={changed.status_code}")
            denied = operator.post("/api/ingest/mock", params={"bank_code": "CMB", "account_no": "not-granted"}, headers=csrf(operator))
            check("scope.operator_denied_other_bank", denied.status_code == 403, f"status={denied.status_code}")
            loaded = operator.post("/api/ingest/mock", params={"bank_code": "CITIC", "account_no": "1100000000001", "count": 8}, headers=csrf(operator))
            check("scope.operator_allowed_granted_bank", loaded.status_code == 200, f"status={loaded.status_code}")

        with TestClient(app) as auditor:
            login(auditor, "auditor", "ValidPass123!")
            changed = auditor.post(
                "/api/auth/password/change",
                json={"current_password": "ValidPass123!", "new_password": "AuditorPass123!"},
                headers=csrf(auditor),
            )
            check("auth.auditor_password_changed", changed.status_code == 200, f"status={changed.status_code}")
            flows = auditor.get("/api/review/pending")
            sample = flows.json()[0] if flows.status_code == 200 and flows.json() else {}
            check(
                "pii.auditor_masked",
                flows.status_code == 200
                and sample.get("counterparty_name", "").endswith("**")
                and "*" in sample.get("counterparty_account", ""),
                f"status={flows.status_code}",
            )
            trace = auditor.get("/api/trace/by-record", params={"record_id": sample.get("record_id")}) if sample else None
            check("pii.auditor_raw_hidden", trace is not None and trace.status_code == 200 and trace.json().get("raw", {}).get("raw_content") is None, f"status={trace.status_code if trace else 'none'}")

        before = admin.get("/api/auth/me")
        revoke = admin.post("/api/auth/sessions/revoke-all", headers=csrf(admin))
        after = admin.get("/api/auth/me")
        check("session.revoke_other_devices", before.status_code == 200 and revoke.status_code == 200 and after.status_code == 200 and revoke.json().get("current_session_kept") is True, f"before={before.status_code} revoke={revoke.status_code} after={after.status_code}")

        from app.models import AuditLog
        db = SessionLocal()
        try:
            denied_audit = db.query(AuditLog).filter(AuditLog.action == "ACCESS_DENIED").count()
        finally:
            db.close()
        check("audit.denied_access_logged", denied_audit >= 2, f"count={denied_audit}")

    failed = [item for item in _results if not item[1]]
    print(f"TOTAL {len(_results)} FAILED {len(failed)}")
    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    run()
