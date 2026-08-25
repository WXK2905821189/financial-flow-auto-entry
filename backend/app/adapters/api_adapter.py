"""真实银企直联适配器（预留切换点）。

对应决策 D6：真实银行 API 预留切换点。真实凭据就绪后（决策 D3）实现
_fetch_remote() 拉取原始报文并映射为 BankTransaction，即可无缝切换，不动核心链路。
"""
from __future__ import annotations

from app.adapters.base import BaseAdapter
from app.adapters.registry import register_adapter
from app.contract import BankTransaction, SourceType


@register_adapter
class BankApiAdapter(BaseAdapter):
    source_type = SourceType.API

    def fetch(self, **kwargs) -> list[BankTransaction]:
        raise NotImplementedError(
            "真实银企直联接口暂未接入（决策 D3 待银行凭据）。"
            "实现 _fetch_remote() 拉取原始报文并映射为 BankTransaction 后启用。"
        )