"""
The single entry point the UI (app/callbacks.py) calls to execute a full run.
Wraps the entire engine call sequence documented in the Development Planning
Document, Section 2.3.

Periods are processed in ascending order so that each period's Carryover
M+1 (engine/carryover.py) feeds directly into the next period's carryover-in,
closing the loop across the planning horizon exactly as the ground-truth doc
describes. REQ-CR-05's priority overrides (engine/changeover.py) are threaded
forward the same way -- computed from one period's finished allocation, fed
into the next period's allocation.run() call.

Logging and failure handling: every stage runs inside _stage(), which logs its
start/end and duration. An exception in any stage is logged with its full
traceback and returned as a FAILED RunResult naming the stage (and period) --
it never escapes as an unrecorded crash. Parse and validation failures keep
their existing message text. Nothing here changes a calculation: the engine
calls are exactly the ones that were already made, in the same order.

Contract:
    consumes: file paths/objects for the three inputs (manual_input may be
              None), RunParams
    produces: RunResult
"""
from __future__ import annotations

import contextlib
import hashlib
import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path

from engine import allocation, capacity, carryover, changeover, consolidation, dos_difc, fallback as fallback_module, health_checks
from engine.engine_result import EngineResult
from engine.parsers import manual_input_parser, mps_input_parser, mps_output_parser, validation
from engine.reconciliation import ReconciledResult, reconcile
from orchestration import logging_config
from orchestration.models import RunParams, RunResult, RunStatus
from output import excel_writer

log = logging.getLogger("wds.run")

_MAX_LOGGED_MESSAGES = 20  # per kind, so one bad input cannot flood the log
_MAX_LOGGED_ROW_FAILURES = 10


class _StageFailed(Exception):
    def __init__(self, stage: str, period, original: Exception):
        super().__init__(f"{stage}: {original}")
        self.stage = stage
        self.period = period
        self.original = original


@contextlib.contextmanager
def _stage(name: str, period=None):
    """Log a stage's start/end/duration; turn any exception into _StageFailed
    (after logging its traceback). Per-period sub-stages log at DEBUG so a
    normal run stays readable; a failure is always logged at ERROR."""
    where = f" period={period}" if period is not None else ""
    emit = log.debug if period is not None else log.info
    emit("STAGE %s START%s", name, where)
    started = time.perf_counter()
    try:
        yield
    except Exception as exc:
        log.exception("STAGE %s FAILED%s %s: %s", name, where, type(exc).__name__, exc)
        raise _StageFailed(name, period, exc) from exc
    emit("STAGE %s END%s %.2fs", name, where, time.perf_counter() - started)


def _fingerprint(source) -> str:
    """Identify an input without keeping it: short SHA-256 + size. Works for a
    path or an in-memory upload; never raises."""
    try:
        if source is None:
            return "not-supplied"
        if isinstance(source, (str, os.PathLike)):
            data = Path(source).read_bytes()
        elif hasattr(source, "getvalue"):
            data = source.getvalue()  # BytesIO: does not move the read position
        else:
            return "n/a"
        return f"sha256={hashlib.sha256(data).hexdigest()[:12]} size={len(data)}"
    except Exception:
        return "n/a"


def _log_messages(kind: str, messages) -> None:
    unique = list(dict.fromkeys(messages))
    for message in unique[:_MAX_LOGGED_MESSAGES]:
        log.warning("%s %s", kind, message)
    if len(unique) > _MAX_LOGGED_MESSAGES:
        log.warning("%s ... and %d more distinct messages (all are in the Assumption Applied tab)",
                    kind, len(unique) - _MAX_LOGGED_MESSAGES)


def execute_run(
    mps_input_file,
    mps_output_file,
    manual_input_file,
    params: RunParams,
    output_dir: str = "/tmp",
) -> RunResult:
    trace_id = logging_config.new_run_id()
    with logging_config.run_context(trace_id):
        started = time.perf_counter()
        log.info("RUN_START periods=%s-%s lines=%s min_dos=%s version=%s",
                 params.start_period, params.end_period,
                 ",".join(params.lines) if params.lines else "all",
                 params.min_dos_override, logging_config.code_version())
        log.info("INPUT mps_input %s", _fingerprint(mps_input_file))
        log.info("INPUT mps_output %s", _fingerprint(mps_output_file))
        log.info("INPUT manual_input %s", _fingerprint(manual_input_file))

        try:
            result = _run_pipeline(mps_input_file, mps_output_file, manual_input_file, params, output_dir)
        except _StageFailed as failure:
            where = f" (period {failure.period})" if failure.period is not None else ""
            log.error("RUN_FAILED stage=%s%s", failure.stage,
                      f" period={failure.period}" if failure.period is not None else "")
            result = RunResult(
                status=RunStatus.FAILED, output_path=None,
                errors=[f"'{failure.stage}' failed{where}: {failure.original} [ref {trace_id}]"],
            )
        except Exception as exc:  # outside any wrapped stage -- still never an unrecorded crash
            log.exception("RUN_FAILED stage=unexpected %s: %s", type(exc).__name__, exc)
            result = RunResult(
                status=RunStatus.FAILED, output_path=None,
                errors=[f"Unexpected error: {exc} [ref {trace_id}]"],
            )

        result.trace_id = trace_id
        log.info("RUN_END status=%s output=%s duration=%.2fs",
                 result.status.value, result.output_path, time.perf_counter() - started)
        return result


def _run_pipeline(mps_input_file, mps_output_file, manual_input_file, params, output_dir) -> RunResult:
    try:
        with _stage("parse"):
            mps_input = mps_input_parser.parse(mps_input_file)
            mps_output = mps_output_parser.parse(mps_output_file)
            manual_input = manual_input_parser.parse(manual_input_file)
    except _StageFailed as failure:  # malformed workbook, unreadable file, etc.
        log.error("RUN_FAILED stage=parse")
        return RunResult(status=RunStatus.FAILED, output_path=None, errors=[str(failure.original)])

    with _stage("validate"):
        validation_result = validation.validate(mps_input, mps_output, manual_input)
    if not validation_result.can_run:
        log.error("RUN_FAILED stage=validate %s", "; ".join(validation_result.errors))
        return RunResult(status=RunStatus.FAILED, output_path=None, errors=validation_result.errors)

    with _stage("fallback"):
        decisions = fallback_module.resolve(validation_result)
    _log_messages("FALLBACK", decisions.messages)

    with _stage("consolidation"):
        consolidated = consolidation.build(mps_input, mps_output, manual_input, decisions)
        df = consolidated.data
        df = df[(df["period"] >= params.start_period) & (df["period"] <= params.end_period)]
        if params.lines:
            df = df[df["line"].isin(params.lines)]
    log.info("CONSOLIDATED rows=%d periods=%d", len(df), df["period"].nunique())

    all_reconciled_rows = []
    capacity_messages: list[str] = []
    carry_in = dict(params.opening_carryover or {})
    priority_override: set[tuple[str, object]] = set()

    for period in sorted(df["period"].unique()):
        period_started = time.perf_counter()
        period_table = consolidation.ConsolidatedTable(data=df[df["period"] == period])
        with _stage("allocation", period):
            alloc_result = allocation.run(period_table, manual_input.calendar, decisions, carry_in,
                                           priority_override=priority_override)
        capacity_messages.extend(alloc_result.capacity_messages)
        with _stage("reconciliation", period):
            reconciled = reconcile(alloc_result)
        all_reconciled_rows.extend(reconciled.rows)
        with _stage("carryover", period):
            carry_in = carryover.extract_carryover(reconciled)
        with _stage("changeover", period):
            priority_override = changeover.compute_priority_overrides(reconciled)
        log.info("PERIOD %s done rows=%d carryover_links=%d changeover_flags=%d %.2fs",
                 period, len(reconciled.rows), len(carry_in), len(priority_override),
                 time.perf_counter() - period_started)

    _log_messages("CAPACITY", capacity_messages)

    combined_reconciled = ReconciledResult(rows=all_reconciled_rows)
    integrity_warnings = _run_health_checks(all_reconciled_rows)

    with _stage("dos_difc"):
        difc_result = dos_difc.compute(all_reconciled_rows, df, mps_input.demand, decisions)

    engine_result = EngineResult(
        reconciled=combined_reconciled,
        difc=difc_result,
        fallback=decisions,
        capacity_messages=capacity_messages,
    )

    with _stage("excel_write"):
        os.makedirs(output_dir, exist_ok=True)
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        output_path = os.path.join(output_dir, f"weekly_plan_{timestamp}.xlsx")
        excel_writer.write(engine_result, output_path)

    status = RunStatus.DEGRADED if decisions.any_fallback_applied else RunStatus.SUCCESS
    return RunResult(
        status=status,
        output_path=output_path,
        assumption_messages=engine_result.all_assumption_messages,
        integrity_warnings=integrity_warnings,
    )


def _run_health_checks(rows: list) -> list[str]:
    """Never allowed to fail the run: a broken check is logged and skipped."""
    try:
        report = health_checks.check(rows)
    except Exception:
        log.exception("HEALTH check could not run -- skipped")
        return []
    for check in report.checks:
        if check.ok:
            log.info("HEALTH %s ok %s", check.name, check.detail)
            continue
        log.error("INTEGRITY_FAILED check=%s %s", check.name, check.detail)
        for failure in check.failures[:_MAX_LOGGED_ROW_FAILURES]:
            log.error("INTEGRITY_FAILED_ROW %s", failure)
        if len(check.failures) > _MAX_LOGGED_ROW_FAILURES:
            log.error("INTEGRITY_FAILED_ROW ... and %d more", len(check.failures) - _MAX_LOGGED_ROW_FAILURES)
    return report.warnings
