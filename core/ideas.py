"""Keyword ideas fetch — spec §4.3.

One seed (keyword list OR url OR keyword+url OR site); paginate; same
geo/lang/network/window as metrics.py. Adult keywords off.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional

from .models import Row, MonthlyVolume
from . import cache as cache_mod
from . import _rpc
from .metrics import (
    USA_GEO, LANG_ALL_SENTINEL, NETWORK,
    _recent_demand, _three_month_change,
)


@dataclass
class IdeaSeed:
    """Exactly one of these is populated. Spec §1 Method B."""
    keywords: Optional[list[str]] = None        # keyword_seed
    url: Optional[str] = None                   # url_seed (single URL)
    site: Optional[str] = None                  # site_seed (whole domain)

    def validate(self) -> None:
        filled = [v for v in (self.keywords, self.url, self.site) if v]
        if len(filled) == 0:
            raise ValueError("IdeaSeed requires keywords, url, or site")
        if len(filled) > 1 and not (self.keywords and self.url and not self.site):
            # keywords + url combo is the only valid pair (keyword_and_url_seed)
            raise ValueError("IdeaSeed must be one type, or keywords+url combo")
        if self.keywords and len(self.keywords) > 20:
            raise ValueError("keyword_seed supports at most 20 keywords (Phase 0 confirmed)")


def fetch_keyword_ideas(
    seed: IdeaSeed,
    *,
    client,
    conn,
    customer_id: str,
    geo_target: str = USA_GEO,
    months: int = 6,
    store_monthly_volumes: bool = False,
    currency_code: Optional[str] = None,
    progress_cb: Optional[Callable[[int], None]] = None,
    upsert_cb: Optional[Callable[[int], None]] = None,
    max_ideas: int = 10000,
) -> list[Row]:
    """Run one ideas call; paginate up to max_ideas; bulk-upsert; return rows.

    progress_cb(seen) is called every ~100 ideas during streaming.
    upsert_cb(count) is called once just before the DB write.
    """
    seed.validate()

    svc = client.get_service("KeywordPlanIdeaService")

    def _do():
        _rpc.rate_limit()
        req = client.get_type("GenerateKeywordIdeasRequest")
        req.customer_id = customer_id
        req.geo_target_constants.append(geo_target)
        req.keyword_plan_network = client.enums.KeywordPlanNetworkEnum.GOOGLE_SEARCH
        req.include_adult_keywords = False
        _rpc.set_year_month_range(client, req.historical_metrics_options, months)
        req.historical_metrics_options.include_average_cpc = False

        if seed.keywords and seed.url:
            req.keyword_and_url_seed.url = seed.url
            req.keyword_and_url_seed.keywords.extend(seed.keywords)
        elif seed.keywords:
            req.keyword_seed.keywords.extend(seed.keywords)
        elif seed.url:
            req.url_seed.url = seed.url
        elif seed.site:
            req.site_seed.site = seed.site
        return svc.generate_keyword_ideas(request=req)

    response = _rpc.call_with_retry(_do)

    rows: list[Row] = []
    for idx, idea in enumerate(response):
        if len(rows) >= max_ideas:
            break
        row = _row_from_idea(idea, geo_target, currency_code)
        rows.append(row)
        if progress_cb and idx % 100 == 0:
            progress_cb(idx)

    if upsert_cb:
        upsert_cb(len(rows))
    cache_mod.upsert_rows(conn, rows, store_monthly_volumes=store_monthly_volumes)
    return rows


def _row_from_idea(idea, geo_target: str, currency_code: Optional[str]) -> Row:
    m = idea.keyword_idea_metrics
    text = cache_mod.normalize(idea.text)
    if not m:
        return Row(
            keyword=text,
            geo_target=geo_target,
            language=LANG_ALL_SENTINEL,
            network=NETWORK,
            currency_code=currency_code,
            has_data=False,
        )

    monthly = [
        MonthlyVolume(year=s.year, month=_rpc.month_num(s.month), searches=s.monthly_searches)
        for s in m.monthly_search_volumes
    ]
    comp_name = m.competition.name if hasattr(m.competition, "name") else str(m.competition)
    return Row(
        keyword=text,
        geo_target=geo_target,
        language=LANG_ALL_SENTINEL,
        network=NETWORK,
        recent_avg_monthly_searches=_recent_demand(monthly),
        raw_avg_monthly_searches=m.avg_monthly_searches,
        competition=comp_name,
        competition_index=m.competition_index,
        low_top_of_page_bid_micros=m.low_top_of_page_bid_micros,
        high_top_of_page_bid_micros=m.high_top_of_page_bid_micros,
        three_month_change=_three_month_change(monthly),
        currency_code=currency_code,
        has_data=True,
        is_close_variant_merged=False,
        monthly_volumes=monthly,
    )
