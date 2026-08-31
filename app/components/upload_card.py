"""
One reusable upload card, instantiated three times in app/layout.py (MPS
Input, MPS Output, Manual Input) -- Development Planning Document, Section 7:
"three upload cards, not one" (the reference screenshots showed a single
consolidated-workbook upload).

Every id used here is passed in and rendered unconditionally in the initial
layout -- this is what tests/test_ui_layout_ids.py checks, to avoid the
"ID not found in layout" defect visible in the reference screenshots.
"""
from __future__ import annotations

from dash import dcc, html


def make_upload_card(upload_id: str, checklist_id: str, title: str, expected_sheets: list[str], optional: bool = False):
    label = f"{title} (optional)" if optional else title
    return html.Div(
        className="upload-card",
        children=[
            html.Div(label, className="upload-card-title"),
            dcc.Upload(
                id=upload_id,
                children=html.Div([
                    html.Div("Click to upload or drag & drop"),
                    html.Div("Excel workbook (.xlsx)", className="upload-hint"),
                ]),
                className="upload-dropzone",
                multiple=False,
            ),
            html.Div(id=checklist_id, className="sheet-checklist", children=[
                html.Div(f"\u25cb {sheet}", className="sheet-item-pending") for sheet in expected_sheets
            ]),
        ],
    )
