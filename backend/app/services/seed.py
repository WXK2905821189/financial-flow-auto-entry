from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.core.security import hash_password
from app.models import AccountMapping, Bank, ValidationRule
from app.models.sys_user import User


def ensure_seed(db: Session) -> None:
    _seed_banks(db)
    _seed_rules(db)
    _seed_mappings(db)
    _seed_admin(db)
    db.commit()


def _seed_banks(db: Session) -> None:
    seed = [("CMB", "招商银行"), ("CITIC", "中信银行")]
    for code, name in seed:
        if db.execute(select(Bank).where(Bank.bank_code == code)).scalar_one_or_none() is None:
            db.add(Bank(bank_code=code, bank_name=name, is_active=True))


def _seed_rules(db: Session) -> None:
    rules = [
        ("R001", "重复流水", "ERROR", "同银行同账号同流水号同日期同金额重复导入"),
        ("R002", "负金额/方向非法", "ERROR", "金额为负或 dc_flag 不在 D/C 取值"),
        ("R003", "必填字段缺失", "ERROR", "契约核心字段（日期/金额/方向/对方户名/流水号）缺失"),
        ("R004", "单笔金额超阈值", "WARN", "单笔金额超过可配置阈值，需人工复核"),
        ("R005", "币种非法", "ERROR", "币种不在 ISO4217 合法取值"),
        ("R006", "批次余额勾稽", "WARN", "银行报表期初+Σ收入−Σ支出≠期末，整批判不平需人工介入"),
    ]
    for code, name, level, desc in rules:
        if db.execute(select(ValidationRule).where(ValidationRule.rule_code == code)).scalar_one_or_none() is None:
            db.add(ValidationRule(rule_code=code, rule_name=name, rule_level=level, is_enabled=True, description=desc))


def _seed_mappings(db: Session) -> None:
    seeds = [
        ("代发工资", "KEYWORD", "DEBIT", "2211.01", "应付职工薪酬-工资", 10),
        ("税款", "KEYWORD", "DEBIT", "2221", "应交税费", 20),
        ("税费", "KEYWORD", "DEBIT", "2221", "应交税费", 20),
        ("利息", "KEYWORD", "BOTH", "6603", "财务费用-利息", 30),
        ("货款", "KEYWORD", "CREDIT", "1122", "应收账款", 40),
        ("退款", "KEYWORD", "CREDIT", "2202", "应付账款", 40),
    ]
    if db.execute(select(AccountMapping).limit(1)).scalar_one_or_none() is not None:
        return
    for pattern, match_type, direction, code, name, priority in seeds:
        db.add(AccountMapping(pattern=pattern, match_type=match_type, direction=direction, subject_code=code, subject_name=name, priority=priority, is_enabled=True))


def _seed_admin(db: Session) -> None:
    username = settings.initial_admin_username
    if db.execute(select(User).where(User.username == username)).scalar_one_or_none() is None:
        db.add(User(username=username, password_hash=hash_password(settings.initial_admin_password), display_name="财务管理员", role="ADMIN", is_active=True))
