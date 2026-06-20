"""Phase 1 CLI gate: 50-keyword run end-to-end.

Acceptance (spec §9 Phase 1 Gate):
  - 50-keyword run returns correct ₹ + recent demand + 3-month change.
  - Second run serves from cache with 0 API calls.

Usage:
    python run_phase1.py                       # default 50-keyword list
    python run_phase1.py --keywords-file=foo   # one keyword per line
    python run_phase1.py --force               # bypass cache (refetch all)
    python run_phase1.py --ideas-seed="car insurance"   # also run an ideas call
"""
from __future__ import annotations

import argparse
import sys
import time

from config import Config
from db import connect, init_schema
from core import _rpc
from core.google_ads_client import build_client, get_account_currency
from core.metrics import fetch_historical_metrics, expand_to_output_rows
from core.ideas import fetch_keyword_ideas, IdeaSeed


DEFAULT_KEYWORDS = [
    "car insurance", "auto insurance", "best mattress", "memory foam mattress",
    "personal loan", "home loan", "credit card", "credit card offers",
    "yoga teacher training", "online yoga course", "vpn", "best vpn",
    "web hosting", "cheap web hosting", "noise cancelling headphones",
    "wireless earbuds", "running shoes", "best running shoes",
    "meal kit delivery", "blue apron", "weight loss program", "keto diet plan",
    "life insurance", "term life insurance", "health insurance",
    "dental insurance", "pet insurance", "home insurance", "renters insurance",
    "business loan", "small business loan", "student loan refinance",
    "mortgage rates", "refinance mortgage", "robo advisor", "investment app",
    "stock trading app", "high yield savings", "online checking account",
    "best smartphone", "cheap laptop", "gaming pc", "mechanical keyboard",
    "smart watch", "fitness tracker", "air purifier", "robot vacuum",
    "online courses", "language learning app", "meditation app",
]


def _fmt_inr(micros):
    return f"₹{micros / 1_000_000:.2f}" if micros else "—"


def _fmt_change(c):
    return f"{c:+.2f}%" if c is not None else "—"


class CallCounter:
    """Wraps _rpc.rate_limit to count how many times we actually rate-limited
    (i.e. how many keyword-planning API calls were issued in this run)."""
    def __init__(self):
        self.count = 0
        self._real = _rpc.rate_limit

    def __enter__(self):
        def wrapped():
            self.count += 1
            self._real()
        _rpc.rate_limit = wrapped
        return self

    def __exit__(self, *exc):
        _rpc.rate_limit = self._real


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--keywords-file")
    p.add_argument("--force", action="store_true", help="Bypass cache (force refresh).")
    p.add_argument("--ideas-seed", help="Run an ideas call with this seed keyword too.")
    p.add_argument("--clear-cache", action="store_true",
                   help="Wipe keyword_cache before running (for a clean gate test).")
    args = p.parse_args()

    cfg = Config.from_env()
    init_schema(cfg.database_url)

    if args.keywords_file:
        with open(args.keywords_file) as f:
            keywords = [line.strip() for line in f if line.strip()]
    else:
        keywords = DEFAULT_KEYWORDS[:50]

    print(f"Phase 1 — historical metrics for {len(keywords)} keywords")
    if args.force:
        print("  --force: bypassing cache")

    client = build_client(cfg.google_ads_credentials())
    currency = get_account_currency(client, cfg.customer_id)
    print(f"  account currency: {currency}")

    with connect(cfg.database_url) as conn:
        if args.clear_cache:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM keyword_cache")
                print(f"  cleared keyword_cache ({cur.rowcount} rows)")
            conn.commit()

        t0 = time.time()
        with CallCounter() as cc:
            def progress(done, total, phase="done", chunk_n=0):
                if total and phase == "done":
                    print(f"  chunk {done}/{total} done")
            rows_by_kw = fetch_historical_metrics(
                keywords,
                client=client,
                conn=conn,
                customer_id=cfg.customer_id,
                chunk_size=cfg.chunk_size,
                months=cfg.historical_window_months,
                cache_freshness_days=cfg.cache_freshness_days,
                store_monthly_volumes=cfg.store_monthly_volumes,
                force_refresh=args.force,
                currency_code=currency,
                progress_cb=progress,
            )
        elapsed = time.time() - t0

        api_calls = cc.count
        output = expand_to_output_rows(keywords, rows_by_kw)

        print(f"\n  done in {elapsed:.2f}s — API calls issued: {api_calls}")
        print(f"  unique normalized keywords resolved: {len(rows_by_kw)}")

        # Pretty-print first 20 rows
        print("\n  Sample (first 20 outputs):")
        print(f"    {'keyword':32}  {'recent_avg':>11}  {'Δ3mo':>9}  {'comp':6}  {'low ₹':>10}  {'high ₹':>10}  flags")
        print("    " + "-" * 110)
        for inp, row in output[:20]:
            recent = row.recent_avg_monthly_searches if row.recent_avg_monthly_searches is not None else "—"
            flags = []
            if not row.has_data:
                flags.append("NO-DATA")
            if row.is_close_variant_merged:
                flags.append("MERGED")
            print(f"    {inp[:32]:32}  {str(recent):>11}  {_fmt_change(row.three_month_change):>9}  "
                  f"{(row.competition or '—'):6}  "
                  f"{_fmt_inr(row.low_top_of_page_bid_micros):>10}  "
                  f"{_fmt_inr(row.high_top_of_page_bid_micros):>10}  "
                  f"{','.join(flags)}")

        # DB sanity
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) AS n FROM keyword_cache")
            n = cur.fetchone()["n"]
            print(f"\n  keyword_cache rows: {n}")

        # Ideas (optional)
        if args.ideas_seed:
            print(f"\n  Ideas call for seed: {args.ideas_seed!r}")
            with CallCounter() as cc2:
                ideas_rows = fetch_keyword_ideas(
                    IdeaSeed(keywords=[args.ideas_seed]),
                    client=client,
                    conn=conn,
                    customer_id=cfg.customer_id,
                    months=cfg.historical_window_months,
                    store_monthly_volumes=cfg.store_monthly_volumes,
                    currency_code=currency,
                )
            print(f"  → {len(ideas_rows)} ideas returned, {cc2.count} API call(s).")
            for r in ideas_rows[:10]:
                print(f"    {r.keyword!r:40}  recent={r.recent_avg_monthly_searches}  "
                      f"comp={r.competition}  high={_fmt_inr(r.high_top_of_page_bid_micros)}")

    print("\n  Done.")
    if api_calls == 0:
        print("  ✓ Phase 1 cache-hit gate: 0 API calls on this run.")


if __name__ == "__main__":
    sys.exit(main() or 0)
