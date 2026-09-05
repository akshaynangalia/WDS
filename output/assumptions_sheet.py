"""
Writes the Assumption Applied tab — Development Planning Document, Section 6
("a planner opening the file six weeks from now should understand why a
number looks the way it does, without asking the person who ran it").

Empty dataframe (headers only) when nothing was defaulted -- a fully-supplied
run should produce a visibly empty tab, not a missing one.
"""
from __future__ import annotations

import pandas as pd

from engine.engine_result import EngineResult


def build_dataframe(result: EngineResult) -> pd.DataFrame:
    messages = result.all_assumption_messages
    if not messages:
        return pd.DataFrame(columns=["Assumption Applied"])
    # de-duplicate while preserving order (row-level messages can repeat)
    seen = []
    for m in messages:
        if m not in seen:
            seen.append(m)
    return pd.DataFrame({"Assumption Applied": seen})
