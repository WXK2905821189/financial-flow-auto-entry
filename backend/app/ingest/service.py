"""数据中台入库服务：批次落库 + 原始归档 + 去重(R001) + 校验留痕 + 审计。

流程：适配器输出 List[BankTransaction] → 按 (银行, 账户) 分组各建批次 →
      逐笔：归档 raw → 去重 → 落 dwd_trans_flow → 校验(R002–R005) → 写留痕
      → 回写批次状态与预期/实际口径。
"""
from __future__ import annotations

import hashlib
import json
import secrets
from datetime import datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.contract import (
    BankTransaction,
    BatchStatus,
    ProcessStatus,
    SourceType,
    ValidationStatus,
)
from app.models import Bank, BankAccount, BankRawFlow, FlowBatch, FlowValidation, TransFlow
from app.ingest import mapper as mapper_svc
from app.core import audit as audit_svc
from app.ingest import validation as validation_svc


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _gen_batch_no(bank_code: str) -> str:
    now = datetime.now()
    return f"B{now:%Y%m%d}-{now:%H%M%S}-{bank_code}{secrets.token_hex(2).upper()}"


class IngestSummary:
    def __init__(self) -> None:
        self.batches: list[FlowBatch] = []
        self.loaded = 0
        self.duplicated = 0
        self.failed = 0
        self.warned = 0


def ingest(
    db: Session,
    *,
    transactions: list[BankTransaction],
    source_type: SourceType,
    source_ref: str | None = None,
    imported_by: str | None = None,
    ip_address: str | None = None,
    expected_begin_balance: Decimal | None = None,
    expected_end_balance: Decimal | None = None,
) -> IngestSummary:
    if not transactions:
        raise ValueError("无流水数据可入库")

    summary = IngestSummary()
    groups: dict[tuple[str, str], list[BankTransaction]] = {}
    for t in transactions:
        groups.setdefault((t.bank_code, t.account_no), []).append(t)

    for (bank_code, account_no), txns in groups.items():
        _ingest_group(
            db,
            txns,
            bank_code=bank_code,
            account_no=account_no,
            source_type=source_type,
            source_ref=source_ref,
            imported_by=imported_by,
            ip_address=ip_address,
            summary=summary,
            expected_begin_balance=expected_begin_balance,
            expected_end_balance=expected_end_balance,
        )
    db.commit()
    return summary


def _ingest_group(
    db: Session,
    txns: list[BankTransaction],
    *,
    bank_code: str,
    account_no: str,
    source_type: SourceType,
    source_ref: str | None,
    imported_by: str | None,
    ip_address: str | None,
    summary: IngestSummary,
    expected_begin_balance: Decimal | None,
    expected_end_balance: Decimal | None,
) -> None:
    bank = _resolve_bank(db, bank_code)
    account = _resolve_account(db, bank, account_no)

    batch = FlowBatch(
        batch_no=_gen_batch_no(bank_code),
        source_type=source_type.value,
        bank_id=bank.bank_id,
        account_id=account.account_id,
        source_ref=source_ref,
        contract_version=txns[0].contract_version,
        flow_date_start=min(t.txn_date for t in txns),
        flow_date_end=max(t.txn_date for t in txns),
        total_count=len(txns),
        total_amount=sum((t.amount for t in txns), Decimal("0")),
        expected_begin_balance=expected_begin_balance,
        expected_end_balance=expected_end_balance,
        status=BatchStatus.IMPORTING.value,
        imported_by=imported_by,
        imported_at=datetime.now(),
    )
    db.add(batch)
    db.flush()  # 取得 batch_id

    seen: set[str] = set()
    loaded = duplicated = failed = warned = 0
    for txn in txns:
        raw_content = json.loads(txn.model_dump_json())
        raw_hash = _sha256(txn.model_dump_json())
        raw = BankRawFlow(
            batch_id=batch.batch_id,
            source_file_name=source_ref,
            source_uri=source_ref,
            raw_content=raw_content,
            raw_hash=raw_hash,
        )
        db.add(raw)
        db.flush()

        # R001 去重（批内 + 历史）
        dedup_key = _sha256(txn.dedup_seed(bank.bank_id, account.account_id))
        if dedup_key in seen:
            duplicated += 1
            continue
        exists = db.execute(
            select(TransFlow.record_id).where(TransFlow.dedup_key == dedup_key).limit(1)
        ).scalar_one_or_none()
        if exists:
            seen.add(dedup_key)
            duplicated += 1
            continue
        seen.add(dedup_key)

        flow = TransFlow(
            dedup_key=dedup_key,
            batch_id=batch.batch_id,
            bank_id=bank.bank_id,
            account_id=account.account_id,
            raw_id=raw.raw_id,
            contract_version=txn.contract_version,
            txn_no=txn.txn_no,
            txn_date=txn.txn_date,
            txn_time=txn.txn_time,
            currency=txn.currency.upper(),
            amount=txn.amount,
            dc_flag=txn.dc_flag.value,
            counterparty_name=txn.counterparty_name,
            counterparty_account=txn.counterparty_account,
            summary=txn.summary,
            process_status=ProcessStatus.LOADED.value,
            validation_status=ValidationStatus.PENDING.value,
            ext_json=txn.ext,
        )
        db.add(flow)
        db.flush()

        # 对方科目规则预填（决策 P1：规则命中自动预填）
        try:
            mapper_svc.prefill(flow=flow, txn=txn, db=db)
        except Exception:  # noqa: BLE001 规则异常不影响采集主流程
            pass

        # 校验 R002–R005 + 留痕
        rule_results = validation_svc.validate_transaction(txn)
        val_status, codes = validation_svc.summarize(rule_results)
        flow.validation_status = val_status.value
        flow.exception_type = ",".join(codes) if codes else None
        for rr in rule_results:
            db.add(
                FlowValidation(
                    record_id=flow.record_id,
                    batch_id=batch.batch_id,
                    rule_code=rr.rule_code,
                    rule_result=rr.result,
                    error_detail=rr.detail,
                )
            )

        # A2 状态机口径：校验 FAIL 先落库留痕置 LOADED（不置 REJECTED），
        # 失败语义由 validation_status=FAIL + FlowValidation 承载；REJECTED 仅留给人工驳回。
        if val_status == ValidationStatus.FAIL:
            flow.process_status = ProcessStatus.LOADED.value
            failed += 1
        elif val_status == ValidationStatus.WARN:
            flow.process_status = ProcessStatus.REVIEW_READY.value
            warned += 1
        else:
            flow.process_status = (
                ProcessStatus.REVIEW_PASSED.value
                if settings.auto_pass_enabled
                else ProcessStatus.REVIEW_READY.value
            )
        loaded += 1

    # 批次级余额勾稽（R006）：仅当银行报表提供期初/期末余额时执行
    batch.status = BatchStatus.LOADED.value
    if expected_begin_balance is not None and expected_end_balance is not None:
        rr = validation_svc.check_batch_balance(
            expected_begin_balance, expected_end_balance, txns
        )
        batch.balance_check_status = rr.result
        credit = sum((t.amount for t in txns if t.dc_flag.value == "C"), Decimal("0"))
        debit = sum((t.amount for t in txns if t.dc_flag.value == "D"), Decimal("0"))
        batch.balance_diff = Decimal(
            f"{(expected_end_balance - expected_begin_balance - (credit - debit)):.2f}"
        )
        if rr.result == "FAIL":
            warned += 1
        db.add(
            FlowValidation(
                record_id=0,
                batch_id=batch.batch_id,
                rule_code=rr.rule_code,
                rule_result=rr.result,
                error_detail=rr.detail,
            )
        )

    # 统计回流：批次级 loaded/duplicated/failed/warned 显性落库，对接 v_recon_balance 对账口径
    batch.loaded_count = loaded
    batch.duplicated_count = duplicated
    batch.failed_count = failed
    batch.warned_count = warned
    summary.loaded += loaded
    summary.duplicated += duplicated
    summary.failed += failed
    summary.warned += warned

    summary.batches.append(batch)
    audit_svc.append_audit(
        db,
        actor=imported_by or "system",
        action="IMPORT",
        entity_type="batch",
        entity_id=str(batch.batch_id),
        detail={
            "batch_no": batch.batch_no,
            "source_type": source_type.value,
            "total": len(txns),
            "loaded": loaded,
            "duplicated": duplicated,
            "failed": failed,
            "warned": warned,
            "balance_check": batch.balance_check_status,
        },
        ip_address=ip_address,
    )


def _resolve_bank(db: Session, bank_code: str) -> Bank:
    bank = db.execute(select(Bank).where(Bank.bank_code == bank_code)).scalar_one_or_none()
    if bank is None:
        raise ValueError(f"银行编码未配置：{bank_code}")
    return bank


def _resolve_account(db: Session, bank: Bank, account_no: str) -> BankAccount:
    acct = db.execute(
        select(BankAccount).where(
            BankAccount.bank_id == bank.bank_id, BankAccount.account_no == account_no
        )
    ).scalar_one_or_none()
    if acct is None:
        acct = BankAccount(
            bank_id=bank.bank_id,
            account_no=account_no,
            account_name=account_no,
            default_currency="CNY",
            is_active=True,
        )
        db.add(acct)
        db.flush()
    return acct