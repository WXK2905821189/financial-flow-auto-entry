"""Mock 采集适配器：自建「模拟银行」生成逼真原始流水。

对应《执行方案》决策 D6：一期以模拟银行 API 为主，跑通生产调用链路。
数据生成确定性可复现（固定随机种子），便于 CI 契约测试与端到端演示。
"""
from __future__ import annotations

import random
from datetime import date, time
from decimal import Decimal

from app.adapters.base import BaseAdapter
from app.adapters.registry import register_adapter
from app.contract import BankTransaction, Direction, SourceType


@register_adapter
class MockAdapter(BaseAdapter):
    source_type = SourceType.MOCK

    _COUNTERPARTIES = [
        "北京字节跳动科技有限公司",
        "深圳市腾讯计算机系统有限公司",
        "杭州阿里巴巴网络技术有限公司",
        "北京市海淀区税务局",
        "某某电子商务有限公司",
        "个人客户-张三",
    ]
    _SUMMARIES = ["货款", "服务费", "代发工资", "税费", "往来款", "退款"]

    def fetch(
        self,
        *,
        bank_code: str = "CITIC",
        account_no: str = "1100000000001",
        start_date: date | None = None,
        end_date: date | None = None,
        count: int = 50,
        seed: int = 20260824,
        **kwargs,
    ) -> list[BankTransaction]:
        rng = random.Random(seed)
        start_date = start_date or date(2026, 8, 1)
        end_date = end_date or date(2026, 8, 23)
        days = (end_date - start_date).days + 1

        result: list[BankTransaction] = []
        for i in range(count):
            d = date.fromordinal(start_date.toordinal() + rng.randrange(days))
            amount = Decimal(rng.randint(100, 95_000))
            if i % 13 == 0:  # 少量大额触发 R004 超阈值(50万)人工复核（约占 8%，贴合 ≥80% 自动化）
                amount = Decimal("820000.00")
            dc = Direction.CREDIT if rng.random() < 0.5 else Direction.DEBIT
            result.append(
                BankTransaction(
                    bank_code=bank_code,
                    account_no=account_no,
                    txn_no=f"{bank_code}{d:%Y%m%d}{rng.randint(100000, 999999)}",
                    txn_date=d,
                    txn_time=time(rng.randint(0, 23), rng.randint(0, 59), rng.randint(0, 59)),
                    currency="CNY",
                    amount=amount,
                    dc_flag=dc,
                    counterparty_name=rng.choice(self._COUNTERPARTIES),
                    counterparty_account=str(rng.randint(1_000_000_000_000, 9_999_999_999_999)),
                    summary=rng.choice(self._SUMMARIES),
                )
            )
        return result