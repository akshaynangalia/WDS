"""
Parses the MPS Output workbook.

Sheets read:
    - SKU Line Loading 1 -> monthly FIN (Line-SKU-Month), wide-format with one
                            column per Plant_Line combination
    - Linkcode_DIFC      -> DOS trend per Link Code, one column per period
                            (this is where "Opening DOS" for a given period comes from)

See Development Planning Document, Section 2.2.
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

REQUIRED_SHEETS = ("SKU Line Loading 1", "Linkcode_DIFC")


@dataclass
class MPSOutputData:
    monthly_fin: pd.DataFrame
    linkcode_difc: pd.DataFrame
    sheets_found: set[str]


def parse(file) -> MPSOutputData:
    # Opened in a `with` block so the workbook handle is released before this
    # function returns -- see the note in mps_input_parser.parse for why.
    with pd.ExcelFile(file) as xl:
        sheets_found = set(xl.sheet_names)

        def _read(name: str) -> pd.DataFrame:
            if name not in sheets_found:
                return pd.DataFrame()
            return xl.parse(name)

        return MPSOutputData(
            monthly_fin=_read("SKU Line Loading 1"),
            linkcode_difc=_read("Linkcode_DIFC"),
            sheets_found=sheets_found,
        )


def missing_sheets(data: MPSOutputData) -> list[str]:
    return [s for s in REQUIRED_SHEETS if s not in data.sheets_found]


def plant_line_columns(monthly_fin: pd.DataFrame) -> list[str]:
    """Columns after the fixed metadata columns are Plant_Line production columns.
    Requires an underscore in the name -- this also correctly excludes duplicate
    columns pandas renames on read (e.g. a repeated "Period" column becomes
    "Period.1" in the sample file, which is not a Plant_Line column at all)."""
    fixed = {
        "Period", "SKU", "Brand", "Link Code", "Link Desc Description",
        "List Description", "O/S", "DOS",
    }
    return [c for c in monthly_fin.columns if c not in fixed and "_" in str(c)]
