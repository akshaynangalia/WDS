"""
Assembles the final downloadable workbook from an EngineResult:
    Weekly Plan, Comparison Table, Weekly DIFC Summary, Assumption Applied

Weekly Plan, Comparison Table and Weekly DIFC Summary all share the same
wide/transposed shape (period pivot, two-row banded header) -- see
output/period_pivot.py for why weekly_plan_sheet.py doesn't share the same
code path as the other two despite the identical shape. Assumption Applied
stays a plain one-row-header sheet.

Contract:
    consumes: EngineResult, output file path
    produces: the file path (workbook written to disk)
"""
from __future__ import annotations

import pandas as pd

from engine.engine_result import EngineResult
from output import (
    assumptions_sheet,
    comparison_table_sheet,
    difc_summary_sheet,
    styling,
    weekly_plan_sheet,
)

# (sheet name, module, static-field-count) for the three period-pivoted sheets.
_PIVOTED_SHEETS = (
    ("Weekly Plan", weekly_plan_sheet, len(weekly_plan_sheet.LEFT_COLS)),
    ("Comparison Table", comparison_table_sheet, len(comparison_table_sheet.STATIC_FIELDS)),
    ("Weekly DIFC Summary", difc_summary_sheet, len(difc_summary_sheet.STATIC_FIELDS)),
)


def write(result: EngineResult, output_path: str) -> str:
    assumptions_df = assumptions_sheet.build_dataframe(result)
    pivoted = [
        (sheet_name, *module.build(result), n_static)
        for sheet_name, module, n_static in _PIVOTED_SHEETS
    ]

    with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
        for sheet_name, df, hdr1, hdr2, n_static in pivoted:
            df.to_excel(writer, sheet_name=sheet_name, index=False, header=False, startrow=2)

        assumptions_df.to_excel(writer, sheet_name="Assumption Applied", index=False)
        styling.style_header_row(
            writer.sheets["Assumption Applied"], ncols=max(len(assumptions_df.columns), 1)
        )

        for sheet_name, df, hdr1, hdr2, n_static in pivoted:
            ws = writer.sheets[sheet_name]
            styling.style_period_banded_header(ws, hdr1, hdr2, n_id_cols=n_static)

        # Weekly Plan is the only pivoted sheet with a footnote today (the
        # W1 = W1A + W1 fold) -- add others here the same way if a future
        # sheet needs one.
        weekly_plan_df = pivoted[0][1]
        note_row = len(weekly_plan_df) + 4  # data occupies rows 3..(n+2); blank row; note
        writer.sheets["Weekly Plan"].cell(row=note_row, column=1, value=weekly_plan_sheet.NOTE)

    return output_path
