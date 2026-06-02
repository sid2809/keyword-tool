"""Shortlist viewer + saved-searches index — spec §6."""
from __future__ import annotations

import pandas as pd
import streamlit as st

import db
import export
from ui import _theme


def render(cfg, client, conn):
    items = db.list_shortlist(conn)
    n = len(items)
    total_high = sum(((r.get("metrics_snapshot") or {}).get("high_top_of_page_bid_micros") or 0)
                     for r in items) / 1_000_000 if items else 0
    total_searches = sum(((r.get("metrics_snapshot") or {}).get("recent_avg_monthly_searches") or 0)
                        for r in items)

    m1, m2, m3 = st.columns(3)
    m1.metric("Shortlist size", f"{n:,}")
    m2.metric("Sum recent searches", f"{int(total_searches):,}" if total_searches else "—")
    m3.metric("Sum high bids (₹)", f"₹{total_high:,.2f}" if total_high else "—")

    if not items:
        st.info("Shortlist is empty. Tick the 'Shortlist' checkboxes in Bulk Metrics or Discover to add keywords.")
    else:
        with st.container(border=True):
            _theme.section_title("Shortlisted keywords")
            df_rows = []
            for r in items:
                snap = r.get("metrics_snapshot") or {}
                df_rows.append({
                    "Keyword": r["keyword"],
                    "Added": r["added_at"].strftime("%Y-%m-%d %H:%M"),
                    "Avg searches (last 3mo)": snap.get("recent_avg_monthly_searches"),
                    "3 month change (%)": snap.get("three_month_change"),
                    "Competition": snap.get("competition"),
                    "Low bid (₹)": (snap.get("low_top_of_page_bid_micros") or 0) / 1_000_000 or None,
                    "High bid (₹)": (snap.get("high_top_of_page_bid_micros") or 0) / 1_000_000 or None,
                    "Source tab": r.get("source_tab"),
                })
            df = pd.DataFrame(df_rows)
            st.dataframe(
                df,
                hide_index=True,
                use_container_width=True,
                column_config={
                    "Avg searches (last 3mo)": st.column_config.NumberColumn(format="%d"),
                    "3 month change (%)": st.column_config.NumberColumn(format="%+.2f"),
                    "Low bid (₹)": st.column_config.NumberColumn(format="₹%.2f"),
                    "High bid (₹)": st.column_config.NumberColumn(format="₹%.2f"),
                },
            )

        with st.container(border=True):
            _theme.section_title("Actions")
            cA, cB, cC = st.columns([1.2, 1.2, 1])
            with cA:
                csv = export.shortlist_to_csv(items).encode("utf-8")
                st.download_button(
                    "Download CSV",
                    data=csv,
                    file_name="shortlist.csv",
                    mime="text/csv",
                    use_container_width=True,
                )
            with cB:
                remove = st.selectbox(
                    "Remove a keyword",
                    options=[""] + [r["keyword"] for r in items],
                    key="shortlist_remove",
                    label_visibility="collapsed",
                )
                if remove and st.button("Remove", key="shortlist_remove_btn", use_container_width=True):
                    db.remove_from_shortlist(conn, remove)
                    st.rerun()
            with cC:
                confirm = st.session_state.get("shortlist_confirm", False)
                btn_label = "Confirm clear all" if confirm else "Clear all"
                if st.button(btn_label, key="shortlist_clear", type="secondary", use_container_width=True):
                    if confirm:
                        removed = db.clear_shortlist(conn)
                        st.session_state["shortlist_confirm"] = False
                        st.toast(f"Removed {removed} entries.")
                        st.rerun()
                    else:
                        st.session_state["shortlist_confirm"] = True
                        st.warning("Click again to confirm.")

    st.divider()

    _theme.section_title("All saved searches")
    all_searches = db.list_searches(conn)
    if not all_searches:
        st.caption("No saved searches.")
        return
    for s in all_searches:
        cA, cB = st.columns([4, 1])
        cA.markdown(
            f"**#{s['id']}** · {s['created_at']:%Y-%m-%d %H:%M} · "
            f"<span class='kt-chip'>{s['tab']}</span> · "
            f"`{s['input_count']}` items · "
            f"{s['label'] or '_(unlabeled)_'}",
            unsafe_allow_html=True,
        )
        if cB.button("Delete", key=f"all_del_{s['id']}", use_container_width=True):
            db.delete_search(conn, s["id"])
            st.rerun()
