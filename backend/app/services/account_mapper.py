from __future__ import annotations

import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.contract import BankTransaction
from app.models import AccountMapping, TransFlow

# 命中的默认键名，写入 ext_json（复核台读取展示）
AUTO_SUBJECT_KEY = "auto_subject"


def _normalize(text: str | None) -> str:
    """摘要归一化：去空白/大小写统一，便于稳定匹配与幂等。"""
    if not text:
        return ""
    return re.sub(r"\s+", " ", text).strip().lower()


def _dc_to_direction(dc_flag: str) -> str:
    """dc_flag 值域对齐为财务语义：C→CREDIT(收入)、D→DEBIT(支出)。"""
    return "CREDIT" if dc_flag == "C" else "DEBIT"


def _is_direction_matched(rule: AccountMapping, dc_flag: str) -> bool:
    if rule.direction in ("BOTH", ""):
        return True
    return rule.direction == _dc_to_direction(dc_flag)


def match_for(txn: BankTransaction, rules: list[AccountMapping]) -> AccountMapping | None:
    """对单笔流水做规则匹配，返回首条命中规则，无命中返回 None。"""
    if not rules:
        return None
    hay = f"{_normalize(txn.summary)} {_normalize(txn.counterparty_name)}".strip()
    if not hay:
        return None
    for rule in rules:
        if not rule.is_enabled or not _is_direction_matched(rule, txn.dc_flag.value):
            continue
        if rule.match_type == "REGEX":
            try:
                if re.search(rule.pattern, hay):
                    return rule
            except re.error:
                continue
        elif rule.pattern.lower() in hay:
            return rule
    return None


def load_rules(db: Session) -> list[AccountMapping]:
    """加载启用中的映射规则，按 priority 升序、id 升序排序（首条命中）。"""
    rows = db.execute(
        select(AccountMapping)
        .where(AccountMapping.is_enabled.is_(True))
        .order_by(AccountMapping.priority, AccountMapping.mapping_id)
    ).scalars().all()
    return list(rows)


def prefill(flow: TransFlow, txn: BankTransaction, db: Session) -> AccountMapping | None:
    """预填对方科目：命中规则则写入 ext_json.auto_subject，返回命中的规则。

    幂等：重复调用覆盖同一 key，不影响已有 matched_subject 等其他扩展字段。
    """
    rule = match_for(txn, load_rules(db))
    if rule is None:
        return None
    payload = {
        "subject_code": rule.subject_code,
        "subject_name": rule.subject_name,
        "pattern": rule.pattern,
        "direction": rule.direction,
        "mapping_id": rule.mapping_id,
    }
    flow.ext_json = {**(flow.ext_json or {}), AUTO_SUBJECT_KEY: payload}
    return rule
