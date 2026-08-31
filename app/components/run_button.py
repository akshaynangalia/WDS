"""Run button + status/progress indicator + download link."""
from __future__ import annotations

from dash import dcc, html


def make_run_button():
    return html.Div(
        className="run-section",
        children=[
            html.Button("Run Disaggregation", id="run-button", n_clicks=0, disabled=True, className="run-button"),
            dcc.Loading(
                id="run-loading",
                type="default",
                children=html.Div(id="run-status", className="run-status"),
            ),
            dcc.Download(id="download-output"),
        ],
    )
