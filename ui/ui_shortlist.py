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
        st.caption("No saved searches. Every run auto-saves under its tab.")
        return
    st.caption(f"{len(all_searches)} run(s) across all tabs. Click ✏️ to rename, 🗑️ to delete.")
    editing_id = st.session_state.get("all_editing_id")
    for s in all_searches:
        label = db.display_label(s)
        cA, cB, cC, cD = st.columns([5, 1, 1, 1])
        with cA:
            if editing_id == s["id"]:
                new_label = st.text_input(
                    f"New label for #{s['id']}",
                    value=s.get("label") or "",
                    key=f"all_rename_input_{s['id']}",
                    label_visibility="collapsed",
                )
                save_col, cancel_col = st.columns(2)
                if save_col.button("Save", key=f"all_rename_save_{s['id']}", use_container_width=True):
                    db.update_search_label(conn, s["id"], new_label or None)
                    st.session_state["all_editing_id"] = None
                    st.rerun()
                if cancel_col.button("Cancel", key=f"all_rename_cancel_{s['id']}", use_container_width=True):
                    st.session_state["all_editing_id"] = None
                    st.rerun()
            else:
                pill = "" if s.get("label") else " <span class='kt-chip'>auto</span>"
                st.markdown(
                    f"**{label}**{pill} <span class='kt-chip'>{s['tab']}</span><br/>"
                    f"<span style='color:var(--muted); font-size:0.8rem;'>"
                    f"#{s['id']} · {s['created_at']:%Y-%m-%d %H:%M} · {s['input_count']} items"
                    f"</span>",
                    unsafe_allow_html=True,
                )
        if cB.button("✏️", key=f"all_edit_{s['id']}", help="Rename", use_container_width=True):
            st.session_state["all_editing_id"] = s["id"]
            st.rerun()
        with cC:
            st.link_button(
                "🔗",
                url=f"?view={s['tab']}&search={s['id']}",
                help="Open in a new tab (shareable URL)",
                use_container_width=True,
            )
        if cD.button("🗑️", key=f"all_del_{s['id']}", help="Delete", use_container_width=True):
            db.delete_search(conn, s["id"])
            st.rerun()
