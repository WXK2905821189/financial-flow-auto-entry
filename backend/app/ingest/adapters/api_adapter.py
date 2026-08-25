"""银企直连 HTTP 采集适配器（决策 D6 主路：模拟银行 API 跑通生产链路）。

真实 HTTP 调用内网银企服务（默认 mock_bank_api:8080）→ 按银行字段差异映射/清洗
→ 输出统一 BankTransaction 契约 → 交由 ingest 落库，`source_type=API` 做切换留痕。

招商/中信任意字段名不同（对方户名 vs 对方账户名、借贷标志 vs 借贷方向、
摘要 vs 银行摘要），复用 file_adapter 的列别名映射；真实银行凭据就绪
（决策 D3）后仅替换 base_url 与签名逻辑即可切换，不动核心链路。

容错：单页/健康检查遇网络抖动或网关 5xx 走指数退避重试；整批拉取若中途失败，
因 dedup_key 幂等，直接重放再拉即可恢复，不会产生重复脏数据（可重放补偿）。
"""
from __future__ import annotations

import hashlib
from datetime import date

import httpx

from app.ingest.adapters.base import BaseAdapter
from app.ingest.adapters.file_adapter import _map_dict
from app.ingest.adapters.registry import register_adapter
from app.core.config import settings
from app.core.contract import BankTransaction, SourceType
from app.core.retry import exponential_backoff_retry

_DEFAULT_SECRET = settings.bank_api_sign_secret


class _TransientServerError(Exception):
    """银行网关瞬时错误（HTTP 5xx），归类为可重试。"""


_RETRYABLE_EXC: tuple[type[BaseException], ...] = (
    httpx.ConnectError,
    httpx.TimeoutException,
    _TransientServerError,
)


@register_adapter
class MockBankApiAdapter(BaseAdapter):
    source_type = SourceType.API

    def __init__(self, base_url: str | None = None, timeout: int = 15):
        self.base_url = (base_url or settings.bank_api_base_url).rstrip("/")
        self.timeout = timeout

    def fetch(
        self,
        *,
        bank_code: str = "CITIC",
        account_no: str = "",
        start_date: date | None = None,
        end_date: date | None = None,
        page_size: int = 200,
        **kwargs,
    ) -> list[BankTransaction]:
        """拉取指定账户全量流水（自动翻页聚合）并归一化为统一契约。"""
        if not account_no:
            raise ValueError("account_no 必填")
        self._check_health()
        txns = self._pull_all(
            bank_code, account_no,
            start_date.isoformat() if start_date else None,
            end_date.isoformat() if end_date else None,
            page_size,
        )
        if not txns:
            raise ValueError(f"银企接口返回 0 笔流水（bank={bank_code}）")
        return txns

    @exponential_backoff_retry(
        max_attempts=3,
        base_delay=1.0,
        max_delay=10.0,
        exc_types=_RETRYABLE_EXC,
    )
    def _check_health(self) -> None:
        with httpx.Client(timeout=min(self.timeout, 5)) as client:
            resp = client.get(f"{self.base_url}/api/health")
            if resp.status_code >= 500:
                raise _TransientServerError(f"银企健康检查 5xx {resp.status_code}")
            resp.raise_for_status()
            if resp.json().get("returnCode") != "0000":
                raise ValueError(f"银企服务异常：{resp.json().get('returnMsg')}")

    def _pull_all(
        self,
        bank_code: str,
        account_no: str,
        start: str | None,
        end: str | None,
        page_size: int,
    ) -> list[BankTransaction]:
        txns: list[BankTransaction] = []
        page = 1
        total_page = 1
        bank_code = bank_code.upper()
        with httpx.Client(timeout=self.timeout) as client:
            while page <= total_page:
                data = self._fetch_page(client, bank_code, account_no, start, end, page, page_size)
                d = data.get("data") or {}
                total_page = int(d.get("totalPage") or 1)
                for item in d.get("list") or []:
                    txn = _map_dict(item, bank_code, account_no)
                    if txn is not None:
                        txns.append(txn)
                page += 1
        return txns

    @exponential_backoff_retry(
        max_attempts=3,
        base_delay=1.0,
        max_delay=10.0,
        exc_types=_RETRYABLE_EXC,
    )
    def _fetch_page(
        self,
        client: httpx.Client,
        bank_code: str,
        account_no: str,
        start: str | None,
        end: str | None,
        page: int,
        page_size: int,
    ) -> dict:
        body: dict = {
            "accountNo": account_no,
            "pageNo": page,
            "pageSize": page_size,
        }
        if start:
            body["startDate"] = start
        if end:
            body["endDate"] = end
        body["sign"] = self._sign(account_no, start, end)
        resp = client.post(f"{self.base_url}/api/bank/{bank_code}/query", json=body)
        if resp.status_code >= 500:
            raise _TransientServerError(f"银企采集 5xx {resp.status_code} (page={page})")
        resp.raise_for_status()
        data = resp.json()
        code = data.get("returnCode")
        if code != "0000":
            raise ValueError(f"银行返回 {code} {data.get('returnMsg')}")
        return data

    def _sign(self, account_no: str, start: str | None, end: str | None) -> str | None:
        """MD5 签名：sign = md5(accountNo + startDate + endDate + SECRET)。"""
        if not _DEFAULT_SECRET:
            return None
        raw = "".join([str(account_no), str(start or ""), str(end or ""), _DEFAULT_SECRET])
        return hashlib.md5(raw.encode("utf-8")).hexdigest()