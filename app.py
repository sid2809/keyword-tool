"""Streamlit entry — key gate + tab router (spec §6)."""
from __future__ import annotations

import streamlit as st

import db
from config import Config
from core.google_ads_client import build_client, get_account_currency
from ui import ui_metrics, ui_discover, ui_shortlist


st.set_page_config(page_title="Keyword Tool", page_icon="🔎", layout="wide")


@st.cache_resource
def get_config() -> Config:
    cfg = Config.from_env()
    # Init schema once per process — idempotent.
    db.init_schema(cfg.database_url)
    return cfg


@st.cache_resource
def get_client(_cfg: Config):
    return build_client(_cfg.google_ads_credentials())


def get_conn(cfg: Config):
    """Per-rerun connection. Cheap on Railway; safer than holding a long-lived one."""
    return db.connect(cfg.database_url)


def key_gate(cfg: Config) -> bool:
    if st.session_state.get("unlocked"):
        return True
    st.title("Keyword Tool")
    st.caption("Access key required.")
    with st.form("unlock"):
        entered = st.text_input("Access key", type="password")
        ok = st.form_submit_button("Unlock")
    if ok:
        if entered == cfg.app_access_key and cfg.app_access_key:
            st.session_state["unlocked"] = True
            st.rerun()
        else:
            st.error("Wrong key.")
    return False


def main():
    cfg = get_config()
    if not key_gate(cfg):
        return

    client = get_client(cfg)

    # Warm the currency code once per session.
    if "currency_code" not in st.session_state:
        try:
            st.session_state["currency_code"] = get_account_currency(client, cfg.customer_id)
        except Exception as e:
            st.warning(f"Could not read currency_code: {e}")
            st.session_state["currency_code"] = None

    currency = st.session_state.get("currency_code")
    cur_badge = f"INR ✓" if currency == "INR" else f"{currency or '??'} ⚠"
    st.title("Keyword Tool")
    st.caption(f"Account currency: {cur_badge}  ·  Geo: USA  ·  Network: Google Search  ·  Languages: all")

    tab_metrics, tab_discover, tab_shortlist = st.tabs(["Bulk Metrics", "Discover", "Shortlist & Saved"])

    with get_conn(cfg) as conn:
        with tab_metrics:
            ui_metrics.render(cfg, client, conn)
        with tab_discover:
            ui_discover.render(cfg, client, conn)
        with tab_shortlist:
            ui_shortlist.render(cfg, client, conn)


if __name__ == "__main__":
    main()
