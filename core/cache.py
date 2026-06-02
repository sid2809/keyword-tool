"""Read-through cache. Spec §4.4.

Engine-internal. Operates on plain Row objects from models.py — no API protos.
The caller owns the psycopg connection; we never open or close it.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Iterable

from .models import Row, MonthlyVolume


def normalize(keyword: str) -> str:
    """Spec §4.2: trim + lowercase before hashing into the cache."""
    return keyword.strip().lower()


def lookup_fresh(
    conn,
    keywords: list[str],
    *,
    geo_target: str,
    language: str,
    network: str,
    max_age_days: int,
    force_refresh: bool = False,
) -> tuple[dict[str, Row], list[str]]:
    """Return ({normalized_keyword: Row} for fresh hits, [missing normalized keywords]).

    If force_refresh is True, every keyword is treated as missing.
    """
    unique = list(dict.fromkeys(keywords))  # dedupe preserving order
    if force_refresh or not unique:
        return {}, unique

    cutoff = datetime.now(timezone.utc) - timedelta(days=max_age_days)
    rows: dict[str, Row] = {}
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT keyword, geo_target, language, network,
                   recent_avg_monthly_searches, raw_avg_monthly_searches,
                   competition, competition_index,
                   low_top_of_page_bid_micros, high_top_of_page_bid_micros,
                   three_month_change, currency_code,
                   has_data, is_close_variant_merged, monthly_volumes,
                   fetched_at
            FROM keyword_cache
            WHERE keyword = ANY(%s)
              AND geo_target = %s
              AND language = %s
              AND network = %s
              AND fetched_at >= %s
            """,
            (unique, geo_target, language, network, cutoff),
        )
        for r in cur.fetchall():
            rows[r["keyword"]] = _row_from_db(r)

    missing = [k for k in unique if k not in rows]
    return rows, missing


_UPSERT_SQL = """
    INSERT INTO keyword_cache (
        keyword, geo_target, language, network,
        recent_avg_monthly_searches, raw_avg_monthly_searches,
        competition, competition_index,
        low_top_of_page_bid_micros, high_top_of_page_bid_micros,
        three_month_change, currency_code,
        has_data, is_close_variant_merged, monthly_volumes,
        fetched_at
    ) VALUES (%s,%s,%s,%s, %s,%s, %s,%s, %s,%s, %s,%s, %s,%s, %s, now())
    ON CONFLICT (keyword, geo_target, language, network) DO UPDATE SET
        recent_avg_monthly_searches = EXCLUDED.recent_avg_monthly_searches,
        raw_avg_monthly_searches    = EXCLUDED.raw_avg_monthly_searches,
        competition                 = EXCLUDED.competition,
        competition_index           = EXCLUDED.competition_index,
        low_top_of_page_bid_micros  = EXCLUDED.low_top_of_page_bid_micros,
        high_top_of_page_bid_micros = EXCLUDED.high_top_of_page_bid_micros,
        three_month_change          = EXCLUDED.three_month_change,
        currency_code               = EXCLUDED.currency_code,
        has_data                    = EXCLUDED.has_data,
        is_close_variant_merged     = EXCLUDED.is_close_variant_merged,
        monthly_volumes             = EXCLUDED.monthly_volumes,
        fetched_at                  = now()
"""


def upsert_rows(
    conn,
    rows: Iterable[Row],
    *,
    store_monthly_volumes: bool = False,
    batch_size: int = 500,
) -> int:
    """Bulk upsert via executemany batches. Avoids one-round-trip-per-row.

    Returns count upserted; commits at the end.
    """
    rows = list(rows)
    if not rows:
        return 0

    params = []
    for row in rows:
        monthly_json = None
        if store_monthly_volumes and row.monthly_volumes:
            monthly_json = json.dumps(
                [{"year": m.year, "month": m.month, "searches": m.searches}
                 for m in row.monthly_volumes]
            )
        params.append((
            row.keyword, row.geo_target, row.language, row.network,
            row.recent_avg_monthly_searches, row.raw_avg_monthly_searches,
            row.competition, row.competition_index,
            row.low_top_of_page_bid_micros, row.high_top_of_page_bid_micros,
            row.three_month_change, row.currency_code,
            row.has_data, row.is_close_variant_merged, monthly_json,
        ))

    with conn.cursor() as cur:
        for i in range(0, len(params), batch_size):
            cur.executemany(_UPSERT_SQL, params[i:i + batch_size])
    conn.commit()
    return len(rows)


def _row_from_db(r: dict) -> Row:
    monthly = None
    if r.get("monthly_volumes"):
        monthly = [MonthlyVolume(**m) for m in r["monthly_volumes"]]
    return Row(
        keyword=r["keyword"],
        geo_target=r["geo_target"],
        language=r["language"],
        network=r["network"],
        recent_avg_monthly_searches=r["recent_avg_monthly_searches"],
        raw_avg_monthly_searches=r["raw_avg_monthly_searches"],
        competition=r["competition"],
        competition_index=r["competition_index"],
        low_top_of_page_bid_micros=r["low_top_of_page_bid_micros"],
        high_top_of_page_bid_micros=r["high_top_of_page_bid_micros"],
        three_month_change=float(r["three_month_change"]) if r["three_month_change"] is not None else None,
        currency_code=r["currency_code"],
        has_data=r["has_data"],
        is_close_variant_merged=r["is_close_variant_merged"],
        monthly_volumes=monthly,
    )
