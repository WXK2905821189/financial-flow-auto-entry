"""复核、制证与金蝶客户端边界专项验证。

用法：python verify_review_push.py
覆盖：复核状态门禁、规则/人工科目传递、单记录幂等、网络中断不重推、
      金蝶成功/失败响应解析及审计哈希链。
"""
from __future__ import annotations

import json
import os
import pathlib
import sys
import tempfile
from datetime import date
from decimal import Decimal

_here = pathlib.Path(__file__).resolve()
sys.path.insert(0, str(_here.parents[1]))

_tmp = pathlib.Path(tempfile.mkdtemp(prefix="wf_review_push_"))
os.environ["DATABASE_URL"] = f"sqlite:///{_tmp / 'review_push.db'}"
os.environ["JWT_SECRET"] = "review_push_test_secret"
os.environ["ENVIRONMENT"] = "test"

from sqlalchemy import select  # noqa: E402
from sqlalchemy.exc import IntegrityError  # noqa: E402

from app.core import audit as audit_svc  # noqa: E402
from app.core.contract import (  # noqa: E402
    APPROVED_SUBJECT_KEY,
    AUTO_SUBJECT_KEY,
    ProcessStatus,
    PushStatus,
    ReviewResult,
)
from app.core.database import Base, SessionLocal, engine  # noqa: E402
from app.models import Bank, BankAccount, FlowBatch, PushRecord, TransFlow  # noqa: E402
from app.push import service as push_svc  # noqa: E402
from app.push.kingdee import (  # noqa: E402
    KingdeeClient,
    KingdeeIndeterminateError,
    OpenApiKingdeeClient,
    build_voucher_model,
)
from app.review import service as review_svc  # noqa: E402

_fails: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print("PASS" if ok else "FAIL", name, detail)
    if not ok:
        _fails.append(name)


def make_flow(
    db,
    *,
    txn_no: str,
    status: str = ProcessStatus.REVIEW_READY.value,
    ext_json: dict | None = None,
) -> TransFlow:
    bank = db.execute(select(Bank).where(Bank.bank_code == "TEST")).scalar_one_or_none()
    if bank is None:
        bank = Bank(bank_code="TEST", bank_name="测试银行")
        db.add(bank)
        db.flush()
    account = db.execute(
        select(BankAccount).where(BankAccount.bank_id == bank.bank_id)
    ).scalar_one_or_none()
    if account is None:
        account = BankAccount(bank_id=bank.bank_id, account_no="10001", account_name="测试账户")
        db.add(account)
        db.flush()
    batch = FlowBatch(
        batch_no=f"B-{txn_no}",
        source_type="MOCK",
        bank_id=bank.bank_id,
        account_id=account.account_id,
    )
    db.add(batch)
    db.flush()
    flow = TransFlow(
        dedup_key=f"dedup-{txn_no}",
        batch_id=batch.batch_id,
        bank_id=bank.bank_id,
        account_id=account.account_id,
        txn_no=txn_no,
        txn_date=date(2026, 8, 26),
        currency="CNY",
        amount=Decimal("100.00"),
        dc_flag="C",
        counterparty_name="测试客户",
        summary="测试货款",
        process_status=status,
        validation_status="WARN",
        ext_json=ext_json,
    )
    db.add(flow)
    db.commit()
    db.refresh(flow)
    return flow


class SuccessClient(KingdeeClient):
    def __init__(self) -> None:
        self.calls = 0
        self.keys: list[str] = []

    def push_voucher(self, flow: TransFlow, *, idempotency_key: str) -> dict:
        self.calls += 1
        self.keys.append(idempotency_key)
        return {
            "voucher_no": f"KD-{flow.record_id}",
            "doc_no": f"DOC-{flow.record_id}",
            "remote_status": "SAVED",
            "mock": False,
        }


class UncertainClient(KingdeeClient):
    def __init__(self) -> None:
        self.calls = 0

    def push_voucher(self, flow: TransFlow, *, idempotency_key: str) -> dict:
        self.calls += 1
        raise KingdeeIndeterminateError("simulated connection reset")


class RetryClient(KingdeeClient):
    def __init__(self) -> None:
        self.calls = 0

    def push_voucher(self, flow: TransFlow, *, idempotency_key: str) -> dict:
        self.calls += 1
        if self.calls == 1:
            raise RuntimeError("simulated business failure")
        return {
            "voucher_no": f"KD-RETRY-{flow.record_id}",
            "doc_no": f"DOC-RETRY-{flow.record_id}",
            "remote_status": "SAVED",
            "mock": False,
        }


def main() -> None:
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        # ① REVIEW_READY 才允许复核；规则科目被固化为已确认科目并进入制证报文。
        ruled = make_flow(
            db,
            txn_no="RULE-1",
            ext_json={AUTO_SUBJECT_KEY: {"subject_code": "1122", "subject_name": "应收账款"}},
        )
        review_svc.review_record(db, record_id=ruled.record_id, result=ReviewResult.PASS, reviewer="tester")
        db.refresh(ruled)
        check("review.rule_subject", ruled.ext_json[APPROVED_SUBJECT_KEY]["subject_code"] == "1122")
        check("voucher.rule_subject", build_voucher_model(ruled)["FEntity"][1]["FAccountID"]["FNumber"] == "1122")
        try:
            review_svc.review_record(db, record_id=ruled.record_id, result=ReviewResult.PASS, reviewer="tester")
            check("review.status_gate", False)
        except ValueError:
            check("review.status_gate", True)

        # ② 未命中规则必须人工调整；人工编码进入报文。
        manual = make_flow(db, txn_no="MANUAL-1")
        try:
            review_svc.review_record(db, record_id=manual.record_id, result=ReviewResult.PASS, reviewer="tester")
            check("review.subject_required", False)
        except ValueError:
            check("review.subject_required", True)
        review_svc.review_record(
            db,
            record_id=manual.record_id,
            result=ReviewResult.ADJUST,
            matched_subject="6603",
            reviewer="tester",
        )
        db.refresh(manual)
        check("review.manual_subject", manual.ext_json[APPROVED_SUBJECT_KEY]["source"] == "MANUAL")
        check("voucher.manual_subject", build_voucher_model(manual)["FEntity"][1]["FAccountID"]["FNumber"] == "6603")

        # ③ 同一流水重复请求只调用一次外部客户端，并保留同一推送记录和请求指纹。
        client = SuccessClient()
        first = push_svc.push_record(db, record_id=ruled.record_id, pushed_by="tester", client=client)
        second = push_svc.push_record(db, record_id=ruled.record_id, pushed_by="tester", client=client)
        pushes = db.execute(select(PushRecord).where(PushRecord.record_id == ruled.record_id)).scalars().all()
        check("push.idempotent_call", client.calls == 1, f"calls={client.calls}")
        check("push.single_record", len(pushes) == 1 and first.push_id == second.push_id, f"records={len(pushes)}")
        check("push.request_hash", len(client.keys) == 1 and len(client.keys[0]) == 64)
        try:
            db.add(PushRecord(record_id=ruled.record_id, batch_id=ruled.batch_id))
            db.commit()
            check("push.unique_record", False)
        except IntegrityError:
            db.rollback()
            check("push.unique_record", True)

        # ④ 明确业务失败可复用同一条记录重试；网络中断则必须人工查单。
        retry_flow = make_flow(
            db,
            txn_no="RETRY-1",
            status=ProcessStatus.REVIEW_PASSED.value,
            ext_json={APPROVED_SUBJECT_KEY: {"subject_code": "2202", "source": "MANUAL"}},
        )
        retry_client = RetryClient()
        failed = push_svc.push_record(db, record_id=retry_flow.record_id, pushed_by="tester", client=retry_client)
        retried = push_svc.push_record(db, record_id=retry_flow.record_id, pushed_by="tester", client=retry_client)
        check("push.retry_same_record", failed.push_id == retried.push_id and retry_client.calls == 2)
        check("push.retry_success", retried.push_status == PushStatus.SUCCESS.value and retried.retry_count == 1)
        check("push.retry_attempts", len((retried.response_payload or {}).get("attempts", [])) == 2)

        uncertain_flow = make_flow(
            db,
            txn_no="UNCERTAIN-1",
            status=ProcessStatus.REVIEW_PASSED.value,
            ext_json={APPROVED_SUBJECT_KEY: {"subject_code": "2202", "source": "MANUAL"}},
        )
        uncertain_client = UncertainClient()
        uncertain = push_svc.push_record(
            db, record_id=uncertain_flow.record_id, pushed_by="tester", client=uncertain_client
        )
        check("push.uncertain_status", uncertain.push_status == PushStatus.UNCERTAIN.value)
        try:
            push_svc.push_record(db, record_id=uncertain_flow.record_id, pushed_by="tester", client=uncertain_client)
            check("push.uncertain_no_retry", False)
        except ValueError:
            check("push.uncertain_no_retry", uncertain_client.calls == 1, f"calls={uncertain_client.calls}")

        # ⑤ 金蝶响应解析与审计链均可离线验证。
        response = json.dumps({"Result": {"ResponseStatus": {"IsSuccess": True}, "Number": "PZ-1", "Id": "1"}})
        parsed = OpenApiKingdeeClient._parse_save_response(response, ruled)
        check("kingdee.parse_success", parsed["voucher_no"] == "PZ-1" and parsed["remote_status"] == "SAVED")
        try:
            OpenApiKingdeeClient._parse_save_response(
                json.dumps({"Result": {"ResponseStatus": {"IsSuccess": False, "Errors": [{"Message": "bad"}]}}}),
                ruled,
            )
            check("kingdee.parse_failure", False)
        except RuntimeError:
            check("kingdee.parse_failure", True)
        valid, count = audit_svc.verify_chain(db)
        check("push.audit_chain", valid and count >= 4, f"rows={count}")
    finally:
        db.close()

    print("RESULT:", "ALL PASS" if not _fails else f"FAILED: {_fails}")
    raise SystemExit(0 if not _fails else 3)


if __name__ == "__main__":
    main()
