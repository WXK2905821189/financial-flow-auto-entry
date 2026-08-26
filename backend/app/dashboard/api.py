"""四看板取数接口（MVP，取数与展示解耦，口径对齐 v_* 视图）。

不依赖数据库视图，直接以 ORM 聚合复现视图语义：
流水总览 / 银行分布 / 异常预警 / 对账钩稽。
"""
from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends
from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.core.deps import account_scope_clause, require_permission
from app.core.database import get_db
from app.core.permissions import Permission
from app.core.pii import mask_name
from app.models import Bank, BankAccount, FlowBatch, FlowReview, FlowValidation, PushRecord, TransFlow

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


@router.get("/summary")
def summary(db: Session = Depends(get_db), user: dict = Depends(require_permission(Permission.DASHBOARD_READ.value))):
    """复核工作台顶部四卡口径：待复核 / 今日已复核 / 今日已推送 / 自动通过率。"""
    today = date.today()
    flow_scope = account_scope_clause(TransFlow.account_id, user, db)
    pending = db.execute(
        select(func.count()).select_from(TransFlow).where(TransFlow.process_status == "REVIEW_READY", flow_scope)
    ).scalar_one()
    today_reviewed = db.execute(
        select(func.count()).select_from(FlowReview).join(TransFlow, TransFlow.record_id == FlowReview.record_id).where(FlowReview.review_time >= today, flow_scope)
    ).scalar_one()
    today_pushed = db.execute(
        select(func.count())
        .select_from(PushRecord)
        .join(TransFlow, TransFlow.record_id == PushRecord.record_id)
        .where(PushRecord.push_status == "SUCCESS", PushRecord.pushed_at >= today, flow_scope)
    ).scalar_one()
    passed_total = db.execute(
        select(func.count())
        .select_from(TransFlow)
        .where(TransFlow.process_status.in_(["REVIEW_PASSED", "KINGDEE_POSTED", "PUSHED"]), flow_scope)
    ).scalar_one()
    auto_passed = db.execute(
        select(func.count())
        .select_from(TransFlow)
        .where(
            TransFlow.process_status.in_(["REVIEW_PASSED", "KINGDEE_POSTED"]),
            TransFlow.validation_status == "PASS", flow_scope,
        )
    ).scalar_one()
    return {
        "pending_review": int(pending),
        "today_reviewed": int(today_reviewed),
        "today_pushed": int(today_pushed),
        "passed_total": int(passed_total),
        "auto_passed": int(auto_passed),
        "auto_pass_rate": round(auto_passed / passed_total, 4) if passed_total else 0,
    }


@router.get("/overview")
def overview(db: Session = Depends(get_db), user: dict = Depends(require_permission(Permission.DASHBOARD_READ.value))):
    rows = db.execute(
        select(
            TransFlow.txn_date,
            Bank.bank_name,
            BankAccount.account_name,
            TransFlow.dc_flag,
            func.count().label("cnt"),
            func.round(func.sum(TransFlow.amount), 2).label("amt"),
        )
        .join(Bank, Bank.bank_id == TransFlow.bank_id)
        .join(BankAccount, BankAccount.account_id == TransFlow.account_id)
        .where(account_scope_clause(TransFlow.account_id, user, db))
        .group_by(TransFlow.txn_date, Bank.bank_name, BankAccount.account_name, TransFlow.dc_flag)
        .order_by(TransFlow.txn_date)
    ).all()
    return [
        {
            "txn_date": r.txn_date.isoformat() if isinstance(r.txn_date, date) else str(r.txn_date),
            "bank_name": r.bank_name,
            "account_name": r.account_name if user.get("can_read_pii") else mask_name(r.account_name),
            "dc_flag": r.dc_flag,
            "cnt": r.cnt,
            "amount": str(r.amt or 0),
        }
        for r in rows
    ]


@router.get("/bank-distribution")
def bank_distribution(db: Session = Depends(get_db), user: dict = Depends(require_permission(Permission.DASHBOARD_READ.value))):
    rows = db.execute(
        select(
            Bank.bank_name,
            BankAccount.account_name,
            func.count().label("cnt"),
            func.round(func.sum(case((TransFlow.dc_flag == "C", TransFlow.amount), else_=0)), 2).label("credit_amount"),
            func.round(func.sum(case((TransFlow.dc_flag == "D", TransFlow.amount), else_=0)), 2).label("debit_amount"),
        )
        .join(Bank, Bank.bank_id == TransFlow.bank_id)
        .join(BankAccount, BankAccount.account_id == TransFlow.account_id)
        .where(account_scope_clause(TransFlow.account_id, user, db))
        .group_by(Bank.bank_name, BankAccount.account_name)
    ).all()
    return [
        {
            "bank_name": r.bank_name,
            "account_name": r.account_name if user.get("can_read_pii") else mask_name(r.account_name),
            "cnt": r.cnt,
            "credit_amount": str(r.credit_amount or 0),
            "debit_amount": str(r.debit_amount or 0),
        }
        for r in rows
    ]


@router.get("/exceptions")
def exceptions(
    limit: int = 200,
    db: Session = Depends(get_db),
    user: dict = Depends(require_permission(Permission.DASHBOARD_READ.value)),
):
    rows = db.execute(
        select(
            TransFlow.record_id,
            TransFlow.batch_id,
            TransFlow.txn_no,
            TransFlow.txn_date,
            TransFlow.amount,
            TransFlow.dc_flag,
            TransFlow.counterparty_name,
            FlowValidation.rule_code,
            FlowValidation.rule_result,
            FlowValidation.error_detail,
        )
        .join(FlowValidation, FlowValidation.record_id == TransFlow.record_id)
        .where(FlowValidation.rule_result.in_(["FAIL", "WARN"]), account_scope_clause(TransFlow.account_id, user, db))
        .order_by(TransFlow.txn_date.desc())
        .limit(limit)
    ).all()
    out = [
        {
            "record_id": r.record_id,
            "batch_id": r.batch_id,
            "batch_level": False,
            "txn_no": r.txn_no,
            "txn_date": r.txn_date.isoformat() if isinstance(r.txn_date, date) else str(r.txn_date),
            "amount": str(r.amount),
            "dc_flag": r.dc_flag,
            "counterparty_name": r.counterparty_name if user.get("can_read_pii") else mask_name(r.counterparty_name),
            "rule_code": r.rule_code,
            "rule_result": r.rule_result,
            "error_detail": r.error_detail,
        }
        for r in rows
    ]
    batch_rows = db.execute(
        select(
            FlowValidation.batch_id,
            FlowValidation.rule_code,
            FlowValidation.rule_result,
            FlowValidation.error_detail,
            FlowBatch.batch_no,
            FlowBatch.flow_date_end,
        )
        .join(FlowBatch, FlowBatch.batch_id == FlowValidation.batch_id)
        .where(
            FlowValidation.record_id == 0,
            FlowValidation.rule_result.in_(["FAIL", "WARN"]),
            account_scope_clause(FlowBatch.account_id, user, db),
        )
        .order_by(FlowBatch.batch_id.desc())
        .limit(limit)
    ).all()
    batch_out = [
        {
            "record_id": None,
            "batch_id": r.batch_id,
            "batch_level": True,
            "txn_no": r.batch_no,
            "txn_date": r.flow_date_end.isoformat() if isinstance(r.flow_date_end, date) else "—",
            "amount": "0",
            "dc_flag": None,
            "counterparty_name": "整批",
            "rule_code": r.rule_code,
            "rule_result": r.rule_result,
            "error_detail": r.error_detail,
        }
        for r in batch_rows
    ]
    return out[: max(0, limit - len(batch_out))] + batch_out[:limit]


@router.get("/recon")
def recon(db: Session = Depends(get_db), user: dict = Depends(require_permission(Permission.DASHBOARD_READ.value))):
    loaded_subq = (
        select(
            TransFlow.batch_id,
            func.round(func.sum(TransFlow.amount), 2).label("loaded_amount"),
        )
        .where(account_scope_clause(TransFlow.account_id, user, db))
        .group_by(TransFlow.batch_id)
        .subquery()
    )
    rows = db.execute(
        select(
            FlowBatch.batch_id,
            FlowBatch.batch_no,
            FlowBatch.source_type,
            FlowBatch.source_ref,
            FlowBatch.total_count,
            FlowBatch.total_amount,
            FlowBatch.loaded_count,
            FlowBatch.duplicated_count,
            FlowBatch.failed_count,
            FlowBatch.warned_count,
            func.coalesce(loaded_subq.c.loaded_amount, 0).label("loaded_amount"),
        )
        .outerjoin(loaded_subq, loaded_subq.c.batch_id == FlowBatch.batch_id)
        .where(account_scope_clause(FlowBatch.account_id, user, db))
        .order_by(FlowBatch.batch_id.desc())
    ).all()
    out = []
    for r in rows:
        expected_count = int(r.total_count)
        loaded_count = int(r.loaded_count)
        out.append(
            {
                "batch_id": r.batch_id,
                "batch_no": r.batch_no,
                "source_type": r.source_type,
                "source_ref": r.source_ref,
                "expected_count": expected_count,
                "loaded_count": loaded_count,
                "duplicated_count": int(r.duplicated_count),
                "failed_count": int(r.failed_count),
                "warned_count": int(r.warned_count),
                "count_diff": expected_count - loaded_count,
                "expected_amount": str(r.total_amount),
                "loaded_amount": str(r.loaded_amount or 0),
            }
        )
    return out
