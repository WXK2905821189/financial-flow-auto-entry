"""采集适配层抽象基类。

适配器是可插拔的数据源接入点。任何新银行/数据源只需实现 BaseAdapter.fetch()
并返回 List[BankTransaction]，即可接入中台，不改动核心链路（《执行方案》第 8 章）。
"""
from __future__ import annotations

from abc import ABC, abstractmethod

from app.core.contract import BankTransaction, SourceType


class BaseAdapter(ABC):
    """采集适配器抽象基类。"""

    source_type: SourceType

    @abstractmethod
    def fetch(self, **kwargs) -> list[BankTransaction]:
        """拉取原始流水并归一化为统一契约（List[BankTransaction]）。

        子类职责：从各自数据源取数 → 字段映射/清洗 → 输出标准契约对象。
        """
        raise NotImplementedError