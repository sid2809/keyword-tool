"""Phase 0 API smoke test — Bulk Keyword Research Tool.

Verifies §9 checks (a)–(k) before any Phase 1 work. Uses the engine layer
(core/google_ads_client.py) directly; no UI, no DB.

Usage:
    python smoke_test.py                # core checks only (cheap)
    python smoke_test.py --full         # also run heavy probes (chunk size, seed cap)
"""
from __future__ import annotations

import datetime
import sys
import time
import traceback
from typing import Optional

from config import Config
from core.google_ads_client import build_client, get_account_currency

USA_GEO = "geoTargetConstants/2840"
ENGLISH_LANG = "languageConstants/1000"
RATE_LIMIT_SECONDS = 1.1  # spec §5.2 says ≥1.05; pad slightly

_MONTH_NAMES = [
    "JANUARY", "FEBRUARY", "MARCH", "APRIL", "MAY", "JUNE",
    "JULY", "AUGUST", "SEPTEMBER", "OCTOBER", "NOVEMBER", "DECEMBER",
]

_last_call_ts = 0.0


def rate_limit() -> None:
    global _last_call_ts
    now = time.monotonic()
    delta = now - _last_call_ts
    if delta < RATE_LIMIT_SECONDS:
        time.sleep(RATE_LIMIT_SECONDS - delta)
    _last_call_ts = time.monotonic()


def banner(title: str) -> None:
    print()
    print("=" * 72)
    print(title)
    print("=" * 72)


def month_num(month_value) -> int:
    """Map MonthOfYear enum (or int) → 1..12."""
    if hasattr(month_value, "name"):
        return _MONTH_NAMES.index(month_value.name) + 1
    if isinstance(month_value, int):
        # API enum: UNSPECIFIED=0, UNKNOWN=1, JANUARY=2..DECEMBER=13
        if 2 <= month_value <= 13:
            return month_value - 1
        return 0
    return 0


def month_str(month_value) -> str:
    n = month_num(month_value)
    return _MONTH_NAMES[n - 1] if 1 <= n <= 12 else f"?({month_value})"


def micros_to_inr(m: Optional[int]) -> str:
    if not m:
        return "—"
    return f"₹{m / 1_000_000:.2f}"


def set_year_month_range(client, options, months_back: int):
    """Populate options.year_month_range (proto-plus: assign fields directly).

    Returns ((start_year, start_month), (end_year, end_month)) for logging.
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
    return (start_year, start_month), (end_year, end_month)


def call_historical(client, customer_id, keywords,
                    geo: Optional[str] = USA_GEO,
                    language: Optional[str] = None,
                    months: int = 6):
    rate_limit()
    svc = client.get_service("KeywordPlanIdeaService")
    req = client.get_type("GenerateKeywordHistoricalMetricsRequest")
    req.customer_id = customer_id
    req.keywords.extend(keywords)
    if geo:
        req.geo_target_constants.append(geo)
    if language:
        req.language = language
    req.keyword_plan_network = client.enums.KeywordPlanNetworkEnum.GOOGLE_SEARCH
    req.historical_metrics_options.include_average_cpc = False
    if months:
        set_year_month_range(client, req.historical_metrics_options, months)
    return svc.generate_keyword_historical_metrics(request=req)


# ---------- Checks ----------

def check_currency(client, cid):
    banner("(b) Currency check  —  customer.currency_code")
    code = get_account_currency(client, cid)
    print(f"  currency_code = {code!r}")
    if code == "INR":
        print("  ✓ INR confirmed (spec assumes INR).")
    else:
        print(f"  ⚠  Expected INR, got {code}. Bid math assumes INR.")
    return code


def check_basic_call(client, cid):
    banner("(a)(c)(d)(e) Basic historical call  —  USA, language omitted")
    keywords = ["car insurance", "best mattress", "personal loan",
                "yoga teacher training", "credit card"]
    print(f"  keywords: {keywords}")
    print(f"  geo={USA_GEO}, language=<omitted>, network=GOOGLE_SEARCH, window=6mo")
    response = call_historical(client, cid, keywords)
    results = list(response.results)
    print(f"\n  results returned: {len(results)}")
    for r in results:
        m = r.keyword_metrics
        print(f"\n  • {r.text!r}  has_metrics={bool(m)}")
        if r.close_variants:
            print(f"     close_variants: {list(r.close_variants)}")
        if not m:
            continue
        print(f"     avg_monthly_searches = {m.avg_monthly_searches}")
        print(f"     competition          = {m.competition.name}  index={m.competition_index}")
        print(f"     low_top_of_page_bid  = {m.low_top_of_page_bid_micros}  ({micros_to_inr(m.low_top_of_page_bid_micros)})")
        print(f"     high_top_of_page_bid = {m.high_top_of_page_bid_micros}  ({micros_to_inr(m.high_top_of_page_bid_micros)})")
        series = list(m.monthly_search_volumes)
        print(f"     monthly_search_volumes ({len(series)}):")
        for s in series:
            print(f"        {s.year}-{month_str(s.month):>9}: {s.monthly_searches}")
    print("\n  Interpretation guide:")
    print("    (a) ✓ if has_metrics=True for known commercial keywords")
    print("    (c) ✓ if bid_micros are large 6–8 digit numbers (e.g. 5000000 = ₹5.00)")
    print("    (d) ✓ if avg_monthly_searches looks like a precise integer, not 10/100/1k/10k buckets")
    print("    (e) ✓ if ~6 monthly_search_volumes entries returned")
    return results


def check_three_month_change(results):
    banner("(i) Three-month-change computation  —  verify ONE against UI")
    print("  Formula: (latest_month − month_3_prior) / month_3_prior × 100")
    for r in results:
        m = r.keyword_metrics
        if not m or not m.monthly_search_volumes:
            print(f"  {r.text!r}: no series.")
            continue
        series = sorted(list(m.monthly_search_volumes),
                        key=lambda s: (s.year, month_num(s.month)))
        if len(series) < 4:
            print(f"  {r.text!r}: only {len(series)} points — cannot compute.")
            continue
        latest = series[-1]
        ref = series[-4]
        ref_val = ref.monthly_searches
        latest_val = latest.monthly_searches
        if not ref_val:
            print(f"  {r.text!r}: ref month is 0 — change undefined.")
            continue
        change = (latest_val - ref_val) / ref_val * 100
        print(f"  {r.text!r}: latest={latest_val} ({latest.year}-{month_str(latest.month)})  "
              f"ref={ref_val} ({ref.year}-{month_str(ref.month)})  Δ={change:+.2f}%")
    print("\n  ACTION: open Google Ads Keyword Planner UI for one keyword above,")
    print("          read its '3 month change', confirm ours matches.")


def check_close_variants(client, cid):
    banner("(f) Close-variant grouping  —  send 4 variations")
    keywords = ["car insurance", "car insurances",
                "auto insurance", "automobile insurance"]
    print(f"  inputs: {keywords}")
    response = call_historical(client, cid, keywords)
    results = list(response.results)
    print(f"  results returned: {len(results)} (vs {len(keywords)} inputs)")
    for r in results:
        m = r.keyword_metrics
        v = list(r.close_variants)
        print(f"    text={r.text!r}  variants={v}  "
              f"avg={m.avg_monthly_searches if m else None}")
    print("\n  ✓ if results < inputs AND some result has non-empty close_variants[].")
    print("    That tells us Google merges, and we can 1:1-map each input via the variants array (spec §5.5).")


def check_language_omit_vs_english(client, cid):
    banner("(j) Language: omitted vs explicit English  —  incl. Spanish queries")
    # English queries (baseline) + Spanish queries (decisive: should differ if omit = all-langs)
    keywords = [
        "cricket",                # English baseline
        "car insurance",          # English baseline
        "seguro de auto",         # Spanish: "auto insurance"
        "comprar casa",           # Spanish: "buy house"
        "noticias",               # Spanish: "news"
    ]
    print("  Call 1: language omitted ...")
    r_omit = list(call_historical(client, cid, keywords, language=None).results)
    print("  Call 2: language=languageConstants/1000 (English) ...")
    r_en = list(call_historical(client, cid, keywords, language=ENGLISH_LANG).results)
    by_omit = {r.text: (r.keyword_metrics.avg_monthly_searches if r.keyword_metrics else None)
               for r in r_omit}
    by_en = {r.text: (r.keyword_metrics.avg_monthly_searches if r.keyword_metrics else None)
             for r in r_en}
    for k in keywords:
        o = by_omit.get(k)
        e = by_en.get(k)
        if o is None and e is None:
            verdict = "NO DATA both"
        elif o == e:
            verdict = "match"
        else:
            verdict = "DIFFER"
        print(f"    {k!r:24}  omit={o}  english={e}  → {verdict}")
    print("\n  Interpretation:")
    print("    DIFFER on any Spanish query (esp. omit > english) → omit = all-languages. ✓")
    print("    Match on Spanish queries too → omit defaults to English. Spec assumption wrong.")


def check_geo_takes_effect(client, cid):
    banner("(j) Geo: USA vs no-geo  —  expect volumes to differ")
    keywords = ["cricket"]  # India-heavy globally → USA should be much smaller
    print("  Call 1: geo=USA (2840) ...")
    r_us = list(call_historical(client, cid, keywords, geo=USA_GEO).results)
    print("  Call 2: geo omitted (global) ...")
    r_g = list(call_historical(client, cid, keywords, geo=None).results)
    us = r_us[0].keyword_metrics.avg_monthly_searches if r_us and r_us[0].keyword_metrics else None
    glb = r_g[0].keyword_metrics.avg_monthly_searches if r_g and r_g[0].keyword_metrics else None
    print(f"    'cricket': usa={us}  global={glb}")
    if us is not None and glb is not None:
        if us < glb:
            print("  ✓ USA < global — geo is taking effect.")
        elif us == glb:
            print("  ⚠ Identical. Geo may not be applied. Investigate.")
        else:
            print("  ?  USA > global. Unexpected — investigate.")


def check_ideas_call(client, cid):
    banner("(h) Ideas call  —  seed=keyword, iterate first ~100")
    svc = client.get_service("KeywordPlanIdeaService")
    req = client.get_type("GenerateKeywordIdeasRequest")
    req.customer_id = cid
    req.keyword_seed.keywords.append("car insurance")
    req.geo_target_constants.append(USA_GEO)
    req.keyword_plan_network = client.enums.KeywordPlanNetworkEnum.GOOGLE_SEARCH
    req.include_adult_keywords = False
    set_year_month_range(client, req.historical_metrics_options, 6)
    req.historical_metrics_options.include_average_cpc = False
    rate_limit()
    response = svc.generate_keyword_ideas(request=req)
    sample = []
    count = 0
    for idea in response:
        count += 1
        if count <= 5:
            m = idea.keyword_idea_metrics
            sample.append((idea.text,
                           m.avg_monthly_searches if m else None,
                           m.competition.name if m else None))
        if count >= 100:
            break
    print(f"  iterated {count} ideas (capped at 100 for smoke).")
    for s in sample:
        print(f"    {s}")
    print("\n  ✓ if count > 0 and metrics populated.")


def check_chunk_size_probe(client, cid):
    banner("(g) Chunk-size probe  —  escalate batch size")
    seeds = ["best", "cheap", "buy", "review", "price", "near me",
             "online", "free", "vs", "how to"]
    nouns = ["car", "phone", "laptop", "shoes", "watch", "mattress",
             "loan", "insurance", "vpn", "hosting", "headphones", "tv",
             "camera", "tablet", "earbuds", "course", "book", "guitar",
             "monitor", "printer"]
    base = [f"{s} {n}" for s in seeds for n in nouns]
    extra = [f"{n} {y}" for n in nouns
             for y in ["2024", "2025", "2026", "price", "review",
                       "deals", "amazon", "walmart", "sale", "brand",
                       "near me", "online", "cheap", "best", "vs"]]
    pool = list(dict.fromkeys(base + extra))  # dedupe, preserve order
    print(f"  pool size = {len(pool)}")
    last_ok = None
    for n in [1000, 2500, 5000, 10000, 20000]:
        if n > len(pool):
            # Pad with synthetic but plausibly-formed keywords
            extras = [f"{base[i % len(base)]} v{i}" for i in range(n - len(pool))]
            sample = pool + extras
            sample = sample[:n]
        else:
            sample = pool[:n]
        print(f"\n  → trying n={n} ({len(sample)} unique={len(set(sample))})")
        try:
            response = call_historical(client, cid, sample)
            results = list(response.results)
            print(f"    ✓ accepted, {len(results)} results returned")
            last_ok = n
        except Exception as e:
            print(f"    ✗ rejected — {type(e).__name__}: {str(e)[:300]}")
            break
    print(f"\n  Max batch size that succeeded: {last_ok}")


def check_ideas_seed_cap(client, cid):
    banner("(h) Ideas seed-cap probe")
    base = ["best laptop", "cheap car insurance", "buy phone", "how to invest",
            "vpn review", "online courses", "weight loss", "keto diet",
            "running shoes", "credit cards", "yoga teacher training",
            "meditation app", "gaming chair", "mechanical keyboard",
            "noise cancelling headphones", "cordless vacuum", "robot vacuum",
            "air purifier", "smart watch", "fitness tracker"]
    svc = client.get_service("KeywordPlanIdeaService")
    last_ok = None
    for n in [1, 5, 10, 20, 50, 100]:
        seeds = (base * 10)[:n]
        req = client.get_type("GenerateKeywordIdeasRequest")
        req.customer_id = cid
        req.keyword_seed.keywords.extend(seeds)
        req.geo_target_constants.append(USA_GEO)
        req.keyword_plan_network = client.enums.KeywordPlanNetworkEnum.GOOGLE_SEARCH
        req.include_adult_keywords = False
        set_year_month_range(client, req.historical_metrics_options, 6)
        req.historical_metrics_options.include_average_cpc = False
        rate_limit()
        try:
            response = svc.generate_keyword_ideas(request=req)
            # Pull just first idea to confirm streaming works
            it = iter(response)
            next(it, None)
            print(f"  ✓ {n} seeds accepted")
            last_ok = n
        except Exception as e:
            print(f"  ✗ {n} seeds rejected — {type(e).__name__}: {str(e)[:200]}")
            break
    print(f"\n  Max seeds accepted: {last_ok}")


def main():
    print("Phase 0 smoke test — Bulk Keyword Research Tool")
    cfg = Config.from_env()
    print(f"  operating customer_id = {cfg.customer_id}")
    print(f"  login_customer_id (MCC) = {cfg.login_customer_id}")
    client = build_client(cfg.google_ads_credentials())

    try:
        check_currency(client, cfg.customer_id)
    except Exception:
        traceback.print_exc()

    try:
        results = check_basic_call(client, cfg.customer_id)
    except Exception:
        traceback.print_exc()
        results = []

    try:
        check_three_month_change(results)
    except Exception:
        traceback.print_exc()

    try:
        check_close_variants(client, cfg.customer_id)
    except Exception:
        traceback.print_exc()

    try:
        check_language_omit_vs_english(client, cfg.customer_id)
    except Exception:
        traceback.print_exc()

    try:
        check_geo_takes_effect(client, cfg.customer_id)
    except Exception:
        traceback.print_exc()

    try:
        check_ideas_call(client, cfg.customer_id)
    except Exception:
        traceback.print_exc()

    if "--full" in sys.argv:
        try:
            check_chunk_size_probe(client, cfg.customer_id)
        except Exception:
            traceback.print_exc()
        try:
            check_ideas_seed_cap(client, cfg.customer_id)
        except Exception:
            traceback.print_exc()
    else:
        banner("Skipped: --full not passed")
        print("  Heavy probes (chunk size, ideas seed cap) skipped.")
        print("  Re-run with `python smoke_test.py --full` once core checks look right.")

    print("\nDone.")


if __name__ == "__main__":
    main()
