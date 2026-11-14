"""Visual identity: red / navy / neutral palette (PRD 4.2). No APIS brand assets are used."""

from __future__ import annotations

import streamlit as st

RED = "#C8102E"
NAVY = "#1B2A4A"
SLATE = "#5B6578"
SURFACE = "#F4F6F9"

_CSS = f"""
<style>
  .apis-header {{ border-bottom: 3px solid {RED}; padding-bottom: .4rem; margin-bottom: 1rem; }}
  .apis-header h1 {{ color: {NAVY}; font-size: 1.6rem; margin: 0; }}
  .apis-header p  {{ color: {SLATE}; margin: .2rem 0 0 0; font-size: .9rem; }}
  .apis-badge {{ display:inline-block; padding:.1rem .55rem; border-radius:999px; font-size:.75rem;
                 font-weight:600; letter-spacing:.02em; }}
  .apis-badge.ok   {{ background:#E6F4EA; color:#1E6B34; }}
  .apis-badge.warn {{ background:#FFF4E0; color:#8A5A00; }}
  .apis-badge.fail {{ background:#FDE7EA; color:{RED}; }}
  .apis-badge.info {{ background:#E8EDF5; color:{NAVY}; }}
  [data-testid="stMetric"] {{ background:{SURFACE}; border-radius:8px; padding:.6rem .8rem;
                              border-left:4px solid {NAVY}; }}
</style>
"""


def apply_theme() -> None:
    st.markdown(_CSS, unsafe_allow_html=True)


def page_header(title: str, subtitle: str | None = None) -> None:
    sub = f"<p>{subtitle}</p>" if subtitle else ""
    st.markdown(f'<div class="apis-header"><h1>{title}</h1>{sub}</div>', unsafe_allow_html=True)


def badge(text: str, kind: str = "info") -> str:
    """Return badge HTML. `text` must be application-controlled, never user input."""
    return f'<span class="apis-badge {kind}">{text}</span>'
