"""Theme + chrome CSS injection.

Streamlit's native widgets follow the user's hamburger-menu Theme setting.
This module overlays our brand chrome on top — header, sidebar, containers,
badges, table polish — and swaps palettes when the in-app dark toggle flips.
"""
from __future__ import annotations

import streamlit as st


def _palette(dark: bool) -> dict:
    if dark:
        return {
            "bg":          "#0B1220",
            "panel":       "#131C2E",
            "panel2":      "#1A2640",
            "border":      "#1F2A44",
            "text":        "#E2E8F0",
            "muted":       "#94A3B8",
            "primary":     "#818CF8",
            "primary_2":   "#6366F1",
            "accent":      "#22D3EE",
            "good":        "#22C55E",
            "warn":        "#F59E0B",
            "bad":         "#F87171",
        }
    return {
        "bg":          "#FFFFFF",
        "panel":       "#F8FAFC",
        "panel2":      "#F1F5F9",
        "border":      "#E2E8F0",
        "text":        "#0F172A",
        "muted":       "#64748B",
        "primary":     "#4F46E5",
        "primary_2":   "#4338CA",
        "accent":      "#0891B2",
        "good":        "#16A34A",
        "warn":        "#D97706",
        "bad":         "#DC2626",
    }


def inject(dark: bool) -> None:
    p = _palette(dark)
    css = f"""
    <style>
      :root {{
        --bg: {p['bg']};
        --panel: {p['panel']};
        --panel2: {p['panel2']};
        --border: {p['border']};
        --text: {p['text']};
        --muted: {p['muted']};
        --primary: {p['primary']};
        --primary-2: {p['primary_2']};
        --accent: {p['accent']};
        --good: {p['good']};
        --warn: {p['warn']};
        --bad: {p['bad']};
      }}

      @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');

      html, body, [class*="css"]  {{
        font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'SF Pro Text', sans-serif !important;
      }}

      /* App background */
      .stApp {{
        background: var(--bg) !important;
        color: var(--text) !important;
      }}

      /* Hide Streamlit chrome we don't need */
      #MainMenu {{ visibility: visible; }}
      footer {{ visibility: hidden; }}
      header[data-testid="stHeader"] {{ background: transparent !important; }}

      /* Sidebar */
      section[data-testid="stSidebar"] {{
        background: var(--panel) !important;
        border-right: 1px solid var(--border) !important;
      }}
      section[data-testid="stSidebar"] * {{ color: var(--text) !important; }}

      /* Main container width tweak */
      .block-container {{
        padding-top: 1.4rem !important;
        padding-bottom: 4rem !important;
        max-width: 1280px;
      }}

      /* Brand header card */
      .kt-header {{
        display: flex; align-items: center; justify-content: space-between;
        padding: 18px 22px;
        background: linear-gradient(135deg, var(--panel) 0%, var(--panel2) 100%);
        border: 1px solid var(--border);
        border-radius: 14px;
        margin-bottom: 18px;
      }}
      .kt-title {{ display:flex; align-items:center; gap: 12px; }}
      .kt-logo {{
        width: 36px; height: 36px; border-radius: 10px;
        background: linear-gradient(135deg, var(--primary), var(--accent));
        display:flex; align-items:center; justify-content:center;
        color: white; font-weight: 700; font-size: 18px;
        box-shadow: 0 6px 16px -8px var(--primary);
      }}
      .kt-title h1 {{
        margin: 0; font-size: 1.25rem; font-weight: 700; color: var(--text);
        letter-spacing: -0.01em;
      }}
      .kt-subtitle {{ color: var(--muted); font-size: 0.85rem; margin-top: 2px; }}

      .kt-badges {{ display:flex; gap: 8px; }}
      .kt-badge {{
        display:inline-flex; align-items:center; gap:6px;
        padding: 4px 10px; border-radius: 999px;
        background: var(--panel2); border: 1px solid var(--border);
        font-size: 0.75rem; color: var(--muted); font-weight: 500;
      }}
      .kt-badge.good {{ color: var(--good); border-color: color-mix(in srgb, var(--good) 30%, transparent); }}
      .kt-badge.warn {{ color: var(--warn); border-color: color-mix(in srgb, var(--warn) 35%, transparent); }}
      .kt-badge.bad  {{ color: var(--bad);  border-color: color-mix(in srgb, var(--bad)  35%, transparent); }}
      .kt-dot {{ width:6px; height:6px; border-radius:50%; background: currentColor; }}

      /* Tabs */
      div[data-baseweb="tab-list"] {{
        gap: 4px;
        border-bottom: 1px solid var(--border) !important;
      }}
      button[data-baseweb="tab"] {{
        background: transparent !important;
        color: var(--muted) !important;
        font-weight: 500 !important;
        border-radius: 8px 8px 0 0 !important;
      }}
      button[data-baseweb="tab"][aria-selected="true"] {{
        color: var(--primary) !important;
        border-bottom: 2px solid var(--primary) !important;
      }}

      /* Primary buttons */
      .stButton > button[kind="primary"],
      .stDownloadButton > button[kind="primary"],
      .stFormSubmitButton > button[kind="primary"] {{
        background: linear-gradient(135deg, var(--primary), var(--primary-2)) !important;
        color: #fff !important;
        border: none !important;
        font-weight: 600 !important;
        box-shadow: 0 6px 14px -6px var(--primary) !important;
        transition: transform 0.04s ease, box-shadow 0.2s ease;
      }}
      .stButton > button[kind="primary"]:hover {{
        transform: translateY(-1px);
        box-shadow: 0 10px 24px -8px var(--primary) !important;
      }}
      .stButton > button[kind="secondary"] {{
        background: var(--panel) !important;
        color: var(--text) !important;
        border: 1px solid var(--border) !important;
      }}

      /* Inputs (text area, text input, number input) */
      .stTextInput input, .stTextArea textarea, .stNumberInput input,
      .stSelectbox div[data-baseweb="select"] > div {{
        background: var(--panel) !important;
        color: var(--text) !important;
        border-color: var(--border) !important;
        border-radius: 10px !important;
      }}
      .stTextInput input:focus, .stTextArea textarea:focus, .stNumberInput input:focus {{
        border-color: var(--primary) !important;
        box-shadow: 0 0 0 3px color-mix(in srgb, var(--primary) 25%, transparent) !important;
      }}

      /* DataFrames + data-editor */
      .stDataFrame, .stDataEditor, div[data-testid="stDataFrame"], div[data-testid="stDataEditor"] {{
        border: 1px solid var(--border) !important;
        border-radius: 12px !important;
        overflow: hidden;
      }}

      /* Bordered containers (st.container(border=True)) */
      div[data-testid="stVerticalBlockBorderWrapper"] {{
        border-color: var(--border) !important;
        background: var(--panel) !important;
        border-radius: 14px !important;
      }}

      /* Captions / muted text */
      .stCaption, [data-testid="stCaptionContainer"] {{
        color: var(--muted) !important;
      }}

      /* Progress bar */
      div[data-testid="stProgress"] > div > div > div {{
        background: linear-gradient(90deg, var(--primary), var(--accent)) !important;
      }}

      /* Metric tiles */
      div[data-testid="stMetric"] {{
        background: var(--panel);
        border: 1px solid var(--border);
        padding: 12px 16px;
        border-radius: 12px;
      }}
      div[data-testid="stMetricLabel"] {{ color: var(--muted) !important; font-weight: 500 !important; }}
      div[data-testid="stMetricValue"] {{ color: var(--text) !important; }}

      /* Expanders */
      details[data-testid="stExpander"] {{
        background: var(--panel) !important;
        border: 1px solid var(--border) !important;
        border-radius: 12px !important;
      }}

      /* Section heading helper */
      .kt-section-title {{
        font-size: 0.78rem; font-weight: 600; letter-spacing: 0.08em;
        text-transform: uppercase; color: var(--muted); margin: 4px 0 8px 0;
      }}

      /* Tag / chip */
      .kt-chip {{
        display:inline-block; padding: 2px 8px; border-radius: 999px;
        font-size: 0.75rem; font-weight: 500;
        background: var(--panel2); color: var(--muted);
        border: 1px solid var(--border);
      }}
    </style>
    """
    st.markdown(css, unsafe_allow_html=True)


def header(title: str, subtitle: str, badges: list[tuple[str, str]]) -> None:
    """Render the brand header card. badges = [(label, kind), ...] where kind ∈ {good,warn,bad,neutral}."""
    badge_html = "".join(
        f'<span class="kt-badge {kind if kind != "neutral" else ""}">'
        f'<span class="kt-dot"></span>{label}</span>'
        for label, kind in badges
    )
    st.markdown(
        f"""
        <div class="kt-header">
          <div>
            <div class="kt-title">
              <div class="kt-logo">K</div>
              <div>
                <h1>{title}</h1>
                <div class="kt-subtitle">{subtitle}</div>
              </div>
            </div>
          </div>
          <div class="kt-badges">{badge_html}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def section_title(text: str) -> None:
    st.markdown(f'<div class="kt-section-title">{text}</div>', unsafe_allow_html=True)
