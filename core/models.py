"""Shared internal types — plain dataclasses, no API protos leak past this layer."""
from dataclasses import dataclass, field
from typing import Optional, List, Tuple


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
