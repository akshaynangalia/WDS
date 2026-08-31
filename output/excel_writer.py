"""
Assembles the final downloadable workbook from an EngineResult:
    WEEKLY_PLAN, COMPARISON_TABLE, DIFC_SUMMARY, ASSUMPTIONS_APPLIED

Contract:
    consumes: EngineResult, output file path
    produces: the file path (workbook written to disk)
"""
from __future__ import annotations

import pandas as pd

from engine.engine_result import EngineResult
from output import assumptions_sheet, comparison_table_sheet, difc_summary_sheet, weekly_plan_sheet


def write(result: EngineResult, output_path: str) -> str:
    weekly_plan_df = weekly_plan_sheet.build_dataframe(result)
    comparison_df = comparison_table_sheet.build_dataframe(result)
    difc_df = difc_summary_sheet.build_dataframe(result)
    assumptions_df = assumptions_sheet.build_dataframe(result)

    with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
        weekly_plan_df.to_excel(writer, sheet_name="WEEKLY_PLAN", index=False)
        comparison_df.to_excel(writer, sheet_name="COMPARISON_TABLE", index=False)
        difc_df.to_excel(writer, sheet_name="DIFC_SUMMARY", index=False)
        assumptions_df.to_excel(writer, sheet_name="ASSUMPTIONS_APPLIED", index=False)

    return output_path
