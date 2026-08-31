from __future__ import annotations

import pandas as pd
import pytest

from engine.consolidation import CONSOLIDATED_COLUMNS, ConsolidatedTable
from engine.fallback import FallbackDecisions


def make_row(
    plant_line: str,
    period: int = 1,
    link_code: str = "L1",
    sku: str = "L1",
    current_fin: float = 100.0,
    opening_dos: float = 20.0,
    target_dos: float = 20.0,
    priority: float = 1.0,
    moq_days=None,
    throughput_per_day: float = 24.0,
    ge_pct: float = 1.0,
    month_num: int = 1,
    month_key: str = "Jan-26",
):
    return {
        "period": period, "month_num": month_num, "month_key": month_key,
        "plant": plant_line.split("_", 1)[0], "line": plant_line.split("_", 1)[1],
        "plant_line": plant_line, "link_code": link_code, "link_desc": link_code, "sku": sku,
        "current_fin": current_fin, "opening_dos": opening_dos, "target_dos": target_dos,
        "dos_gap": max(target_dos - opening_dos, 0.0),
        "priority": priority, "moq_days": moq_days,
        "throughput_per_day": throughput_per_day, "ge_pct": ge_pct,
        "row_assumptions": [],
    }


def make_consolidated(rows: list[dict]) -> ConsolidatedTable:
    df = pd.DataFrame.from_records(rows, columns=CONSOLIDATED_COLUMNS)
    return ConsolidatedTable(data=df)


@pytest.fixture
def no_fallback() -> FallbackDecisions:
    return FallbackDecisions()
