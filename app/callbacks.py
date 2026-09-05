"""
All Dash callbacks. This is the ONLY file allowed to call
orchestration.run_manager.execute_run() (Development Planning Document,
Section 2.2) -- business logic itself never lives here.

Every callback Output/Input/State id must exist in app/layout.py's initial
render; tests/test_ui_layout_ids.py checks this automatically.
"""
from __future__ import annotations

import base64
import io

from dash import Dash, Input, Output, State, dcc, html

from engine.parsers import manual_input_parser, mps_input_parser, mps_output_parser, validation
from engine.fallback import resolve as resolve_fallback
from orchestration.models import RunParams
from orchestration import run_history
from orchestration.run_manager import execute_run


def _decode(contents: str) -> io.BytesIO:
    _, content_string = contents.split(",", 1)
    return io.BytesIO(base64.b64decode(content_string))


def _checklist(expected: list[str], found: set[str]) -> list:
    items = []
    for sheet in expected:
        ok = sheet in found
        mark = "\u2713" if ok else "\u25cb"
        cls = "sheet-item-found" if ok else "sheet-item-missing"
        items.append(html.Div(f"{mark} {sheet}", className=cls))
    return items


def register_callbacks(app: Dash):

    @app.callback(
        Output("checklist-mps-input", "children"),
        Output("store-mps-input", "data"),
        Input("upload-mps-input", "contents"),
        prevent_initial_call=True,
    )
    def on_upload_mps_input(contents):
        if contents is None:
            return [], None
        data = mps_input_parser.parse(_decode(contents))
        checklist = _checklist(list(mps_input_parser.REQUIRED_SHEETS), data.sheets_found)
        return checklist, contents

    @app.callback(
        Output("checklist-mps-output", "children"),
        Output("store-mps-output", "data"),
        Input("upload-mps-output", "contents"),
        prevent_initial_call=True,
    )
    def on_upload_mps_output(contents):
        if contents is None:
            return [], None
        data = mps_output_parser.parse(_decode(contents))
        checklist = _checklist(list(mps_output_parser.REQUIRED_SHEETS), data.sheets_found)
        return checklist, contents

    @app.callback(
        Output("checklist-manual-input", "children"),
        Output("store-manual-input", "data"),
        Input("upload-manual-input", "contents"),
        prevent_initial_call=True,
    )
    def on_upload_manual_input(contents):
        if contents is None:
            return [], None
        data = manual_input_parser.parse(_decode(contents))
        checklist = _checklist(["RCCP", "Calendar"], data.sheets_found)
        return checklist, contents

    @app.callback(
        Output("fallback-banner", "children"),
        Output("fallback-banner", "style"),
        Output("run-button", "disabled"),
        Output("store-validation", "data"),
        Input("store-mps-input", "data"),
        Input("store-mps-output", "data"),
        Input("store-manual-input", "data"),
    )
    def on_validate(mps_input_contents, mps_output_contents, manual_input_contents):
        if mps_input_contents is None or mps_output_contents is None:
            # MPS Input/Output are mandatory -- no fallback (Section 5).
            return [], {"display": "none"}, True, None

        mps_input = mps_input_parser.parse(_decode(mps_input_contents))
        mps_output = mps_output_parser.parse(_decode(mps_output_contents))
        manual_input = (
            manual_input_parser.parse(_decode(manual_input_contents))
            if manual_input_contents is not None
            else manual_input_parser.parse(None)
        )

        result = validation.validate(mps_input, mps_output, manual_input)
        if not result.can_run:
            banner = [html.Div(msg) for msg in result.errors]
            return banner, {"display": "block"}, True, None

        decisions = resolve_fallback(result)
        if decisions.any_fallback_applied:
            banner = [html.Div(msg) for msg in decisions.messages]
            return banner, {"display": "block"}, False, {"degraded": True}
        return [], {"display": "none"}, False, {"degraded": False}

    @app.callback(
        Output("line-filter-dropdown", "options"),
        Input("store-mps-output", "data"),
        prevent_initial_call=True,
    )
    def on_populate_lines(mps_output_contents):
        if mps_output_contents is None:
            return []
        data = mps_output_parser.parse(_decode(mps_output_contents))
        if data.monthly_fin.empty:
            return []
        cols = mps_output_parser.plant_line_columns(data.monthly_fin)
        lines = sorted({c.split("_", 1)[1] for c in cols if "_" in c})
        return [{"label": line, "value": line} for line in lines]

    @app.callback(
        Output("run-status", "children"),
        Output("download-output", "data"),
        Input("run-button", "n_clicks"),
        State("store-mps-input", "data"),
        State("store-mps-output", "data"),
        State("store-manual-input", "data"),
        State("start-period-dropdown", "value"),
        State("end-period-dropdown", "value"),
        State("line-filter-dropdown", "value"),
        State("min-dos-input", "value"),
        prevent_initial_call=True,
    )
    def on_run(n_clicks, mps_input_contents, mps_output_contents, manual_input_contents,
               start_period, end_period, lines, min_dos):
        if not mps_input_contents or not mps_output_contents:
            return "MPS Input and MPS Output are required.", None

        params = RunParams(
            start_period=start_period, end_period=end_period,
            lines=lines or None, min_dos_override=min_dos,
        )
        manual_file = _decode(manual_input_contents) if manual_input_contents else None
        result = execute_run(_decode(mps_input_contents), _decode(mps_output_contents), manual_file, params)
        run_history.record_run(params, result)

        if result.status.value == "failed":
            return f"Run failed: {'; '.join(result.errors)}", None

        status_text = "Run complete" + (" (degraded mode — see Assumption Applied tab)" if result.status.value == "degraded" else "")
        return status_text, dcc.send_file(result.output_path)
