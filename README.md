# Bulk Keyword Research Tool

Internal tool for content arbitrage. Pulls Google Ads Keyword Planner data
(search volume + bid ranges) in bulk, plus a discovery tab. Single user,
key-gated, USA-targeted, INR currency. See `keyword-tool-spec.md` for the
locked spec.

## Status

Phase 0 (API smoke test) — in progress.

## Layout

See spec §8. Engine in `core/` has no Streamlit imports.

## Phase 0 — run the smoke test

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env  # fill in creds
python smoke_test.py             # core checks
python smoke_test.py --full      # also chunk-size + ideas-seed-cap probes
```
