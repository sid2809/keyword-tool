"""Historical metrics fetch — spec §4.2 / §5.3 / §5.4 / §5.5.

Pipeline:
  normalize → dedupe → cache lookup →
  chunk missing → rate-limit + retry call →
  map close-variants 1:1 → compute recent demand + 3-mo change →
  upsert → return {keyword: Row}.
"""
from __future__ import annotations

from collections import Counter
from typing import Callable, Optional

from .models import Row, MonthlyVolume
from . import cache as cache_mod
from . import _rpc

USA_GEO = "geoTargetConstants/2840"
LANG_ALL_SENTINEL = "ALL"      # what we store when the API field is omitted
NETWORK = "GOOGLE_SEARCH"


def fetch_historical_metrics(
    keywords: list[str],
    *,
    client,
    conn,
    customer_id: str,
    chunk_size: int = 10000,
    geo_target: str = USA_GEO,
    months: int = 6,
    cache_freshness_days: int = 30,
    store_monthly_volumes: bool = False,
    force_refresh: bool = False,
    currency_code: Optional[str] = None,
    progress_cb: Optional[Callable[[int, int], None]] = None,
) -> dict[str, Row]:
    """Return {normalized_keyword: Row} for every input keyword.

    progress_cb(chunks_done, chunks_total) is called once per chunk if provided.
    """
    # Normalize and preserve multiplicity for the caller's output expansion.
    normalized = [cache_mod.normalize(k) for k in keywords]
    multiplicity = Counter(normalized)
    unique_norm = list(multiplicity.keys())

    fresh, missing = cache_mod.lookup_fresh(
        conn,
        unique_norm,
        geo_target=geo_target,
        language=LANG_ALL_SENTINEL,
        network=NETWORK,
        max_age_days=cache_freshness_days,
        force_refresh=force_refresh,
    )

    if not missing:
        if progress_cb:
            progress_cb(0, 0)
        return fresh

    chunks = [missing[i:i + chunk_size] for i in range(0, len(missing), chunk_size)]
    total = len(chunks)
    fetched: dict[str, Row] = {}
    for idx, chunk in enumerate(chunks, start=1):
        results = _call_chunk(client, customer_id, chunk, geo_target, months)
        chunk_rows = _map_results_to_rows(
            results, chunk,
            geo_target=geo_target,
            currency_code=currency_code,
        )
        fetched.update(chunk_rows)
        if progress_cb:
            progress_cb(idx, total)

    # Upsert everything we fetched (cache hits already in DB; no need to re-write).
    cache_mod.upsert_rows(conn, fetched.values(), store_monthly_volumes=store_monthly_volumes)

    return {**fresh, **fetched}


def expand_to_output_rows(
    original_input: list[str],
    rows_by_keyword: dict[str, Row],
) -> list[tuple[str, Row]]:
    """Spec §4.5: iterate the original ordered input (with dupes); one output
    row per line via normalized lookup. Missing → synthetic no-data row.
    """
    out: list[tuple[str, Row]] = []
    for raw in original_input:
        norm = cache_mod.normalize(raw)
        row = rows_by_keyword.get(norm)
        if row is None:
            row = Row(keyword=norm, has_data=False)
        out.append((raw, row))
    return out


# ---------- internals ----------

def _call_chunk(client, customer_id: str, keywords: list[str], geo_target: str, months: int):
    """Issue ONE GenerateKeywordHistoricalMetrics call. Rate-limited + retried.

    Spec §1: language field omitted = all languages. We always omit.
    """
    svc = client.get_service("KeywordPlanIdeaService")

    def _do():
        _rpc.rate_limit()
        req = client.get_type("GenerateKeywordHistoricalMetricsRequest")
        req.customer_id = customer_id
        req.keywords.extend(keywords)
        if geo_target:
            req.geo_target_constants.append(geo_target)
        req.keyword_plan_network = client.enums.KeywordPlanNetworkEnum.GOOGLE_SEARCH
        req.historical_metrics_options.include_average_cpc = False
        if months:
            _rpc.set_year_month_range(client, req.historical_metrics_options, months)
        return svc.generate_keyword_historical_metrics(request=req)

    return _rpc.call_with_retry(_do).results


def _map_results_to_rows(
    results,
    requested_keywords: list[str],
    *,
    geo_target: str,
    currency_code: Optional[str],
) -> dict[str, Row]:
    """Map API results (which merge close-variants) back to 1:1 input keywords.

    Spec §5.5: variants are flagged is_close_variant_merged; canonical keeps the
    primary metrics; missing inputs get has_data=False.
    """
    requested = set(requested_keywords)
    rows: dict[str, Row] = {}

    for r in results:
        m = r.keyword_metrics
        canonical = r.text
        variants = list(r.close_variants)

        if not m:
            # Edge case: API returned the result but no metrics. Mark no-data
            # for canonical + variants that we actually asked about.
            for kw in [canonical, *variants]:
                if kw in requested and kw not in rows:
                    rows[kw] = Row(
                        keyword=kw,
                        geo_target=geo_target,
                        currency_code=currency_code,
                        has_data=False,
                        is_close_variant_merged=(kw != canonical),
                    )
            continue

        monthly = [
            MonthlyVolume(year=s.year, month=_rpc.month_num(s.month), searches=s.monthly_searches)
            for s in m.monthly_search_volumes
        ]
        recent = _recent_demand(monthly)
        change = _three_month_change(monthly)
        comp_name = m.competition.name if hasattr(m.competition, "name") else str(m.competition)

        for kw in [canonical, *variants]:
            if kw not in requested or kw in rows:
                continue
            rows[kw] = Row(
                keyword=kw,
                geo_target=geo_target,
                language=LANG_ALL_SENTINEL,
                network=NETWORK,
                recent_avg_monthly_searches=recent,
                raw_avg_monthly_searches=m.avg_monthly_searches,
                competition=comp_name,
                competition_index=m.competition_index,
                low_top_of_page_bid_micros=m.low_top_of_page_bid_micros,
                high_top_of_page_bid_micros=m.high_top_of_page_bid_micros,
                three_month_change=change,
                currency_code=currency_code,
                has_data=True,
                is_close_variant_merged=(kw != canonical),
                monthly_volumes=monthly,
            )

    # Any requested keyword the API never mentioned → no-data row.
    for kw in requested_keywords:
        if kw not in rows:
            rows[kw] = Row(
                keyword=kw,
                geo_target=geo_target,
                language=LANG_ALL_SENTINEL,
                network=NETWORK,
                currency_code=currency_code,
                has_data=False,
            )

    return rows


def _recent_demand(monthly: list[MonthlyVolume]) -> Optional[int]:
    """Spec §5.3: mean of the last 3 months that have data."""
    if not monthly:
        return None
    sorted_mv = sorted(monthly, key=lambda m: (m.year, m.month))
    last3 = sorted_mv[-3:]
    if not last3:
        return None
    return int(round(sum(m.searches for m in last3) / len(last3)))


def _three_month_change(monthly: list[MonthlyVolume]) -> Optional[float]:
    """Spec §5.4: (latest − month_3_prior) / month_3_prior * 100. None if ref is 0/missing."""
    if not monthly:
        return None
    sorted_mv = sorted(monthly, key=lambda m: (m.year, m.month))
    if len(sorted_mv) < 4:
        return None
    latest = sorted_mv[-1].searches
    ref = sorted_mv[-4].searches
    if not ref:
        return None
    return round((latest - ref) / ref * 100, 4)
