"""固定角色与权限点。业务域仅声明所需权限，不得自行实现角色判断。"""
from __future__ import annotations

from enum import Enum


class Role(str, Enum):
    SYSTEM_ADMIN = "SYSTEM_ADMIN"
    FINANCE_MANAGER = "FINANCE_MANAGER"
    REVIEWER = "REVIEWER"
    INGEST_OPERATOR = "INGEST_OPERATOR"
    AUDITOR = "AUDITOR"


class Permission(str, Enum):
    INGEST_WRITE = "ingest:write"
    REVIEW_READ = "review:read"
    REVIEW_WRITE = "review:write"
    PUSH_WRITE = "push:write"
    DASHBOARD_READ = "dashboard:read"
    TRACE_READ = "trace:read"
    SETTINGS_READ = "settings:read"
    USER_ADMIN = "user:admin"
    PII_READ = "pii:read"


ROLE_PERMISSIONS: dict[str, set[str]] = {
    # 系统管理员只管理账号、授权和系统状态；不自动获得财务业务或 PII 权限。
    Role.SYSTEM_ADMIN.value: {Permission.SETTINGS_READ.value, Permission.USER_ADMIN.value},
    Role.FINANCE_MANAGER.value: {
        Permission.REVIEW_READ.value, Permission.REVIEW_WRITE.value, Permission.PUSH_WRITE.value,
        Permission.DASHBOARD_READ.value, Permission.TRACE_READ.value, Permission.PII_READ.value,
    },
    Role.REVIEWER.value: {Permission.REVIEW_READ.value, Permission.REVIEW_WRITE.value, Permission.DASHBOARD_READ.value, Permission.TRACE_READ.value, Permission.PII_READ.value},
    Role.INGEST_OPERATOR.value: {Permission.INGEST_WRITE.value, Permission.DASHBOARD_READ.value},
    Role.AUDITOR.value: {Permission.REVIEW_READ.value, Permission.DASHBOARD_READ.value, Permission.TRACE_READ.value},
    # 旧种子账号兼容；新账号只允许 SYSTEM_ADMIN。
    "ADMIN": {Permission.SETTINGS_READ.value, Permission.USER_ADMIN.value},
}


def is_system_admin(role: str) -> bool:
    return role in {Role.SYSTEM_ADMIN.value, "ADMIN"}
