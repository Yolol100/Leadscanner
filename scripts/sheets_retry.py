#!/usr/bin/env python3
from __future__ import annotations

import time
from typing import Callable, TypeVar

T = TypeVar("T")


def is_retryable_error(exc: BaseException) -> bool:
    text = str(exc).casefold()
    return isinstance(exc, (OSError, TimeoutError)) or any(token in text for token in (
        "ssl", "eof occurred", "timed out", "timeout", "connection reset", "connection aborted",
        "temporarily unavailable", "rate limit", "429", "500", "502", "503", "504",
    ))


def with_retry(call: Callable[[], T], *, attempts: int = 4, base_delay: float = 0.75) -> T:
    last: BaseException | None = None
    for attempt in range(1, max(1, attempts) + 1):
        try:
            return call()
        except Exception as exc:
            last = exc
            if not is_retryable_error(exc) or attempt >= attempts:
                raise
            time.sleep(min(8.0, base_delay * (2 ** (attempt - 1))))
    assert last is not None
    raise last
