"""
Parses the MPS Input workbook.

Sheets read:
    - SKU Master            -> SKU / Link Code mapping
    - 2.Demand Input        -> monthly demand per Link Code, per period
    - Period Calendar Matrix-> maps calendar dates to Period numbers
    - 4.SOC Sheet & Flag    -> GE% and SOC (used as effective throughput proxy) per
                               Link Code / Period / Plant / Line

SKU Master is the DESIGNATED SKU <-> Link Code mapping sheet -- but it is
parsed and validated here, then never consumed downstream. engine/consolidation.py
currently pulls SKU and Link Code straight off the FIN sheet (MPS Output's
`SKU Line Loading 1`) instead, which is harmless only because SKU == Link Code
1:1 in all current client data. If a SKU <-> Link Code mapping is ever actually
needed by future code -- most notably once the parked FIN-source switch to
`Link Code Line Loading 1` happens (that sheet has no SKU column at all) -- it
must come from THIS sheet, not from the FIN sheet. See LIMITATIONS.md L4:
SKU Master itself has no column literally named "SKU" (its closest analog is
"List Code"), so that still needs client confirmation before any code relies
on it for a real mapping.

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
