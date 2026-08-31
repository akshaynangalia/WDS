"""
The single entry point the UI (app/callbacks.py) calls to execute a full run.
Wraps the entire engine call sequence documented in the Development Planning
Document, Section 2.3.

Periods are processed in ascending order so that each period's Carryover
M+1 (engine/carryover.py) feeds directly into the next period's carryover-in,
closing the loop across the planning horizon exactly as the ground-truth doc
describes.

Contract:
    consumes: file paths/objects for the three inputs (manual_input may be
              None), RunParams
    produces: RunResult
"""
from __future__ import annotations

import os
from datetime import datetime, timezone

from engine import allocation, capacity, carryover, changeover, consolidation, dos_difc, fallback as fallback_module
from engine.engine_result import EngineResult
from engine.parsers import manual_input_parser, mps_input_parser, mps_output_parser, validation
from engine.reconciliation import ReconciledResult, reconcile
from orchestration.models import RunParams, RunResult, RunStatus
from output import excel_writer


def execute_run(
    mps_input_file,
    mps_output_file,
    manual_input_file,
    params: RunParams,
    output_dir: str = "/tmp",
) -> RunResult:
    try:
        mps_input = mps_input_parser.parse(mps_input_file)
        mps_output = mps_output_parser.parse(mps_output_file)
        manual_input = manual_input_parser.parse(manual_input_file)
    except Exception as exc:  # malformed workbook, unreadable file, etc.
        return RunResult(status=RunStatus.FAILED, output_path=None, errors=[str(exc)])

    validation_result = validation.validate(mps_input, mps_output, manual_input)
    if not validation_result.can_run:
        return RunResult(status=RunStatus.FAILED, output_path=None, errors=validation_result.errors)

    decisions = fallback_module.resolve(validation_result)

    consolidated = consolidation.build(mps_input, mps_output, manual_input, decisions)
    df = consolidated.data
    df = df[(df["period"] >= params.start_period) & (df["period"] <= params.end_period)]
    if params.lines:
        df = df[df["line"].isin(params.lines)]

    all_reconciled_rows = []
    capacity_messages: list[str] = []
    carry_in = dict(params.opening_carryover or {})

    for period in sorted(df["period"].unique()):
        period_table = consolidation.ConsolidatedTable(data=df[df["period"] == period])
        alloc_result = allocation.run(period_table, manual_input.calendar, decisions, carry_in)
        capacity_messages.extend(alloc_result.capacity_messages)
        reconciled = reconcile(alloc_result)
        reconciled = changeover.apply(reconciled)  # no-op, per REQ-CR-05 seam
        all_reconciled_rows.extend(reconciled.rows)
        carry_in = carryover.extract_carryover(reconciled)

    combined_reconciled = ReconciledResult(rows=all_reconciled_rows)
    difc_result = dos_difc.compute(all_reconciled_rows, df, mps_input.demand, decisions)

    engine_result = EngineResult(
        reconciled=combined_reconciled,
        difc=difc_result,
        fallback=decisions,
        capacity_messages=capacity_messages,
    )

    os.makedirs(output_dir, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    output_path = os.path.join(output_dir, f"weekly_plan_{timestamp}.xlsx")
    excel_writer.write(engine_result, output_path)

    status = RunStatus.DEGRADED if decisions.any_fallback_applied else RunStatus.SUCCESS
    return RunResult(
        status=status,
        output_path=output_path,
        assumption_messages=engine_result.all_assumption_messages,
    )
