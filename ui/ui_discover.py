"""Discover tab — spec §6 Tab 2.

Seed = keywords (≤20) and/or a page URL. Auto-pick seed type. One ideas call,
paginated by the SDK. Same filters, shortlist, save, and CSV download.
"""
from __future__ import annotations

import io

import pandas as pd
import streamlit as st

import db
import export
from core import cache as cache_mod
from core.ideas import IdeaSeed, fetch_keyword_ideas
from core.models import Row, row_to_dict, row_from_dict
from ui import _theme


COMPETITION_DISPLAY = {"LOW": "Low", "MEDIUM": "Medium", "HIGH": "High"}
SEED_KW_MAX = 20  # Phase 0 confirmed cap
RESULTS_DISPLAY_CAP = 5000  # safety cap so the table stays responsive


def render(cfg, client, conn):
    with st.container(border=True):
        _theme.section_title("Seed")
        col1, col2 = st.columns([2, 1])
        with col1:
            seed_kws_text = st.text_area(
                f"Seed keywords (one per line, max {SEED_KW_MAX})",
                height=190,
                key="discover_seed_kws",
                placeholder="car insurance\nauto insurance",
                label_visibility="collapsed",
            )
        with col2:
            seed_url = st.text_input(
                "Or a single page URL",
                key="discover_seed_url",
                placeholder="https://www.example.com/some-page",
            )
            seed_kws = _parse_seed_keywords(seed_kws_text)
            seed_kind = _decide_seed_kind(seed_kws, seed_url)
            disabled = (not seed_kind) or (seed_kws and len(seed_kws) > SEED_KW_MAX)
            run_clicked = st.button("Discover", type="primary", key="discover_run",
                                    disabled=disabled, use_container_width=True)

        if seed_kws and len(seed_kws) > SEED_KW_MAX:
            st.error(f"Too many seed keywords: {len(seed_kws)}. Max is {SEED_KW_MAX}.")
        st.caption(
            f"Seed type: **{seed_kind or '— none —'}**  ·  keywords: {len(seed_kws)}  "
            f"·  url: {'yes' if seed_url else 'no'}"
        )

    if run_clicked:
        _run_discover(cfg, client, conn, seed_kws, seed_url)

    rows = st.session_state.get("discover_rows")
    if not rows:
        st.caption("Run a discovery to see ideas here.")
    else:
        _render_results(cfg, conn, rows)

    _render_saved_searches(cfg, conn)


def _parse_seed_keywords(text: str) -> list[str]:
    out: list[str] = []
    for line in (text or "").splitlines():
        s = line.strip()
        if s:
            out.append(s)
    return out


def _decide_seed_kind(seed_kws: list[str], seed_url: str) -> str | None:
    has_kw = bool(seed_kws)
    has_url = bool(seed_url and seed_url.strip())
    if has_kw and has_url:
        return "keywords + URL"
    if has_kw:
        return "keywords"
    if has_url:
        return "URL"
    return None


def _run_discover(cfg, client, conn, seed_kws: list[str], seed_url: str):
    seed = IdeaSeed(
        keywords=seed_kws or None,
        url=seed_url.strip() or None if seed_url else None,
    )
    try:
        seed.validate()
    except Exception as e:
        st.error(f"Invalid seed: {e}")
        return

    currency = st.session_state.get("currency_code")
    if not currency:
        from core.google_ads_client import get_account_currency
        currency = get_account_currency(client, cfg.customer_id)
        st.session_state["currency_code"] = currency

    MAX_IDEAS = 10000
    progress = st.progress(0.0, text="Calling Google Ads…")
    def cb(seen):
        frac = min(0.95, seen / float(MAX_IDEAS))
        progress.progress(frac, text=f"Streaming ideas… ({seen:,} so far, cap {MAX_IDEAS:,})")

    def upsert_cb(n):
        progress.progress(0.97, text=f"Writing {n:,} rows to cache…")

    try:
        rows = fetch_keyword_ideas(
            seed,
            client=client,
            conn=conn,
            customer_id=cfg.customer_id,
            months=cfg.historical_window_months,
            store_monthly_volumes=cfg.store_monthly_volumes,
            currency_code=currency,
            progress_cb=cb,
            upsert_cb=upsert_cb,
            max_ideas=MAX_IDEAS,
        )
    except Exception as e:
        progress.empty()
        st.error(f"API call failed: {type(e).__name__}: {e}")
        return

    progress.progress(1.0, text=f"Got {len(rows):,} ideas. Done.")
    progress.empty()
    st.session_state["discover_rows"] = rows
    st.session_state["discover_input"] = {"keywords": seed_kws, "url": seed_url}

    # Auto-save every successful run, including the output snapshot.
    seed_count = len(seed_kws or []) + (1 if (seed_url or "").strip() else 0)
    snapshot = {"ideas": [row_to_dict(r) for r in rows]}
    sid = db.save_search(
        conn,
        label=None,
        tab="discover",
        input_count=seed_count,
        filters={},
        input_data={"keywords": seed_kws, "url": seed_url},
        output_data=snapshot,
    )
    st.session_state["discover_last_search_id"] = sid
    st.success(f"Got {len(rows)} ideas.")


def _rows_to_df(rows: list[Row]) -> pd.DataFrame:
    out = []
    for r in rows:
        out.append({
            "Keyword": r.keyword,
            "Avg searches (last 3mo)": r.recent_avg_monthly_searches,
            "3 month change (%)": r.three_month_change,
            "Competition": COMPETITION_DISPLAY.get(r.competition or "", r.competition or ""),
            "Low bid (₹)": (r.low_top_of_page_bid_micros / 1_000_000) if r.low_top_of_page_bid_micros else None,
            "High bid (₹)": (r.high_top_of_page_bid_micros / 1_000_000) if r.high_top_of_page_bid_micros else None,
            "Status": "No data" if not r.has_data else "",
            "_row": r,
        })
    return pd.DataFrame(out)


def _render_results(cfg, conn, rows: list[Row]):
    df = _rows_to_df(rows)

    # Summary tiles
    n_total = len(df)
    n_data = int(df["_row"].apply(lambda r: r.has_data).sum())
    avg_s = df["Avg searches (last 3mo)"].dropna().mean() if n_data else 0
    high_bid_med = df["High bid (₹)"].dropna().median() if n_data else 0

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Ideas returned", f"{n_total:,}")
    m2.metric("With data", f"{n_data:,}")
    m3.metric("Avg searches (mean)", f"{int(avg_s):,}" if avg_s else "—")
    m4.metric("Median high bid", f"₹{high_bid_med:,.0f}" if high_bid_med else "—")

    with st.container(border=True):
        _theme.section_title("Filters")
        fc1, fc2, fc3 = st.columns(3)
        with fc1:
            min_searches = st.number_input(
                "Min avg searches (last 3mo)",
                min_value=0, value=0, step=100, key="discover_filter_min",
            )
        with fc2:
            max_high_bid = st.number_input(
                "Max high bid (₹)",
                min_value=0.0, value=0.0, step=10.0, key="discover_filter_bid",
                help="0 = no limit",
            )
        with fc3:
            comp_options = ["Low", "Medium", "High"]
            comp_selected = st.multiselect(
                "Competition", comp_options, default=comp_options, key="discover_filter_comp",
            )

    mask = pd.Series([True] * len(df))
    if min_searches > 0:
        mask &= df["Avg searches (last 3mo)"].fillna(-1) >= min_searches
    if max_high_bid > 0:
        mask &= df["High bid (₹)"].fillna(float("inf")) <= max_high_bid
    if comp_selected and len(comp_selected) < 3:
        mask &= df["Competition"].isin(comp_selected)
    filtered = df[mask].copy()

    capped = False
    if len(filtered) > RESULTS_DISPLAY_CAP:
        capped = True
        filtered = filtered.head(RESULTS_DISPLAY_CAP)

    cap_note = f" (showing first {RESULTS_DISPLAY_CAP:,})" if capped else ""
    st.caption(f"Showing {len(filtered):,} of {len(df):,} ideas after filters{cap_note}.")

    sl_keywords = db.shortlist_keywords(conn)
    filtered["Shortlist"] = filtered["Keyword"].apply(lambda k: k in sl_keywords)

    display_cols = ["Shortlist", "Keyword", "Avg searches (last 3mo)",
                    "3 month change (%)", "Competition",
                    "Low bid (₹)", "High bid (₹)", "Status"]
    edited = st.data_editor(
        filtered[display_cols],
        hide_index=True,
        disabled=[c for c in display_cols if c != "Shortlist"],
        column_config={
            "Shortlist": st.column_config.CheckboxColumn(default=False),
            "Avg searches (last 3mo)": st.column_config.NumberColumn(format="%d"),
            "3 month change (%)": st.column_config.NumberColumn(format="%+.2f"),
            "Low bid (₹)": st.column_config.NumberColumn(format="₹%.2f"),
            "High bid (₹)": st.column_config.NumberColumn(format="₹%.2f"),
        },
        use_container_width=True,
        key="discover_table",
    )

    with st.container(border=True):
        _theme.section_title("Actions")
        cA, cB, cC = st.columns([1, 1, 1.4])
        with cA:
            if st.button("Save shortlist toggles", key="discover_save_sl", use_container_width=True):
                _persist_shortlist_toggles(conn, filtered, edited)
                st.rerun()
        with cB:
            as_pairs = [(r._row.keyword, r._row) for _, r in filtered.iterrows()]
            csv_str = export.output_rows_to_csv(as_pairs)
            st.download_button(
                "Download CSV",
                data=csv_str.encode("utf-8"),
                file_name="keyword_ideas.csv",
                mime="text/csv",
                key="discover_dl",
                use_container_width=True,
            )
        with cC:
            last_sid = st.session_state.get("discover_last_search_id")
            label = st.text_input(
                "Label this run…",
                key="discover_save_label",
                placeholder="e.g. competitor URL exploration",
                label_visibility="collapsed",
                disabled=not last_sid,
            )
            if st.button(
                "Label this run", key="discover_save",
                use_container_width=True, disabled=not last_sid,
            ):
                db.update_search_label(conn, last_sid, label or None)
                st.toast(f"Search #{last_sid} labeled.")


def _persist_shortlist_toggles(conn, filtered_df, edited_df):
    before = list(filtered_df["Shortlist"])
    after = list(edited_df["Shortlist"])
    keys = list(filtered_df["Keyword"])
    rows_by_kw = {r.Keyword: r._row for _, r in filtered_df.iterrows()}
    added = removed = 0
    for kw, b, a in zip(keys, before, after):
        if a == b:
            continue
        r: Row = rows_by_kw[kw]
        if a:
            db.add_to_shortlist(
                conn,
                keyword=kw,
                source_tab="discover",
                source_search_id=None,
                metrics_snapshot={
                    "recent_avg_monthly_searches": r.recent_avg_monthly_searches,
                    "three_month_change": r.three_month_change,
                    "competition": r.competition,
                    "low_top_of_page_bid_micros": r.low_top_of_page_bid_micros,
                    "high_top_of_page_bid_micros": r.high_top_of_page_bid_micros,
                    "currency_code": r.currency_code,
                },
            )
            added += 1
        else:
            db.remove_from_shortlist(conn, kw)
            removed += 1
    if added or removed:
        st.toast(f"Shortlist: +{added} / -{removed}")


def _render_saved_searches(cfg, conn):
    with st.expander("Discover history (auto-saved)", expanded=False):
        saved = db.list_searches(conn, tab="discover")
        if not saved:
            st.caption("No discovery runs yet. Every run auto-saves here.")
            return
        st.caption(f"{len(saved)} run(s). Click ✏️ to rename, 🔁 to reload, 🗑️ to delete.")
        editing_id = st.session_state.get("discover_editing_id")
        for s in saved:
            label = db.display_label(s)
            cA, cB, cC, cD = st.columns([4, 1, 1, 1])
            with cA:
                if editing_id == s["id"]:
                    new_label = st.text_input(
                        f"New label for #{s['id']}",
                        value=s.get("label") or "",
                        key=f"discover_rename_input_{s['id']}",
                        label_visibility="collapsed",
                    )
                    save_col, cancel_col = st.columns(2)
                    if save_col.button("Save", key=f"discover_rename_save_{s['id']}", use_container_width=True):
                        db.update_search_label(conn, s["id"], new_label or None)
                        st.session_state["discover_editing_id"] = None
                        st.rerun()
                    if cancel_col.button("Cancel", key=f"discover_rename_cancel_{s['id']}", use_container_width=True):
                        st.session_state["discover_editing_id"] = None
                        st.rerun()
                else:
                    pill = "" if s.get("label") else " <span class='kt-chip'>auto</span>"
                    st.markdown(
                        f"**{label}**{pill}<br/>"
                        f"<span style='color:var(--muted); font-size:0.8rem;'>"
                        f"#{s['id']} · {s['created_at']:%Y-%m-%d %H:%M} · {s['input_count']} seeds"
                        f"</span>",
                        unsafe_allow_html=True,
                    )
            if cB.button("✏️", key=f"discover_edit_{s['id']}", help="Rename", use_container_width=True):
                st.session_state["discover_editing_id"] = s["id"]
                st.rerun()
            if cC.button("🔁", key=f"discover_reload_{s['id']}", help="Restore saved ideas", use_container_width=True):
                data = s.get("input_data") or {}
                st.session_state["discover_seed_kws"] = "\n".join(data.get("keywords") or [])
                st.session_state["discover_seed_url"] = data.get("url") or ""
                out = s.get("output_data") or {}
                if out.get("ideas"):
                    restored = [row_from_dict(r) for r in out["ideas"]]
                    st.session_state["discover_rows"] = restored
                    st.session_state["discover_input"] = data
                    st.session_state["discover_last_search_id"] = s["id"]
                    st.toast(f"Restored {len(restored):,} saved ideas.")
                else:
                    st.toast("Loaded seed (no saved output) — click Discover.")
                st.rerun()
            if cD.button("🗑️", key=f"discover_del_{s['id']}", help="Delete", use_container_width=True):
                db.delete_search(conn, s["id"])
                st.rerun()
