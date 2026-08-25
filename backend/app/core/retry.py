"""采集/推送通用重试工具：指数退避 + 幂等可重放补偿。

接口抖动（连接失败/超时/网关 5xx）做有限次指数退避重试；业务侧依赖
dedup_key 幂等，批次拉取一半失败时可直接整体重放恢复，不会产生重复脏数据。
"""
from __future__ import annotations

import time
from functools import wraps
from typing import Callable, TypeVar

T = TypeVar("T")


class RetryExhausted(Exception):
    """重试次数耗尽仍未成功。"""


def exponential_backoff_retry(
    *,
    max_attempts: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 10.0,
    exc_types: tuple[type[BaseException], ...] = (ConnectionError, TimeoutError),
) -> Callable[[Callable[..., T]], Callable[..., T]]:
    """对指定异常做指数退避重试。

    退避序列：base_delay * 2**(attempt-1) 并封顶 max_delay；max_attempts 为总尝试次数
    （含首次，即最多重试 max_attempts - 1 次）。
    """

    def decorator(fn: Callable[..., T]) -> Callable[..., T]:
        @wraps(fn)
        def wrapper(*args, **kwargs) -> T:
            last_exc: BaseException | None = None
            for attempt in range(max_attempts):
                try:
                    return fn(*args, **kwargs)
                except exc_types as exc:
                    last_exc = exc
                    if attempt >= max_attempts - 1:
                        break
                    time.sleep(min(base_delay * (2 ** attempt), max_delay))
            raise RetryExhausted(
                f"{fn.__name__} 在 {max_attempts} 次尝试后仍失败：{last_exc}"
            ) from last_exc

        return wrapper

    return decorator