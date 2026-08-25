"""流水校验服务：实现 R001–R005 规则（可扩展规则钩子）。

R001 重复流水由 dedup_key 唯一索引天然支撑（入库时判重），R002–R005
在本服务逐笔执行。规则字典见 dim_validation_rule（种子数据见 services/seed.py）。
"""
from __future__ import annotations

from decimal import Decimal

from app.core.config import settings
from app.core.contract import BankTransaction, ValidationStatus

# ISO4217 合法币种（一期最小集，可扩展）
_VALID_CURRENCIES = {"CNY", "USD", "HKD", "EUR", "GBP", "JPY"}


class RuleResult:
    def __init__(self, rule_code: str, result: str, detail: str | None = None):
        self.rule_code = rule_code
        self.result = result  # PASS / FAIL / WARN
        self.detail = detail


def validate_transaction(txn: BankTransaction) -> list[RuleResult]:
    """对单笔流水执行 R002–R005，返回逐规则命中结果。"""
    results: list[RuleResult] = []

    # R002 负金额 / 方向非法
    if txn.amount <= 0:
        results.append(RuleResult("R002", "FAIL", f"金额非正：{txn.amount}"))
    elif txn.dc_flag.value not in ("D", "C"):
        results.append(RuleResult("R002", "FAIL", f"方向非法：{txn.dc_flag.value}"))
    else:
        results.append(RuleResult("R002", "PASS"))

    # R003 必填字段缺失（不含对方户名，对方户名单独走 R003b 降级 WARN）
    missing = _missing_fields(txn)
    if missing:
        results.append(RuleResult("R003", "FAIL", f"必填字段缺失：{','.join(missing)}"))
    else:
        results.append(RuleResult("R003", "PASS"))

    # R003b 对方户名缺失 → WARN（财务 P3：手续费/利息等无户名账单降级，转人工复核而非拒绝）
    if not txn.counterparty_name:
        results.append(RuleResult("R003b", "WARN", "对方户名缺失（降级，转人工复核）"))
    else:
        results.append(RuleResult("R003b", "PASS"))

    # R004 单笔金额超阈值（WARN → 人工复核）
    if txn.amount > settings.review_amount_threshold:
        results.append(
            RuleResult(
                "R004",
                "WARN",
                f"金额 {txn.amount} 超阈值 {settings.review_amount_threshold}",
            )
        )
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
    if not txn.account_no:
        missing.append("account_no")
    return missing


def summarize(results: list[RuleResult]) -> tuple[ValidationStatus, list[str]]:
    """由逐规则结果汇总整体校验结论与异常类型列表。"""
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
    """批次级余额勾稽（规则 R006）：期初 + Σ收入 − Σ支出 ≈ 期末。

    对应 bsp 的 Golden Rule。方向口径：dc_flag 为 C(收入/贷方) 增加余额，
    D(支出/借方) 减少余额，故期末 − 期初 应等于 Σ(收入) − Σ(支出)。
    仅在银行报表提供期初/期末余额时启用；无余额则上层置 SKIP 不调用。
    """
    credit = sum((t.amount for t in txns if t.dc_flag.value == "C"), Decimal("0"))
    debit = sum((t.amount for t in txns if t.dc_flag.value == "D"), Decimal("0"))
    expected_delta = end_balance - begin_balance
    actual_delta = credit - debit
    diff = expected_delta - actual_delta
    if abs(diff) <= tolerance:
        return RuleResult("R006", "PASS", f"期初{begin_balance} 期末{end_balance} 勾稽一致")
    return RuleResult(
        "R006",
        "FAIL",
        f"批次勾稽不平衡：期初+收支≠期末，差异 {diff}",
    )