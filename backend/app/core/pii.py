"""业务返回的默认 PII 脱敏；是否展示明文由 core 权限决定。"""
from __future__ import annotations

from collections.abc import Mapping


def mask_account(value: object) -> object:
    if value is None:
        return value
    text = str(value)
    return f"{'*' * max(0, len(text) - 4)}{text[-4:]}" if len(text) > 4 else "****"


def mask_name(value: object) -> object:
    if value is None:
        return value
    text = str(value)
    return f"{text[:1]}**" if text else text


def sanitize(value, *, allow_pii: bool):
    """递归清理流水/原始 JSON，避免新增字段意外泄露同类 PII。"""
    if allow_pii:
        return value
    if isinstance(value, Mapping):
        result = {}
        for key, item in value.items():
            key_text = str(key).lower()
            if key_text in {"account_no", "counterparty_account", "bank_account", "accountnumber"}:
                result[key] = mask_account(item)
            elif key_text in {"account_name", "counterparty_name", "account_holder", "customer_name"}:
                result[key] = mask_name(item)
            else:
                result[key] = sanitize(item, allow_pii=False)
        return result
    if isinstance(value, list):
        return [sanitize(item, allow_pii=False) for item in value]
    if isinstance(value, tuple):
        return tuple(sanitize(item, allow_pii=False) for item in value)
    return value
