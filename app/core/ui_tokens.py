# REMARK: Centralising all visual constants here means every page
# stays in sync with Maersk Design System tokens without importing
# external UI kits — pure CSS injected into Streamlit.

# ---------------------------------------------------------------------------
# Spacing scale (MDS: 4-pt grid)
# ---------------------------------------------------------------------------
SPACING_XS: int = 4
SPACING_SM: int = 8
SPACING_MD: int = 16
SPACING_LG: int = 24
SPACING_XL: int = 32

# ---------------------------------------------------------------------------
# Radius (MDS card standard)
# ---------------------------------------------------------------------------
CARD_RADIUS: int = 8

# ---------------------------------------------------------------------------
# Colour palette — Maersk neutral scaffolding + accent
# ---------------------------------------------------------------------------
COLOR_BG_APP: str = "#F0F4F8"       # Neutral light — app scaffold
COLOR_BG_CARD: str = "#FFFFFF"      # Neutral white — card surfaces
COLOR_TEXT_PRIMARY: str = "#141414"
COLOR_TEXT_SECONDARY: str = "#5C6B7A"
COLOR_ACCENT: str = "#0073AB"       # Maersk ocean blue
COLOR_ACCENT_DARK: str = "#005580"
COLOR_SUCCESS: str = "#1D6F42"
COLOR_WARNING: str = "#B45309"
COLOR_DANGER: str = "#B91C1C"
COLOR_BORDER: str = "#D1D9E0"
COLOR_HIGHLIGHT: str = "#E8F4FC"    # Soft blue tint for selected rows

# ---------------------------------------------------------------------------
# Global CSS — injected once in main.py via st.markdown(unsafe_allow_html=True)
# ---------------------------------------------------------------------------
GLOBAL_CSS: str = f"""
<style>
  /* ── App scaffold ── */
  .stApp {{
    background-color: {COLOR_BG_APP};
    font-family: 'Segoe UI', 'Helvetica Neue', Arial, sans-serif;
  }}

  /* ── Content container ── */
  .block-container {{
    padding: {SPACING_XL}px {SPACING_XL}px {SPACING_LG}px {SPACING_XL}px !important;
    max-width: 1400px !important;
  }}

  /* ── Sidebar ── */
  section[data-testid="stSidebar"] {{
    background-color: {COLOR_BG_CARD};
    border-right: 1px solid {COLOR_BORDER};
  }}
  section[data-testid="stSidebar"] .block-container {{
    padding: {SPACING_LG}px {SPACING_MD}px !important;
  }}

  /* ── Metric tiles ── */
  div[data-testid="stMetricValue"] {{
    font-size: 1.5rem !important;
    font-weight: 700 !important;
    color: {COLOR_TEXT_PRIMARY};
  }}
  div[data-testid="stMetricLabel"] {{
    font-size: 0.78rem !important;
    color: {COLOR_TEXT_SECONDARY} !important;
    text-transform: uppercase;
    letter-spacing: 0.04em;
  }}

  /* ── MDS card ── */
  .mds-card {{
    background: {COLOR_BG_CARD};
    border-radius: {CARD_RADIUS}px;
    padding: {SPACING_LG}px {SPACING_LG}px;
    border: 1px solid {COLOR_BORDER};
    margin-bottom: {SPACING_MD}px;
  }}

  /* ── Page section header ── */
  .mds-section-title {{
    color: {COLOR_TEXT_PRIMARY};
    font-size: 0.72rem;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    margin-bottom: {SPACING_SM}px;
    border-bottom: 2px solid {COLOR_ACCENT};
    padding-bottom: {SPACING_XS}px;
    display: inline-block;
  }}

  /* ── Status badges ── */
  .badge-ok {{
    display: inline-block;
    background: #D1FAE5;
    color: {COLOR_SUCCESS};
    font-weight: 700;
    font-size: 0.75rem;
    padding: 2px 10px;
    border-radius: 999px;
  }}
  .badge-warn {{
    display: inline-block;
    background: #FEF3C7;
    color: {COLOR_WARNING};
    font-weight: 700;
    font-size: 0.75rem;
    padding: 2px 10px;
    border-radius: 999px;
  }}
  .badge-danger {{
    display: inline-block;
    background: #FEE2E2;
    color: {COLOR_DANGER};
    font-weight: 700;
    font-size: 0.75rem;
    padding: 2px 10px;
    border-radius: 999px;
  }}

  /* ── Score block ── */
  .score-block {{
    background: {COLOR_BG_CARD};
    border-radius: {CARD_RADIUS}px;
    border: 1px solid {COLOR_BORDER};
    padding: {SPACING_MD}px;
    text-align: center;
  }}
  .score-number {{
    font-size: 3rem;
    font-weight: 800;
    line-height: 1;
  }}
  .score-approve {{ color: {COLOR_SUCCESS}; }}
  .score-review  {{ color: {COLOR_WARNING}; }}
  .score-reject  {{ color: {COLOR_DANGER};  }}

  /* ── Divider ── */
  hr.mds-divider {{
    border: none;
    border-top: 1px solid {COLOR_BORDER};
    margin: {SPACING_MD}px 0;
  }}

  /* ── Dataframe overrides ── */
  .stDataFrame {{
    border-radius: {CARD_RADIUS}px !important;
    overflow: hidden;
    border: 1px solid {COLOR_BORDER} !important;
  }}

  /* ── Button ── */
  .stButton > button {{
    border-radius: {CARD_RADIUS}px !important;
    font-weight: 600 !important;
    letter-spacing: 0.02em !important;
  }}

  /* ── Expander header ── */
  details summary {{
    font-weight: 600;
    color: {COLOR_TEXT_PRIMARY};
  }}
</style>
"""


def status_badge(status: str) -> str:
    """Return an HTML badge string for a given runway/confidence status."""
    mapping = {
        "On Track": "badge-ok",
        "Risk":     "badge-warn",
        "Expired":  "badge-danger",
        "Unknown":  "badge-warn",
        "Approve":  "badge-ok",
        "Needs Review": "badge-warn",
        "Hard Reject":  "badge-danger",
    }
    css_class = mapping.get(status, "badge-warn")
    return f'<span class="{css_class}">{status}</span>'
