"""Bulk Metrics tab — spec §6 Tab 1.

Paste/CSV input → run + progress → table + filters → shortlist + save + CSV.
"""
from __future__ import annotations

import io
from dataclasses import asdict

import pandas as pd
import streamlit as st

import db
import export
from core import cache as cache_mod
from core.metrics import fetch_historical_metrics, expand_to_output_rows
from core.models import Row, row_to_dict, row_from_dict
from ui import _theme


COMPETITION_DISPLAY = {"LOW": "Low", "MEDIUM": "Medium", "HIGH": "High"}


def render(cfg, client, conn):
    # Apply any pending "Reload" paste BEFORE the text_area is instantiated
    # (Streamlit forbids touching a widget key after the widget renders).
    if "_pending_metrics_paste" in st.session_state:
        st.session_state["metrics_pasted"] = st.session_state.pop("_pending_metrics_paste")

    with st.container(border=True):
        _theme.section_title("Input")
        col1, col2 = st.columns([2, 1])
        with col1:
            pasted = st.text_area(
                "Paste keywords (one per line)",
                height=190,
                key="metrics_pasted",
                placeholder="car insurance\nbest mattress\npersonal loan",
                label_visibility="collapsed",
            )
        with col2:
            uploaded = st.file_uploader("Or upload CSV", type=["csv", "txt"], key="metrics_upload")
            force_refresh = st.checkbox(
                "Force refresh (bypass cache)",
                key="metrics_force",
                help=f"Cache freshness window: {cfg.cache_freshness_days} days.",
            )
            run_clicked = st.button("Run", type="primary", key="metrics_run", use_container_width=True)

    if run_clicked:
        keywords = _collect_keywords(pasted, uploaded)
        if not keywords:
            st.warning("No keywords to run.")
            return
        _run_metrics(cfg, client, conn, keywords, force_refresh)

    output = st.session_state.get("metrics_output")
    if not output:
        st.caption("Run a query to see results here.")
    else:
        _render_results(cfg, conn, output)

    _render_saved_searches(cfg, client, conn)


def _collect_keywords(pasted: str, uploaded) -> list[str]:
    """Build ordered keyword list from pasted text and/or uploaded CSV.
    Preserves order; preserves duplicates (spec §4.5).
    """
    out: list[str] = []
    if pasted:
        for line in pasted.splitlines():
            s = line.strip()
            if s:
                out.append(s)
    if uploaded is not None:
        try:
            text = uploaded.getvalue().decode("utf-8", errors="replace")
        except Exception:
            text = ""
        # Accept either a single column CSV or plain newline-separated text.
        for line in text.splitlines():
            # Take first comma-separated cell if it's a CSV
            cell = line.split(",")[0].strip().strip('"')
            if cell and cell.lower() != "keyword":
                out.append(cell)
    return out


def _run_metrics(cfg, client, conn, keywords: list[str], force_refresh: bool):
    progress = st.progress(0.0, text="Starting…")
    state = {"calls": 0}

    def progress_cb(done, total):
        if total <= 0:
            progress.progress(1.0, text="Cache hits — no API calls.")
            return
        state["calls"] = done
        frac = done / total
        progress.progress(frac, text=f"Chunk {done}/{total}")

    currency = st.session_state.get("currency_code")
    if not currency:
        from core.google_ads_client import get_account_currency
        currency = get_account_currency(client, cfg.customer_id)
        st.session_state["currency_code"] = currency

    try:
        with st.spinner("Fetching from Google Ads…"):
            rows_by_kw = fetch_historical_metrics(
                keywords,
                client=client,
                conn=conn,
                customer_id=cfg.customer_id,
                chunk_size=cfg.chunk_size,
                months=cfg.historical_window_months,
                cache_freshness_days=cfg.cache_freshness_days,
                store_monthly_volumes=cfg.store_monthly_volumes,
                force_refresh=force_refresh,
                currency_code=currency,
                progress_cb=progress_cb,
            )
    except Exception as e:
        progress.empty()
        st.error(f"API call failed: {type(e).__name__}: {e}")
        return

    progress.empty()
    output = expand_to_output_rows(keywords, rows_by_kw)
    st.session_state["metrics_output"] = output
    st.session_state["metrics_input_keywords"] = keywords
    st.session_state["metrics_last_calls"] = state["calls"]
    st.session_state["metrics_last_unique"] = len(rows_by_kw)

    # Auto-save every successful run, including the output snapshot.
    snapshot = {
        "rows": [{"input": inp, "row": row_to_dict(row)} for inp, row in output],
        "calls": state["calls"],
        "unique_resolved": len(rows_by_kw),
    }
    sid = db.save_search(
        conn,
        label=None,
        tab="metrics",
        input_count=len(keywords),
        filters={"force_refresh": force_refresh},
        input_data={"keywords": keywords},
        output_data=snapshot,
    )
    st.session_state["metrics_last_search_id"] = sid


def _output_to_df(output: list[tuple[str, Row]]) -> pd.DataFrame:
    rows = []
    for inp, r in output:
        rows.append({
            "Keyword": inp,
            "Avg searches (last 3mo)": r.recent_avg_monthly_searches,
            "3 month change (%)": r.three_month_change,
            "Competition": COMPETITION_DISPLAY.get(r.competition or "", r.competition or ""),
            "Low bid (₹)": (r.low_top_of_page_bid_micros / 1_000_000) if r.low_top_of_page_bid_micros else None,
            "High bid (₹)": (r.high_top_of_page_bid_micros / 1_000_000) if r.high_top_of_page_bid_micros else None,
            "Status": ("No data" if not r.has_data else ("Merged variant" if r.is_close_variant_merged else "")),
            "_norm": cache_mod.normalize(inp),
            "_row": r,
        })
    return pd.DataFrame(rows)


def _render_results(cfg, conn, output: list[tuple[str, Row]]):
    df = _output_to_df(output)

    # Summary tiles
    n_total = len(df)
    n_data = int(df["_row"].apply(lambda r: r.has_data).sum())
    n_merged = int(df["_row"].apply(lambda r: r.is_close_variant_merged).sum())
    avg_searches = df["Avg searches (last 3mo)"].dropna().mean() if n_data else 0
    last_calls = st.session_state.get("metrics_last_calls")

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Output rows", f"{n_total:,}")
    m2.metric("With data", f"{n_data:,}")
    m3.metric("Avg searches (mean)", f"{int(avg_searches):,}" if avg_searches else "—")
    m4.metric("API calls (last run)", f"{last_calls}" if last_calls is not None else "—")
    if n_merged:
        st.caption(f"{n_merged} input keyword(s) merged into a close variant — see Status column.")

    with st.container(border=True):
        _theme.section_title("Filters")
        fc1, fc2, fc3 = st.columns(3)
        with fc1:
            min_searches = st.number_input(
                "Min avg searches (last 3mo)",
                min_value=0, value=0, step=100, key="filter_min_searches",
            )
        with fc2:
            max_high_bid = st.number_input(
                "Max high bid (₹)",
                min_value=0.0, value=0.0, step=10.0, key="filter_max_bid",
                help="0 = no limit",
            )
        with fc3:
            comp_options = ["Low", "Medium", "High"]
            comp_selected = st.multiselect(
                "Competition", comp_options, default=comp_options, key="filter_comp",
            )

    # Apply filters
    mask = pd.Series([True] * len(df))
    if min_searches > 0:
        mask &= df["Avg searches (last 3mo)"].fillna(-1) >= min_searches
    if max_high_bid > 0:
        mask &= df["High bid (₹)"].fillna(float("inf")) <= max_high_bid
    if comp_selected:
        # Show no-data rows only if Low+Medium+High all selected (i.e. no filter active)
        if len(comp_selected) < 3:
            mask &= df["Competition"].isin(comp_selected)
    filtered = df[mask].copy()

    st.caption(f"Showing {len(filtered)} of {len(df)} rows after filters.")

    sl_keywords = db.shortlist_keywords(conn)
    filtered["Shortlist"] = filtered["_norm"].apply(lambda n: n in sl_keywords)

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
        key="metrics_table",
    )

    with st.container(border=True):
        _theme.section_title("Actions")
        cA, cB, cC = st.columns([1, 1, 1.4])
        with cA:
            if st.button("Save shortlist toggles", key="metrics_save_sl", use_container_width=True):
                _persist_shortlist_toggles(conn, filtered, edited)
                st.rerun()
        with cB:
            csv_str = export.output_rows_to_csv(
                [(inp, r) for inp, r in output if cache_mod.normalize(inp) in set(filtered["_norm"])]
            )
            st.download_button(
                "Download CSV",
                data=csv_str.encode("utf-8"),
                file_name="keywords_filtered.csv",
                mime="text/csv",
                key="metrics_dl_filtered",
                use_container_width=True,
            )
        with cC:
            last_sid = st.session_state.get("metrics_last_search_id")
            label = st.text_input(
                "Label this run…",
                key="metrics_save_label",
                placeholder="e.g. June insurance pull",
                label_visibility="collapsed",
                disabled=not last_sid,
            )
            if st.button(
                "Label this run", key="metrics_save_search",
                use_container_width=True, disabled=not last_sid,
            ):
                db.update_search_label(conn, last_sid, label or None)
                st.toast(f"Search #{last_sid} labeled.")


def _persist_shortlist_toggles(conn, filtered_df, edited_df):
    """Diff filtered vs edited 'Shortlist' column; apply add/remove to DB."""
    by_norm = {row._norm: row._row for _, row in filtered_df.iterrows()}
    # Streamlit's data_editor returns the rows in the same order as input
    before = list(filtered_df["Shortlist"])
    after = list(edited_df["Shortlist"])
    keys = list(filtered_df["_norm"])
    added = removed = 0
    for norm, b, a in zip(keys, before, after):
        if a == b:
            continue
        r: Row = by_norm[norm]
        if a:
            db.add_to_shortlist(
                conn,
                keyword=norm,
                source_tab="metrics",
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
            db.remove_from_shortlist(conn, norm)
            removed += 1
    if added or removed:
        st.toast(f"Shortlist: +{added} / -{removed}")


def _render_saved_searches(cfg, client, conn):
    with st.expander("Search history (auto-saved)", expanded=False):
        saved = db.list_searches(conn, tab="metrics")
        if not saved:
            st.caption("No saved searches yet. Every run auto-saves here.")
            return
        st.caption(f"{len(saved)} run(s). Click ✏️ to rename, 🔁 to reload into the input box, 🗑️ to delete.")
        editing_id = st.session_state.get("metrics_editing_id")
        for s in saved:
            label = db.display_label(s)
            cA, cB, cC, cD = st.columns([4, 1, 1, 1])
            with cA:
                if editing_id == s["id"]:
                    new_label = st.text_input(
                        f"New label for #{s['id']}",
                        value=s.get("label") or "",
                        key=f"rename_input_{s['id']}",
                        label_visibility="collapsed",
                    )
                    save_col, cancel_col = st.columns(2)
                    if save_col.button("Save", key=f"rename_save_{s['id']}", use_container_width=True):
                        db.update_search_label(conn, s["id"], new_label or None)
                        st.session_state["metrics_editing_id"] = None
                        st.rerun()
                    if cancel_col.button("Cancel", key=f"rename_cancel_{s['id']}", use_container_width=True):
                        st.session_state["metrics_editing_id"] = None
                        st.rerun()
                else:
                    pill = "" if s.get("label") else " <span class='kt-chip'>auto</span>"
                    st.markdown(
                        f"**{label}**{pill}<br/>"
                        f"<span style='color:var(--muted); font-size:0.8rem;'>"
                        f"#{s['id']} · {s['created_at']:%Y-%m-%d %H:%M} · {s['input_count']} keywords"
                        f"</span>",
                        unsafe_allow_html=True,
                    )
            if cB.button("✏️", key=f"edit_{s['id']}", help="Rename", use_container_width=True):
                st.session_state["metrics_editing_id"] = s["id"]
                st.rerun()
            if cC.button("🔁", key=f"reload_{s['id']}", help="Restore saved output", use_container_width=True):
                inp = s.get("input_data") or {}
                st.session_state["_pending_metrics_paste"] = "\n".join(inp.get("keywords", []))
                out = s.get("output_data") or {}
                if out.get("rows"):
                    restored = [
                        (item["input"], row_from_dict(item["row"]))
                        for item in out["rows"]
                    ]
                    st.session_state["metrics_output"] = restored
                    st.session_state["metrics_input_keywords"] = inp.get("keywords", [])
                    st.session_state["metrics_last_calls"] = out.get("calls")
                    st.session_state["metrics_last_unique"] = out.get("unique_resolved", len(restored))
                    st.session_state["metrics_last_search_id"] = s["id"]
                    st.toast("Restored saved output.")
                else:
                    st.toast("Loaded keywords (no saved output) — click Run.")
                st.rerun()
            if cD.button("🗑️", key=f"del_{s['id']}", help="Delete", use_container_width=True):
                db.delete_search(conn, s["id"])
                st.rerun()
