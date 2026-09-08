"""
Assembles the final downloadable workbook from an EngineResult:
    Weekly Plan, Comparison Table, Weekly DIFC Summary, Assumption Applied

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
    weekly_plan_transposed_sheet,
)


def write(result: EngineResult, output_path: str) -> str:
    weekly_plan_df = weekly_plan_sheet.build_dataframe(result)
    comparison_df = comparison_table_sheet.build_dataframe(result)
    difc_df = difc_summary_sheet.build_dataframe(result)
    assumptions_df = assumptions_sheet.build_dataframe(result)
    transposed_df, transposed_hdr1, transposed_hdr2 = weekly_plan_transposed_sheet.build(result)

    with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
        weekly_plan_df.to_excel(writer, sheet_name="Weekly Plan", index=False)
        transposed_df.to_excel(
            writer, sheet_name="Weekly Plan Transposed", index=False, header=False, startrow=2
        )
        comparison_df.to_excel(writer, sheet_name="Comparison Table", index=False)
        difc_df.to_excel(writer, sheet_name="Weekly DIFC Summary", index=False)
        assumptions_df.to_excel(writer, sheet_name="Assumption Applied", index=False)

        for df, sheet_name in (
            (weekly_plan_df, "Weekly Plan"),
            (comparison_df, "Comparison Table"),
            (difc_df, "Weekly DIFC Summary"),
            (assumptions_df, "Assumption Applied"),
        ):
            styling.style_header_row(writer.sheets[sheet_name], ncols=max(len(df.columns), 1))

        ws_transposed = writer.sheets["Weekly Plan Transposed"]
        styling.style_period_banded_header(
            ws_transposed, transposed_hdr1, transposed_hdr2,
            n_id_cols=len(weekly_plan_transposed_sheet.ID_COLS),
        )
        note_row = len(transposed_df) + 4  # data occupies rows 3..(n+2); blank row; note
        ws_transposed.cell(row=note_row, column=1, value=weekly_plan_transposed_sheet.NOTE)

    return output_path
