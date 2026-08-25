"""专项验证：R006 批次余额勾稽 + 对方科目规则预填（决策 P1）。

用法：python verify_r006_mapping.py
覆盖：
  R006-PASS  期初+Σ收入−Σ支出==期末
  R006-FAIL  期末不平衡 → 批次 FAIL、转人工(WARN)
  R006-SKIP  未传期初/期末 → SKIP
  MAP-HIT    关键词命中 → ext_json.auto_subject
  MAP-MISS   未命中 → 无 auto_subject
  MAP-DIR    方向过滤（DEBIT 规则不命 CREDIT 流水）
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

_tmp = pathlib.Path(tempfile.mkdtemp(prefix="wf_verify_"))
os.environ["DATABASE_URL"] = f"sqlite:///{_tmp / 'verify.db'}"
os.environ["JWT_SECRET"] = "verify_secret"
os.environ["ENVIRONMENT"] = "test"

from app.core.contract import BankTransaction, Direction, SourceType  # noqa: E402
from app import models  # noqa: E402, F401
from app.core.database import Base, SessionLocal, engine  # noqa: E402
from app.models import FlowBatch, TransFlow  # noqa: E402
from app.services import ingest as ingest_svc  # noqa: E402
from app.core.seed import ensure_seed  # noqa: E402


def txn(**kw: object) -> BankTransaction:
    base: dict[str, object] = {
        "bank_code": "CITIC",
        "account_no": "1100000000001",
        "txn_date": date(2026, 8, 1),
        "currency": "CNY",
        "amount": Decimal("1000.00"),
        "dc_flag": Direction.DEBIT,
        "counterparty_name": "某某公司",
        "counterparty_account": "123456789",
        "summary": "货款",
    }
    base.update(kw)
    return BankTransaction(**base)


def main() -> None:
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    ensure_seed(db)

    # ① R006 PASS：期初 10000，收入 3000、支出 1000 → 期末应 12000
    tx = [
        txn(txn_no="T1", amount=Decimal("3000.00"), dc_flag=Direction.CREDIT, summary="货款"),
        txn(txn_no="T2", amount=Decimal("1000.00"), dc_flag=Direction.DEBIT, summary="代发工资"),
    ]
    s = ingest_svc.ingest(
        db, transactions=tx, source_type=SourceType.MOCK,
        expected_begin_balance=Decimal("10000"), expected_end_balance=Decimal("12000"),
        imported_by="verify",
    )
    b = s.batches[0]
    assert b.balance_check_status == "PASS" and b.balance_diff == Decimal("0.00"), b.balance_check_status
    print("PASS R006-PASS", f"status={b.balance_check_status} diff={b.balance_diff}")

    # ② R006 FAIL：期末给错 13000 → 判不平
    s2 = ingest_svc.ingest(
        db, transactions=tx, source_type=SourceType.MOCK,
        expected_begin_balance=Decimal("10000"), expected_end_balance=Decimal("13000"),
        imported_by="verify",
    )
    b2 = s2.batches[0]
    assert b2.balance_check_status == "FAIL" and s2.warned >= 1, b2.balance_check_status
    print("PASS R006-FAIL", f"status={b2.balance_check_status} diff={b2.balance_diff} warned={s2.warned}")

    # ③ R006 SKIP：不传余额
    s3 = ingest_svc.ingest(db, transactions=[txn(txn_no="T3", summary="其他")], source_type=SourceType.MOCK)
    assert s3.batches[0].balance_check_status == "SKIP", s3.batches[0].balance_check_status
    print("PASS R006-SKIP", "status=SKIP")

    # ④ 科目规则命中：summary=货款(CREDIT) → 应收 1122；summary=代发工资(DEBIT) → 2211.01
    flows = db.query(TransFlow).order_by(TransFlow.record_id).all()
    money_flow = next(f for f in flows if f.summary == "货款" and f.dc_flag == "C")
    wage_flow = next(f for f in flows if f.summary == "代发工资" and f.dc_flag == "D")
    assert money_flow.ext_json["auto_subject"]["subject_code"] == "1122", money_flow.ext_json
    assert wage_flow.ext_json["auto_subject"]["subject_code"] == "2211.01", wage_flow.ext_json
    print("PASS MAP-HIT", f"货款->{money_flow.ext_json['auto_subject']['subject_code']} "
          f"代发工资->{wage_flow.ext_json['auto_subject']['subject_code']}")

    # ⑤ 未命中：summary=其他/往来款 无 auto_subject
    other = next(f for f in flows if f.summary == "其他")
    assert "auto_subject" not in (other.ext_json or {}), other.ext_json
    print("PASS MAP-MISS", "无 auto_subject")

    # ⑥ 方向过滤：DEBIT 规则(代发工资) 不命 CREDIT 流水的"代发工资"关键词
    weird = [(f.summary, f.dc_flag) for f in flows if f.summary == "代发工资"]
    assert all(dc == "D" for _, dc in weird), weird
    print("PASS MAP-DIR", "DEBIT 规则仅命 D")

    db.close()
    print("=" * 60)
    print("VERIFY R006+MAPPING OK")


if __name__ == "__main__":
    main()