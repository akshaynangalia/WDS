"""Period / line-filter / Min-DOS-override controls, per the reference UI."""
from __future__ import annotations

from dash import dcc, html


def make_controls_panel():
    period_options = [{"label": f"Period {i}", "value": i} for i in range(1, 15)]
    return html.Div(
        className="controls-panel",
        children=[
            html.Div([
                html.Label("Start period", className="control-label"),
                dcc.Dropdown(id="start-period-dropdown", options=period_options, value=1, clearable=False),
            ], className="control-group"),
            html.Div([
                html.Label("End period", className="control-label"),
                dcc.Dropdown(id="end-period-dropdown", options=period_options, value=1, clearable=False),
            ], className="control-group"),
            html.Div([
                html.Label("Production lines (default: all)", className="control-label"),
                dcc.Dropdown(id="line-filter-dropdown", options=[], multi=True, placeholder="All lines"),
            ], className="control-group"),
            html.Div([
                html.Label("Minimum DOS override (days, optional)", className="control-label"),
                dcc.Input(id="min-dos-input", type="number", placeholder="Not applied", min=0),
            ], className="control-group"),
        ],
    )
