"""校验服务：R001–R005 单笔规则 + R006 批次余额勾稽。"""
from __future__ import annotations

from decimal import Decimal

from app.config import settings
from app.contract import BankTransaction, ValidationStatus

# ISO4217 合法币种（一期最小集，可扩展）
_VALID_CURRENCIES = {"CNY", "USD", "HKD", "EUR", "GBP", "JPY"}


class RuleResult:
    def __init__(self, rule_code: str, result: str, detail: str | None = None):
        self.rule_code = rule_code
        self.result = result  # PASS / FAIL / WARN
        self.detail = detail


def validate_transaction(txn: BankTransaction) -> list[RuleResult]:
    results: list[RuleResult] = []

    # R002 负金额 / 方向非法
    if txn.amount <= 0:
        results.append(RuleResult("R002", "FAIL", f"金额非正：{txn.amount}"))
    elif txn.dc_flag.value not in ("D", "C"):
        results.append(RuleResult("R002", "FAIL", f"方向非法：{txn.dc_flag.value}"))
    else:
        results.append(RuleResult("R002", "PASS"))

    # R003 必填字段缺失
    missing = _missing_fields(txn)
    if missing:
        results.append(RuleResult("R003", "FAIL", f"必填字段缺失：{','.join(missing)}"))
    else:
        results.append(RuleResult("R003", "PASS"))

    # R004 单笔金额超阈值（WARN → 人工复核）
    if txn.amount > settings.review_amount_threshold:
        results.append(RuleResult("R004", "WARN", f"金额 {txn.amount} 超阈值 {settings.review_amount_threshold}"))
    else:
        results.append(RuleResult("R004", "PASS"))

    # R005 币种非法
    if txn.currency.upper() not in _VALID_CURRENCIES:
        results.append(RuleResult("R005", "FAIL", f"币种非法：{txn.currency}"))
    else:
        results.append(RuleResult("R005", "PASS"))

    return results


def _missing_fields(txn: BankTransaction) -> list[str]:
    missing = []
    if not txn.txn_no:
        missing.append("txn_no")
    if txn.txn_date is None:
        missing.append("txn_date")
    if txn.amount is None:
        missing.append("amount")
    if not txn.counterparty_name:
        missing.append("counterparty_name")
    if not txn.account_no:
        missing.append("account_no")
    return missing


def summarize(results: list[RuleResult]) -> tuple[ValidationStatus, list[str]]:
    codes = []
    has_fail = False
    has_warn = False
    for r in results:
        if r.result == "FAIL":
            has_fail = True
            codes.append(r.rule_code)
        elif r.result == "WARN":
            has_warn = True
            codes.append(r.rule_code)
    if has_fail:
        return ValidationStatus.FAIL, codes
    if has_warn:
        return ValidationStatus.WARN, codes
    return ValidationStatus.PASS, codes


def check_batch_balance(
    begin_balance: Decimal,
    end_balance: Decimal,
    txns: list[BankTransaction],
    *,
    tolerance: Decimal = Decimal("0.01"),
) -> RuleResult:
    """批次级余额勾稽（R006）：期初 + Σ收入 − Σ支出 ≈ 期末。"""
    credit = sum((t.amount for t in txns if t.dc_flag.value == "C"), Decimal("0"))
    debit = sum((t.amount for t in txns if t.dc_flag.value == "D"), Decimal("0"))
    expected_delta = end_balance - begin_balance
    actual_delta = credit - debit
    diff = expected_delta - actual_delta
    if abs(diff) <= tolerance:
        return RuleResult("R006", "PASS", f"期初{begin_balance} 期末{end_balance} 勾稽一致")
    return RuleResult("R006", "FAIL", f"批次勾稽不平衡：期初+收支≠期末，差异 {diff}")
