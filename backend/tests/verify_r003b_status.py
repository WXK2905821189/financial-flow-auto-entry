"""验证 A1/A2 端到端：
- A1（R003b）：对方户名缺失 → WARN 降级 → 进复核队列 REVIEW_READY（而非被拒）
- A2（状态机）：校验 FAIL → process_status = LOADED（先落库留痕），不再置 REJECTED

运行：python verify_r003b_status.py
"""
from __future__ import annotations

import os
import pathlib
import sys
import tempfile
from datetime import date
from decimal import Decimal

_here = pathlib.Path(__file__).resolve()
sys.path.insert(0, str(_here.parents[1]))

_tmp = pathlib.Path(tempfile.mkdtemp(prefix="wf_r003b_"))
os.environ["DATABASE_URL"] = f"sqlite:///{_tmp / 'v.db'}"
os.environ["JWT_SECRET"] = "t"
os.environ["ENVIRONMENT"] = "test"

from app.core.contract import BankTransaction, Direction, SourceType  # noqa: E402
from app.core.database import Base, SessionLocal, engine  # noqa: E402
from app.models import TransFlow  # noqa: E402
from app.services import ingest as ingest_svc  # noqa: E402
from app.services import review as review_svc  # noqa: E402
from app.core.seed import ensure_seed  # noqa: E402

_fails: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    if ok:
        print("PASS", name, detail)
    else:
        _fails.append(name)
        print("FAIL", name, detail)


def txn(no: str, **kw) -> BankTransaction:
    base = dict(
        bank_code="CITIC",
        account_no="1100000000001",
        txn_no=no,
        txn_date=date(2026, 8, 20),
        currency="CNY",
        amount=Decimal("100.00"),
        dc_flag=Direction.DEBIT,
        counterparty_name="某某公司",
        counterparty_account="123",
        summary="往来款",
    )
    base.update(kw)
    return BankTransaction(**base)


def main() -> None:
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    ensure_seed(db)

    no_name = txn("T-A11", amount=Decimal("100.00"), counterparty_name=None)  # → R003b WARN
    bad_no = txn("", amount=Decimal("50.00"))  # 缺流水号 → R003 FAIL
    ok = txn("T-A13", amount=Decimal("888.00"))  # 正常

    s = ingest_svc.ingest(db, transactions=[no_name, bad_no, ok], source_type=SourceType.MOCK)
    db.commit()

    flow: dict[str, TransFlow] = {t.txn_no: t for t in db.query(TransFlow).all()}
    pending = [f.txn_no for f in review_svc.list_pending(db)]

    # ── A1：无户名 → REVIEW_READY，进复核队列 ──
    x = flow["T-A11"]
    check("R003b.status", x.process_status == "REVIEW_READY", f"got={x.process_status}")
    check("R003b.validation", x.validation_status == "WARN", f"got={x.validation_status}")
    check("R003b.excep", "R003b" in (x.exception_type or ""), f"got={x.exception_type}")
    check("R003b.in_pending", "T-A11" in pending, f"pending={pending}")

    # ── A2：校验 FAIL → LOADED，不进复核队列 ──
    y = flow[""]
    check("A2.status", y.process_status == "LOADED", f"got={y.process_status}")
    check("A2.validation", y.validation_status == "FAIL", f"got={y.validation_status}")
    check("A2.not_rejected", y.process_status != "REJECTED", f"got={y.process_status}")
    check("A2.excep", "R003" in (y.exception_type or ""), f"got={y.exception_type}")
    check("A2.not_in_pending", "" not in pending, f"pending={pending}")

    # ── 批次统计回流 ──
    check("batch.failed==1", s.failed == 1, f"got={s.failed}")
    check("batch.warned==1", s.warned == 1, f"got={s.warned}")

    # ── A3 职责边界说明：正常单不入队（auto_pass 看板通） ──
    z = flow["T-A13"]
    check("ok.status", z.process_status in ("REVIEW_PASSED", "REVIEW_READY"), f"got={z.process_status}")

    print("\nRESULT:", "ALL PASS" if not _fails else f"FAILED: {_fails}")
    sys.exit(0 if not _fails else 3)


if __name__ == "__main__":
    main()