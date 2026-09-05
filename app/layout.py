"""
Top-level page layout: header, three upload cards, controls, fallback banner,
run button/status/download.

Every id referenced by app/callbacks.py exists here, unconditionally, in the
initial render -- including the dcc.Store components used to pass uploaded
file bytes and validation state between callbacks. This is what
tests/test_ui_layout_ids.py checks for.
"""
from __future__ import annotations

from dash import dcc, html

from app.components.controls_panel import make_controls_panel
from app.components.fallback_banner import make_fallback_banner
from app.components.run_button import make_run_button
from app.components.upload_card import make_upload_card

MPS_INPUT_SHEETS = ["SKU Master", "2.Demand Input", "Period Calendar Matrix", "4.SOC Sheet & Flag"]
MPS_OUTPUT_SHEETS = ["SKU Line Loading 1", "Linkcode_DIFC"]
MANUAL_INPUT_SHEETS = ["RCCP", "Calendar"]


def make_layout():
    return html.Div(
        className="app-container",
        children=[
            html.Div(
                className="header-bar",
                children=[
                    html.Div(
                        className="header-left",
                        children=[
                            html.Img(src="/assets/mdlz_logo.png", className="header-logo"),
                            html.Div("Mondelez International", className="header-brand"),
                        ],
                    ),
                    html.Div("Weekly Disaggregation Tool", className="header-title"),
                ],
            ),
            html.Div(
                className="main-content",
                children=[
                    html.H1("Weekly Disaggregation", className="page-title"),
                    html.P(
                        "Upload the MPS Input, MPS Output, and Manual Input workbooks, "
                        "choose the periods, and generate the weekly plan.",
                        className="page-subtitle",
                    ),
                    html.Div(
                        className="upload-row",
                        children=[
                            make_upload_card("upload-mps-input", "checklist-mps-input",
                                              "MPS Input", MPS_INPUT_SHEETS),
                            make_upload_card("upload-mps-output", "checklist-mps-output",
                                              "MPS Output", MPS_OUTPUT_SHEETS),
                            make_upload_card("upload-manual-input", "checklist-manual-input",
                                              "Manual Input", MANUAL_INPUT_SHEETS, optional=True),
                        ],
                    ),
                    make_fallback_banner(),
                    make_controls_panel(),
                    make_run_button(),

                    # Stores -- hold uploaded file bytes and validation state between callbacks.
                    dcc.Store(id="store-mps-input"),
                    dcc.Store(id="store-mps-output"),
                    dcc.Store(id="store-manual-input"),
                    dcc.Store(id="store-validation"),
                ],
            ),
            html.Div("Mondelez International", className="footer"),
        ],
    )
