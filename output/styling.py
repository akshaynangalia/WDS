"""Shared header styling for every output tab, matching the client-supplied
sample workbook ("Sample Output Format.xlsx"): a purple fill with bold white
centered text and a thin border, applied to row 1 of each sheet.
"""
from __future__ import annotations

from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.worksheet.worksheet import Worksheet

HEADER_FILL = PatternFill(start_color="FF4F2170", end_color="FF4F2170", fill_type="solid")
HEADER_FONT = Font(name="Calibri", size=10, bold=True, color="FFFFFFFF")
HEADER_ALIGNMENT = Alignment(horizontal="center", vertical="center")
HEADER_BORDER = Border(*(Side(style="thin") for _ in range(4)))
HEADER_ROW_HEIGHT = 19.8


def style_header_row(ws: Worksheet, ncols: int) -> None:
    ws.row_dimensions[1].height = HEADER_ROW_HEIGHT
    for col in range(1, ncols + 1):
        cell = ws.cell(row=1, column=col)
        cell.fill = HEADER_FILL
        cell.font = HEADER_FONT
        cell.alignment = HEADER_ALIGNMENT
        cell.border = HEADER_BORDER


def style_period_banded_header(
    ws: Worksheet, header_row1: list[str], header_row2: list[str], n_id_cols: int
) -> None:
    """Two-row banded header for the Weekly Plan sheet: row 1 carries
    the month band (merged across each period block), row 2 the week labels. The
    id columns (first ``n_id_cols``) are merged vertically across both rows.
    """
    for row_idx, labels in ((1, header_row1), (2, header_row2)):
        ws.row_dimensions[row_idx].height = HEADER_ROW_HEIGHT
        for col_idx, label in enumerate(labels, start=1):
            cell = ws.cell(row=row_idx, column=col_idx, value=label)
            cell.fill = HEADER_FILL
            cell.font = HEADER_FONT
            cell.alignment = HEADER_ALIGNMENT
            cell.border = HEADER_BORDER

    for col_idx in range(1, n_id_cols + 1):
        ws.merge_cells(start_row=1, start_column=col_idx, end_row=2, end_column=col_idx)

    start = n_id_cols + 1
    while start <= len(header_row1):
        band = header_row1[start - 1]
        end = start
        while end < len(header_row1) and header_row1[end] == band:
            end += 1
        if end > start:
            ws.merge_cells(start_row=1, start_column=start, end_row=1, end_column=end)
        start = end + 1
