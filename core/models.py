"""Shared internal types — plain dataclasses, no API protos leak past this layer."""
from dataclasses import dataclass, field
from typing import Optional, List, Tuple, Any


@dataclass
class MonthlyVolume:
    year: int
    month: int  # 1..12
    searches: int


@dataclass
class Row:
    keyword: str
    geo_target: str = "geoTargetConstants/2840"
    language: str = "ALL"
    network: str = "GOOGLE_SEARCH"
    recent_avg_monthly_searches: Optional[int] = None
    raw_avg_monthly_searches: Optional[int] = None
    competition: Optional[str] = None
    competition_index: Optional[int] = None
    low_top_of_page_bid_micros: Optional[int] = None
    high_top_of_page_bid_micros: Optional[int] = None
    three_month_change: Optional[float] = None
    currency_code: Optional[str] = None
    has_data: bool = True
    is_close_variant_merged: bool = False
    monthly_volumes: Optional[List[MonthlyVolume]] = None


# Snapshot helpers — for persisting Row to/from JSONB.
# Skips monthly_volumes (not used by the table view; keeps payload small).
_SNAPSHOT_FIELDS = (
    "keyword", "geo_target", "language", "network",
    "recent_avg_monthly_searches", "raw_avg_monthly_searches",
    "competition", "competition_index",
    "low_top_of_page_bid_micros", "high_top_of_page_bid_micros",
    "three_month_change", "currency_code",
    "has_data", "is_close_variant_merged",
)


def row_to_dict(row: Row) -> dict[str, Any]:
    return {f: getattr(row, f) for f in _SNAPSHOT_FIELDS}


def row_from_dict(d: dict[str, Any]) -> Row:
    return Row(**{k: v for k, v in d.items() if k in _SNAPSHOT_FIELDS})
