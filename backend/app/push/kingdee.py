"""金蝶云星空对接服务（决策 D8 = OpenAPI 直连）。

一期凭据未就绪时走 Mock（9/16 链路打通演示）；
凭据就绪后 OpenApiKingdeeClient 复用金蝶官方 Python SDK（vendored wheel）做真实推送，
签名采用「第三方系统登录授权」：X-Kd-AppKey / X-Kd-Appdata / X-Kd-Signature 三件套，
由官方 `K3CloudApiSdk` 统一生成，无需在业务层自维护密钥。
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any

import requests

from app.core.contract import APPROVED_SUBJECT_KEY, AUTO_SUBJECT_KEY
from app.core.config import settings
from app.models import TransFlow

try:
    from k3cloud_webapi_sdk.main import K3CloudApiSdk
    _HAS_KD_SDK = True
except ImportError:  # pragma: no cover - 仅当未安装 vendored wheel 时发生
    K3CloudApiSdk = None
    _HAS_KD_SDK = False

# 总账凭证（GL_VOUCHER）科目/账簿/币别字典项：需财务与金蝶顾问按真实账套回填后再启用真实推送。
GL_VOUCHER_FORMID = "GL_VOUCHER"

# TODO(金蝶字典回填): 以下编码为占位值，必须按目标账套字典确认
_BANK_SUBJECT_NO = "1002.01"      # 银行科目占位（借方发生账户）
_BOOK_NO = "001"                  # 账簿编码占位
_CNY_FCURRENCY_NO = "PRE001"      # 人民币预设币别


class KingdeeClient:
    """金蝶推送客户端抽象。"""

    def push_voucher(self, flow: TransFlow, *, idempotency_key: str) -> dict:
        """推送单笔流水生成凭证，返回金蝶响应（含 voucher_no / doc_no）。"""
        raise NotImplementedError


class KingdeeIndeterminateError(RuntimeError):
    """网络中断导致远端是否已落单不可判定，禁止自动重推。"""


class MockKingdeeClient(KingdeeClient):
    """Mock 金蝶：本地生成凭证号，供链路打通演示与 CI 使用。"""

    _seq = 0

    def push_voucher(self, flow: TransFlow, *, idempotency_key: str) -> dict:
        MockKingdeeClient._seq += 1
        voucher_no = f"PZ-{datetime.now():%Y%m%d}-{MockKingdeeClient._seq:05d}"
        return {
            "voucher_no": voucher_no,
            "doc_no": f"DOC-{flow.txn_no}",
            "remote_status": "MOCK_SAVED",
            "idempotency_key": idempotency_key,
            "mock": True,
        }


def resolve_subject_code(flow: TransFlow) -> str:
    """优先采用复核确认科目，兼容未进入人工复核的规则预填科目。"""
    ext = flow.ext_json or {}
    for key in (APPROVED_SUBJECT_KEY, AUTO_SUBJECT_KEY):
        subject = ext.get(key)
        if isinstance(subject, dict):
            code = str(subject.get("subject_code") or "").strip()
            if code:
                return code
    raise ValueError("流水缺少已确认的对方科目，不能生成金蝶凭证")


def build_voucher_model(flow: TransFlow) -> dict[str, Any]:
    """构造金蝶云星空总账凭证（GL_VOUCHER）保存 Model（最小可运行骨架）。

    借贷方向按统一契约 dc_flag：D=借方（资金流入），C=贷方（资金流出）。
    金额以字符串传递以保留 Decimal 精度；对方科目从复核确认值取得。
    银行科目、账簿、币别仍待按目标账套字典回填。
    """
    amount = str(abs(flow.amount))
    is_debit = flow.dc_flag == "D"
    currency_no = _CNY_FCURRENCY_NO if flow.currency == "CNY" else flow.currency
    summary = flow.summary or flow.counterparty_name or ""

    bank_side = {
        "FDebit": amount if is_debit else "0",
        "FCredit": "0" if is_debit else amount,
    }
    counterparty_side = {
        "FDebit": "0" if is_debit else amount,
        "FCredit": amount if is_debit else "0",
    }

    def _entry(account_no: str, side: dict[str, str]) -> dict[str, Any]:
        return {
            "FExplanation": summary,
            "FAccountID": {"FNumber": account_no},
            "FCurrencyID": {"FNumber": currency_no},
            "FExchangeRate": 1,
            **side,
        }

    return {
        "FDate": flow.txn_date.isoformat(),
        "FBookID": {"FNumber": _BOOK_NO},
        "FExplanation": summary,
        "FEntity": [
            _entry(_BANK_SUBJECT_NO, bank_side),
            _entry(resolve_subject_code(flow), counterparty_side),
        ],
    }


class OpenApiKingdeeClient(KingdeeClient):
    """真实金蝶云星空 OpenAPI 客户端（复用官方 Python SDK）。

    由 `get_kingdee_client()` 在 `settings.kingdee_mock_enabled=False` 时构造。
    """

    def __init__(self) -> None:
        if not _HAS_KD_SDK:
            raise RuntimeError(
                "缺少金蝶官方 SDK（k3cloud_webapi_sdk）。"
                "请先安装 backend/vendor/kingdee.cdp.webapi.sdk-8.2.0-py3-none-any.whl 再启用真实推送。"
            )
        server_url = settings.kingdee_base_url.rstrip("/") + "/"
        self._sdk = K3CloudApiSdk(server_url, timeout=settings.kingdee_timeout)
        self._sdk.InitConfig(
            acct_id=settings.kingdee_acct_id,
            user_name=settings.kingdee_user_name,
            app_id=settings.kingdee_app_id,
            app_secret=settings.kingdee_app_secret,
            server_url=server_url,
            lcid=settings.kingdee_lcid,
            org_num=settings.kingdee_org_num,
            connect_timeout=settings.kingdee_timeout,
            request_timeout=settings.kingdee_timeout,
        )

    def push_voucher(self, flow: TransFlow, *, idempotency_key: str) -> dict:
        data = {
            "NeedUpDateFields": [],
            "NeedReturnFields": ["FBillNo"],
            "IsDeleteEntry": "True",
            "SubSystemId": "",
            "IsVerifyBaseDataField": "False",
            "IsEntryBatchFill": "True",
            "ValidateFlag": "True",
            "NumberSearch": "True",
            "IsAutoAdjustField": "False",
            "InterationFlags": "",
            "IgnoreInterationFlag": "",
            "IsControlPrecision": "False",
            "Model": build_voucher_model(flow),
        }
        try:
            response = self._sdk.Save(GL_VOUCHER_FORMID, data)
        except (TimeoutError, ConnectionError, requests.exceptions.Timeout, requests.exceptions.ConnectionError) as exc:
            raise KingdeeIndeterminateError(
                "调用金蝶时连接中断，远端可能已保存凭证；请先按流水号查单确认"
            ) from exc
        return self._parse_save_response(response, flow)

    @staticmethod
    def _parse_save_response(response: str, flow: TransFlow) -> dict:
        try:
            payload = json.loads(response)
        except (TypeError, ValueError) as exc:  # noqa: BLE001  保留原始响应便于定位
            raise RuntimeError(f"金蝶响应解析失败：{response[:256]}") from exc

        result = payload.get("Result") or {}
        status = result.get("ResponseStatus") or {}
        if not status.get("IsSuccess"):
            errors = status.get("Errors") or []
            detail = "; ".join(str(e.get("Message", "")) for e in errors) if errors else str(payload)
            raise RuntimeError(f"金蝶凭证保存失败：{detail[:512]}")

        voucher_no = str(result.get("Number") or "").strip()
        doc_no = str(result.get("Id") or "").strip()
        return {
            "voucher_no": voucher_no or f"GL-{flow.txn_no}",
            "doc_no": doc_no or flow.txn_no,
            "remote_status": "SAVED",
            "mock": False,
        }


def get_kingdee_client() -> KingdeeClient:
    return MockKingdeeClient() if settings.kingdee_mock_enabled else OpenApiKingdeeClient()
