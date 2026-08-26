"""统一流水契约（Unified Bank Transaction Contract）。

所有采集适配器的输出、中台落库与复核的输入，均以本契约为唯一标准。
字段口径与《数据中间池表结构设计》及 financial_flow_schema.sql 对齐：
契约核心字段 = txn_no / txn_date / txn_time / currency / amount / dc_flag /
              counterparty_name / counterparty_account + summary。
契约 version 用于向后兼容演进（《执行方案》第 6 章「契约版本化」）。
8/27 契约冻结前为草案，字段口径以财务业务顾问定稿为准（决策 D4=B）。
"""
from __future__ import annotations

from datetime import date, time
from decimal import Decimal
from enum import Enum

from pydantic import BaseModel, Field, field_validator

CONTRACT_VERSION = "v1"  # 对齐 dwd_trans_flow.contract_version 默认值
# 规则预填科目的 ext_json 键名：ingest/mapper 写入、review/api 展示，上提为跨域契约常量
AUTO_SUBJECT_KEY = "auto_subject"
# 已确认科目的 ext_json 键名：review 写入、push 制证消费。
# 值为 {subject_code, subject_name, source}，其中 source 为 RULE 或 MANUAL。
APPROVED_SUBJECT_KEY = "approved_subject"


class Direction(str, Enum):
    """借贷方向，对齐 dwd_trans_flow.dc_flag。"""

    DEBIT = "D"  # 借方 / 支出
    CREDIT = "C"  # 贷方 / 收入


class SourceType(str, Enum):
    """采集数据源类型，对齐 dwd_flow_batch.source_type。"""

    MOCK = "MOCK"
    FILE = "FILE"
    API = "API"


class BatchStatus(str, Enum):
    """批次状态，对齐 dwd_flow_batch.status。"""

    IMPORTING = "IMPORTING"
    LOADED = "LOADED"
    VALIDATED = "VALIDATED"
    RECONCILED = "RECONCILED"


class ProcessStatus(str, Enum):
    """流水业务阶段，对齐 dwd_trans_flow.process_status。"""

    LOADED = "LOADED"
    VALIDATING = "VALIDATING"
    REVIEW_READY = "REVIEW_READY"
    REVIEW_PASSED = "REVIEW_PASSED"
    PUSHED = "PUSHED"
    KINGDEE_POSTED = "KINGDEE_POSTED"
    REJECTED = "REJECTED"


class ValidationStatus(str, Enum):
    """校验结论，对齐 dwd_trans_flow.validation_status。"""

    PENDING = "PENDING"
    PASS = "PASS"
    WARN = "WARN"
    FAIL = "FAIL"


class ReviewResult(str, Enum):
    """复核结论，对齐 biz_flow_review.review_result。"""

    PASS = "PASS"  # 通过
    REJECT = "REJECT"  # 驳回
    ADJUST = "ADJUST"  # 调整（人工匹配科目后通过）


class PushStatus(str, Enum):
    """金蝶推送状态，对齐 biz_push_record.push_status。"""

    PENDING = "PENDING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    UNCERTAIN = "UNCERTAIN"  # 远端连接中断，可能已制证，须先查单确认


class BankTransaction(BaseModel):
    """标准流水契约：所有数据源归一化后的输出标准（采集适配层唯一出口）。"""

    contract_version: str = CONTRACT_VERSION

    # 来源标识（入库时解析为 dim_bank / dim_bank_account）
    bank_code: str = Field(..., description="银行编码，CMB=招商 / CITIC=中信")
    account_no: str = Field(..., description="本方银行账号")

    # 契约核心字段
    txn_no: str = Field(..., description="银行侧唯一流水号")
    txn_date: date = Field(..., description="交易日期")
    txn_time: time | None = Field(default=None, description="交易时间")
    currency: str = Field(default="CNY", description="币种 ISO4217")
    amount: Decimal = Field(..., gt=0, description="金额，恒为正")
    dc_flag: Direction = Field(..., description="借贷方向")
    counterparty_name: str | None = Field(default=None, description="对方户名")
    counterparty_account: str | None = Field(default=None, description="对方账号")
    summary: str | None = Field(default=None, description="摘要")

    # 预留扩展（非核心字段原样留痕，写入 ext_json / raw_content）
    ext: dict[str, object] | None = Field(default=None, description="预留扩展字段")

    @field_validator("currency")
    @classmethod
    def _normalize_currency(cls, v: str) -> str:
        return v.upper()

    def dedup_seed(self, bank_id: int, account_id: int) -> str:
        """幂等去重种子，与 dwd_trans_flow.dedup_key 口径一致。

        SHA256(bank_id|account_id|txn_no|txn_date|amount|dc_flag)
        """
        return "|".join([
            str(bank_id),
            str(account_id),
            self.txn_no,
            self.txn_date.isoformat(),
            f"{self.amount:.2f}",
            self.dc_flag.value,
        ])
