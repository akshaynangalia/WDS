"""
Amber degraded-mode banner. Present in the layout at all times (empty/hidden
by default via style, never conditionally created) so callbacks can safely
target its id -- see the Section 7 note on the "ID not found in layout"
defect this is designed to avoid.
"""
from __future__ import annotations

from dash import html


def make_fallback_banner():
    return html.Div(
        id="fallback-banner",
        className="fallback-banner",
        style={"display": "none"},
        children=[],
    )
