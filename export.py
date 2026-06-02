"""CSV helpers (infra). Used by ui_metrics and ui_shortlist for downloads."""
from __future__ import annotations

import csv
import io
from typing import Iterable

from core.models import Row


HEADER = [
    "keyword",
    "avg_monthly_searches_last_3_months",
    "three_month_change_pct",
    "competition",
    "competition_index",
    "low_top_of_page_bid_inr",
    "high_top_of_page_bid_inr",
    "currency",
    "is_close_variant_merged",
    "has_data",
]


def _inr(micros) -> str:
    return f"{micros / 1_000_000:.2f}" if micros else ""


def output_rows_to_csv(output: Iterable[tuple[str, Row]]) -> str:
    """Take expanded output (input_keyword, Row) tuples → CSV string.

    Uses input_keyword (preserves original ordering + casing + duplicates per
    spec §4.5).
    """
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(HEADER)
    for raw_input, row in output:
        w.writerow([
            raw_input,
            row.recent_avg_monthly_searches if row.recent_avg_monthly_searches is not None else "",
            f"{row.three_month_change:+.2f}" if row.three_month_change is not None else "",
            row.competition or "",
            row.competition_index if row.competition_index is not None else "",
            _inr(row.low_top_of_page_bid_micros),
            _inr(row.high_top_of_page_bid_micros),
            row.currency_code or "",
            "yes" if row.is_close_variant_merged else "",
            "yes" if row.has_data else "no",
        ])
    return buf.getvalue()


def shortlist_to_csv(rows: list[dict]) -> str:
    """List-of-dict from db.list_shortlist() → CSV."""
    header = ["keyword", "added_at", "source_tab", "source_search_id",
              "recent_avg_monthly_searches", "three_month_change",
              "competition", "low_top_of_page_bid_inr", "high_top_of_page_bid_inr"]
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(header)
    for r in rows:
        snap = r.get("metrics_snapshot") or {}
        low = snap.get("low_top_of_page_bid_micros")
        high = snap.get("high_top_of_page_bid_micros")
        w.writerow([
            r["keyword"],
            r["added_at"].isoformat() if r.get("added_at") else "",
            r.get("source_tab") or "",
            r.get("source_search_id") or "",
            snap.get("recent_avg_monthly_searches") or "",
            f"{snap.get('three_month_change'):+.2f}" if snap.get("three_month_change") is not None else "",
            snap.get("competition") or "",
            _inr(low),
            _inr(high),
        ])
    return buf.getvalue()
