"""
Parses the MPS Input workbook.

Sheets read:
    - SKU Master            -> SKU / Link Code mapping
    - 2.Demand Input        -> monthly demand per Link Code, per period
    - Period Calendar Matrix-> maps calendar dates to Period numbers
    - 4.SOC Sheet & Flag    -> GE% and SOC (used as effective throughput proxy) per
                               Link Code / Period / Plant / Line

See Development Planning Document, Section 2.2, for this module's contract:
    consumes: a file path or file-like object
    produces: MPSInputData
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

REQUIRED_SHEETS = (
    "SKU Master",
    "2.Demand Input",
    "Period Calendar Matrix",
    "4.SOC Sheet & Flag",
)


@dataclass
class MPSInputData:
    sku_master: pd.DataFrame
    demand: pd.DataFrame
    period_calendar: pd.DataFrame
    soc: pd.DataFrame
    sheets_found: set[str]


def parse(file) -> MPSInputData:
    """Read the MPS Input workbook. `file` is a path or file-like object.

    The workbook is opened in a `with` block so its file handle is released
    before this function returns. pandas' ExcelFile does not close itself; a
    lingering handle locks the file on Windows (breaking temp-dir cleanup in
    tests) and leaks a file descriptor per run everywhere else. Every sheet is
    fully materialised by `xl.parse()` inside the block, so the returned
    DataFrames do not depend on the handle staying open.
    """
    with pd.ExcelFile(file) as xl:
        sheets_found = set(xl.sheet_names)

        def _read(name: str) -> pd.DataFrame:
            if name not in sheets_found:
                return pd.DataFrame()
            return xl.parse(name)

        return MPSInputData(
            sku_master=_read("SKU Master"),
            demand=_read("2.Demand Input"),
            period_calendar=_read("Period Calendar Matrix"),
            soc=_read("4.SOC Sheet & Flag"),
            sheets_found=sheets_found,
        )


def missing_sheets(data: MPSInputData) -> list[str]:
    return [s for s in REQUIRED_SHEETS if s not in data.sheets_found]
