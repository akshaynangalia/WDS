from __future__ import annotations

import logging

from app import callbacks
from orchestration.models import RunParams, RunResult, RunStatus


def test_a_failing_history_write_never_costs_the_planner_a_finished_run(monkeypatch):
    # e.g. a read-only app folder on the host, or a locked run_history.db.
    def boom(params, result):
        raise OSError("unable to open database file")

    monkeypatch.setattr(callbacks.run_history, "record_run", boom)

    records: list[str] = []

    class _Capture(logging.Handler):
        def emit(self, record):
            records.append(record.getMessage())

    handler = _Capture()
    logger = logging.getLogger("wds.run")
    logger.addHandler(handler)
    try:
        result = RunResult(status=RunStatus.SUCCESS, output_path="x.xlsx", trace_id="ref-123")
        callbacks._safe_record_run(RunParams(start_period=1, end_period=1), result)  # must not raise
    finally:
        logger.removeHandler(handler)

    assert any("HISTORY_WRITE_FAILED" in m and "ref-123" in m and "OSError" in m for m in records)


def test_a_working_history_write_is_passed_through(monkeypatch):
    seen = []
    monkeypatch.setattr(callbacks.run_history, "record_run", lambda params, result: seen.append(result))
    result = RunResult(status=RunStatus.SUCCESS, output_path="x.xlsx")
    callbacks._safe_record_run(RunParams(start_period=1, end_period=1), result)
    assert seen == [result]
