"""
Consolidation is tested against the REAL sample files structurally (does it
build a sane table, are the derived columns populated correctly) rather than
against exact numbers -- the sample files don't share a common date range
(Development Planning Document, Risk Register), so there's no numerically
"correct" answer to check against here. The exact-number checks against the
ground-truth worked example live in test_allocation.py instead, using
synthetic, controlled input built directly from the doc's own figures.
"""
from __future__ import annotations

import os

from engine import consolidation, fallback
from engine.parsers import manual_input_parser, mps_input_parser, mps_output_parser, validation

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures", "sample_files")


def _load_all():
    mps_input = mps_input_parser.parse(os.path.join(FIXTURES, "MPS_Input_File.xlsx"))
    mps_output = mps_output_parser.parse(os.path.join(FIXTURES, "MPS_Output_File.xlsx"))
    manual_input = manual_input_parser.parse(os.path.join(FIXTURES, "Manual_Input.xlsx"))
    return mps_input, mps_output, manual_input


def test_consolidation_builds_nonempty_table_with_expected_columns():
    mps_input, mps_output, manual_input = _load_all()
    result = validation.validate(mps_input, mps_output, manual_input)
    decisions = fallback.resolve(result)

    table = consolidation.build(mps_input, mps_output, manual_input, decisions)
    df = table.data
    assert not df.empty
    assert list(df.columns) == consolidation.CONSOLIDATED_COLUMNS
    assert (df["current_fin"] > 0).all()  # zero-FIN rows should have been filtered out
    assert df["plant"].notna().all()
    assert df["line"].notna().all()


def test_dos_gap_is_never_negative():
    mps_input, mps_output, manual_input = _load_all()
    result = validation.validate(mps_input, mps_output, manual_input)
    decisions = fallback.resolve(result)
    table = consolidation.build(mps_input, mps_output, manual_input, decisions)
    assert (table.data["dos_gap"] >= 0).all()


def test_no_rccp_match_falls_back_gracefully_without_crashing():
    # Manual Input present overall, but its Link Code Desc values are text
    # descriptions that won't match every SKU in the sample MPS Output file
    # (documented join-key ambiguity -- see consolidation.py's module docstring).
    # This should degrade gracefully per-row, not crash.
    mps_input, mps_output, manual_input = _load_all()
    result = validation.validate(mps_input, mps_output, manual_input)
    decisions = fallback.resolve(result)
    table = consolidation.build(mps_input, mps_output, manual_input, decisions)
    # every row must have SOME priority/target_dos value (defaulted or matched), never NaN
    assert table.data["priority"].notna().all()
    assert table.data["target_dos"].notna().all()
