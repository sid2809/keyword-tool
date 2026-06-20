"""Streamlit entry — key gate + tab router (spec §6)."""
from __future__ import annotations

import streamlit as st

import db
from config import Config
from core.google_ads_client import build_client, get_account_currency
from ui import ui_metrics, ui_discover, ui_shortlist, _theme


st.set_page_config(
    page_title="Keyword Tool",
    page_icon="🔎",
    layout="wide",
    initial_sidebar_state="expanded",
)


@st.cache_resource
def get_config() -> Config:
    cfg = Config.from_env()
    db.init_schema(cfg.database_url)
    return cfg


@st.cache_resource
def get_client(_cfg: Config):
    return build_client(_cfg.google_ads_credentials())


def get_conn(cfg: Config):
    return db.connect(cfg.database_url)


def key_gate(cfg: Config) -> bool:
    if st.session_state.get("unlocked"):
        return True
    _theme.inject(dark=st.session_state.get("dark_mode", False))
    col_l, col_c, col_r = st.columns([1, 1.4, 1])
    with col_c:
        st.markdown(
            """
            <div class="kt-header" style="flex-direction:column; align-items:flex-start; margin-top: 8vh;">
              <div class="kt-title">
                <div class="kt-logo">K</div>
                <div>
                  <h1>Keyword Tool</h1>
                  <div class="kt-subtitle">Internal access · USA · INR · Google Search</div>
                </div>
              </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        with st.form("unlock", clear_on_submit=False):
            entered = st.text_input("Access key", type="password",
                                    placeholder="Enter your access key", label_visibility="collapsed")
            ok = st.form_submit_button("Unlock", type="primary", use_container_width=True)
        if ok:
            if entered == cfg.app_access_key and cfg.app_access_key:
                st.session_state["unlocked"] = True
                st.rerun()
            else:
                st.error("Wrong key.")
    return False


def render_sidebar(cfg: Config, currency: str | None):
    with st.sidebar:
        st.markdown(
            """
            <div style="display:flex; align-items:center; gap:10px; padding: 6px 0 18px 0;">
              <div class="kt-logo" style="width:30px; height:30px; font-size:14px;">K</div>
              <div style="font-weight:700; font-size: 1rem;">Keyword Tool</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        dark = st.toggle(
            "🌙 Dark mode",
            value=st.session_state.get("dark_mode", False),
            help="Re-skins the app chrome. For full theme switch, use the ☰ menu top-right.",
        )
        if dark != st.session_state.get("dark_mode"):
            st.session_state["dark_mode"] = dark
            st.rerun()

        st.divider()

        _theme.section_title("Account")
        st.markdown(
            f"<div style='font-size:0.85rem; line-height:1.7;'>"
            f"<div><span class='kt-chip'>CID</span> {cfg.customer_id}</div>"
            f"<div><span class='kt-chip'>MCC</span> {cfg.login_customer_id}</div>"
            f"<div><span class='kt-chip'>{currency or '??'}</span> {'✓' if currency == 'INR' else 'check'}</div>"
            f"</div>",
            unsafe_allow_html=True,
        )

        st.divider()

        _theme.section_title("Settings")
        st.markdown(
            f"<div style='font-size:0.82rem; color: var(--muted); line-height:1.6;'>"
            f"Geo · USA<br/>Network · Google Search<br/>Languages · all<br/>"
            f"Chunk size · {cfg.chunk_size:,}<br/>Cache · {cfg.cache_freshness_days} days"
            f"</div>",
            unsafe_allow_html=True,
        )

        st.divider()
        col_home, col_lock = st.columns(2)
        if col_home.button("🏠 Home", use_container_width=True, help="Clear restored search + URL"):
            _go_home()
        if col_lock.button("Lock", use_container_width=True):
            st.session_state["unlocked"] = False
            st.rerun()


_VIEW_TO_LABEL = {"metrics": "Bulk Metrics", "discover": "Discover", "shortlist": "Shortlist & Saved"}
_LABEL_TO_VIEW = {v: k for k, v in _VIEW_TO_LABEL.items()}
_VALID_VIEWS = set(_VIEW_TO_LABEL)


def _apply_url_state(cfg: Config) -> None:
    """At the top of each run, BEFORE any widget renders: seed the view from
    the URL on FIRST load only, and handle one-shot saved-search restores.

    Key rule: we do NOT re-force the segmented control from ?view= on every
    rerun. The widget is authoritative for navigation; re-forcing would let a
    stale URL override a manual tab click. `_force_segment` is a one-shot the
    tab strip consumes only when we genuinely need to move the selection
    (first load or a search deep-link).
    """
    qp = st.query_params
    requested_view = qp.get("view") if qp.get("view") in _VALID_VIEWS else None
    requested_search = qp.get("search")

    # Seed the initial view exactly once (first load / shared link).
    if "view" not in st.session_state:
        initial = requested_view or "metrics"
        st.session_state["view"] = initial
        st.session_state["_force_segment"] = _VIEW_TO_LABEL[initial]

    if not requested_search:
        st.session_state.pop("_restore_search", None)
        st.session_state.pop("_loaded_search_id", None)
        return

    # One-shot saved-search restore for this URL's ?search= id.
    cached = st.session_state.get("_restore_search")
    if not cached or st.session_state.get("_loaded_search_id") != requested_search:
        try:
            sid = int(requested_search)
        except ValueError:
            return
        with get_conn(cfg) as conn:
            record = db.load_search(conn, sid)
        if not record:
            return
        st.session_state["_restore_search"] = record
        st.session_state["_loaded_search_id"] = requested_search
        tab = record.get("tab")
        if tab in _VALID_VIEWS:
            st.session_state["view"] = tab
            st.session_state["_force_segment"] = _VIEW_TO_LABEL[tab]  # one-shot
            st.query_params["view"] = tab


def _go_home() -> None:
    """Clear all view + restore state and reset the URL to root."""
    for key in (
        "view", "_loaded_search_id", "_restore_search",
        "_last_applied_metrics_search_id", "_last_applied_discover_search_id",
        "metrics_output", "metrics_input_keywords", "metrics_last_calls",
        "metrics_last_unique", "metrics_last_search_id", "metrics_editing_id",
        "_pending_metrics_paste",
        "discover_rows", "discover_input", "discover_last_search_id",
        "discover_editing_id", "_pending_discover_kws", "_pending_discover_url",
        "all_editing_id",
    ):
        st.session_state.pop(key, None)
    # Reset the segmented_control widget by removing its key too.
    st.session_state.pop("_view_segmented", None)
    st.session_state.pop("_force_segment", None)
    st.query_params.clear()
    st.session_state["view"] = "metrics"
    st.session_state["_force_segment"] = _VIEW_TO_LABEL["metrics"]
    st.rerun()


def main():
    cfg = get_config()
    _theme.inject(dark=st.session_state.get("dark_mode", False))

    if not key_gate(cfg):
        return

    client = get_client(cfg)

    if "currency_code" not in st.session_state:
        try:
            st.session_state["currency_code"] = get_account_currency(client, cfg.customer_id)
        except Exception as e:
            st.warning(f"Could not read currency_code: {e}")
            st.session_state["currency_code"] = None

    # Apply URL → state BEFORE any widget is rendered.
    _apply_url_state(cfg)

    currency = st.session_state.get("currency_code")
    render_sidebar(cfg, currency)

    badges = [
        (f"Currency · {currency or '??'}", "good" if currency == "INR" else "warn"),
        ("Geo · USA", "neutral"),
        ("Network · Search", "neutral"),
        ("Languages · all", "neutral"),
    ]
    _theme.header("Keyword Tool", "Bulk keyword research with cached Postgres lookups", badges)

    # Tab strip. The segmented control is the source of truth for navigation;
    # `_force_segment` (one-shot) is applied only on first load / search
    # restore, so a stale ?view= can never override a manual click.
    label_options = list(_VIEW_TO_LABEL.values())
    force_label = st.session_state.pop("_force_segment", None)
    if force_label is not None:
        st.session_state["_view_segmented"] = force_label
    elif "_view_segmented" not in st.session_state:
        st.session_state["_view_segmented"] = _VIEW_TO_LABEL[st.session_state.get("view", "metrics")]

    col_strip, col_home = st.columns([5, 1])
    with col_strip:
        new_label = st.segmented_control(
            "View",
            options=label_options,
            selection_mode="single",
            label_visibility="collapsed",
            key="_view_segmented",
        )
    with col_home:
        if st.button("🏠 Home", use_container_width=True, key="header_home"):
            _go_home()

    # Widget wins. Fall back to current view if the control was deselected.
    new_view = _LABEL_TO_VIEW.get(new_label or "", st.session_state.get("view", "metrics"))
    if new_view != st.session_state.get("view"):
        st.session_state["view"] = new_view
        st.query_params["view"] = new_view
        # A manual tab switch ends any saved-search deep-link context.
        if "search" in st.query_params:
            del st.query_params["search"]
        st.session_state.pop("_loaded_search_id", None)
        st.session_state.pop("_restore_search", None)

    with get_conn(cfg) as conn:
        if new_view == "metrics":
            ui_metrics.render(cfg, client, conn)
        elif new_view == "discover":
            ui_discover.render(cfg, client, conn)
        else:
            ui_shortlist.render(cfg, client, conn)


if __name__ == "__main__":
    main()
