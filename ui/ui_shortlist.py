"""Shortlist viewer + saved-searches index — spec §6."""
from __future__ import annotations

import pandas as pd
import streamlit as st

import db
import export


def render(cfg, client, conn):
    st.subheader("Shortlist")

    items = db.list_shortlist(conn)
    if not items:
        st.info("Shortlist is empty. Tick the 'Shortlist' checkboxes in Bulk Metrics to add keywords.")
    else:
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

        cA, cB, cC = st.columns([2, 1, 1])
        with cA:
            csv = export.shortlist_to_csv(items).encode("utf-8")
            st.download_button(
                "Download shortlist (CSV)",
                data=csv,
                file_name="shortlist.csv",
                mime="text/csv",
            )
        with cB:
            remove = st.selectbox(
                "Remove keyword",
                options=[""] + [r["keyword"] for r in items],
                key="shortlist_remove",
            )
            if remove and st.button("Remove", key="shortlist_remove_btn"):
                db.remove_from_shortlist(conn, remove)
                st.rerun()
        with cC:
            if st.button("Clear all", key="shortlist_clear", type="secondary"):
                if st.session_state.get("shortlist_confirm"):
                    n = db.clear_shortlist(conn)
                    st.toast(f"Removed {n} entries.")
                    st.session_state["shortlist_confirm"] = False
                    st.rerun()
                else:
                    st.session_state["shortlist_confirm"] = True
                    st.warning("Click 'Clear all' again to confirm.")

    st.divider()
    st.subheader("All saved searches")
    all_searches = db.list_searches(conn)
    if not all_searches:
        st.caption("No saved searches.")
        return
    for s in all_searches:
        st.markdown(
            f"**#{s['id']}** · {s['created_at']:%Y-%m-%d %H:%M} · `{s['tab']}` · "
            f"`{s['input_count']}` keywords · {s['label'] or '_(unlabeled)_'}"
        )
