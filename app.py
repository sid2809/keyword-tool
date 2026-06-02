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
        if st.button("Lock app", use_container_width=True):
            st.session_state["unlocked"] = False
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

    currency = st.session_state.get("currency_code")
    render_sidebar(cfg, currency)

    badges = [
        (f"Currency · {currency or '??'}", "good" if currency == "INR" else "warn"),
        ("Geo · USA", "neutral"),
        ("Network · Search", "neutral"),
        ("Languages · all", "neutral"),
    ]
    _theme.header("Keyword Tool", "Bulk keyword research with cached Postgres lookups", badges)

    tab_metrics, tab_discover, tab_shortlist = st.tabs([
        "  Bulk Metrics  ", "  Discover  ", "  Shortlist & Saved  ",
    ])

    with get_conn(cfg) as conn:
        with tab_metrics:
            ui_metrics.render(cfg, client, conn)
        with tab_discover:
            ui_discover.render(cfg, client, conn)
        with tab_shortlist:
            ui_shortlist.render(cfg, client, conn)


if __name__ == "__main__":
    main()
