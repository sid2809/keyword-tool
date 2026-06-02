"""Engine-internal RPC helpers: rate limiting, retry, year-month range.

Used by metrics.py and ideas.py. No raw API protos leak — callers pass in the
client and we mutate the request they own.
"""
from __future__ import annotations

import datetime
import time
from typing import Callable, TypeVar

from google.api_core import exceptions as gax_exc

T = TypeVar("T")

# Spec §5.2: ≥1.05s between any two keyword-planning calls per CID.
RATE_LIMIT_SECONDS = 1.1
_BACKOFF_DELAYS = [2.0, 4.0, 8.0, 16.0]

_MONTH_NAMES = [
    "JANUARY", "FEBRUARY", "MARCH", "APRIL", "MAY", "JUNE",
    "JULY", "AUGUST", "SEPTEMBER", "OCTOBER", "NOVEMBER", "DECEMBER",
]

_last_call_ts = 0.0


def rate_limit() -> None:
    """Block until ≥RATE_LIMIT_SECONDS have elapsed since the last call."""
    global _last_call_ts
    now = time.monotonic()
    delta = now - _last_call_ts
    if delta < RATE_LIMIT_SECONDS:
        time.sleep(RATE_LIMIT_SECONDS - delta)
    _last_call_ts = time.monotonic()


def _is_resource_exhausted(exc: BaseException) -> bool:
    if isinstance(exc, gax_exc.ResourceExhausted):
        return True
    return "RESOURCE_EXHAUSTED" in str(exc)


def call_with_retry(fn: Callable[[], T], max_retries: int = 4) -> T:
    """Call fn; on RESOURCE_EXHAUSTED, retry with exponential backoff (2,4,8,16s)."""
    for attempt in range(max_retries + 1):
        try:
            return fn()
        except Exception as e:
            if attempt < max_retries and _is_resource_exhausted(e):
                time.sleep(_BACKOFF_DELAYS[attempt])
                continue
            raise


def set_year_month_range(client, options, months_back: int):
    """Populate options.year_month_range covering `months_back` complete months
    ending on the last complete month (today minus 1 month).

    proto-plus: assign nested fields directly; do not use CopyFrom.
    """
    today = datetime.date.today()
    end_year = today.year
    end_month = today.month - 1
    if end_month == 0:
        end_month = 12
        end_year -= 1
    start_month = end_month - (months_back - 1)
    start_year = end_year
    while start_month <= 0:
        start_month += 12
        start_year -= 1
    month_enum = client.enums.MonthOfYearEnum
    options.year_month_range.start.year = start_year
    options.year_month_range.start.month = getattr(month_enum, _MONTH_NAMES[start_month - 1])
    options.year_month_range.end.year = end_year
    options.year_month_range.end.month = getattr(month_enum, _MONTH_NAMES[end_month - 1])


def month_num(month_value) -> int:
    """Map a MonthOfYear enum (proto-plus or raw int) → 1..12."""
    if hasattr(month_value, "name"):
        try:
            return _MONTH_NAMES.index(month_value.name) + 1
        except ValueError:
            return 0
    if isinstance(month_value, int):
        # API enum: UNSPECIFIED=0, UNKNOWN=1, JANUARY=2..DECEMBER=13
        if 2 <= month_value <= 13:
            return month_value - 1
    return 0
