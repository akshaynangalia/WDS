"""
The data behind the Run Report sheet -- plain values, no behaviour.

Lives at engine level (not orchestration) because the output layer renders it
and output/ must never import from orchestration/. orchestration/run_manager.py
fills it in; output/run_report_sheet.py draws it.

The report is written INSIDE the workbook it describes, so it can only know
what has happened by the time the workbook is being written: total elapsed
time is "until the report was written" and the Excel-write stage itself is not
listed. The log's RUN_END line carries the true final duration.

Contract:
    consumes: (nothing -- a data holder)
    produces: RunReport, attached to EngineResult.run_report
"""
from __future__ import annotations

from dataclasses import dataclass, field

from engine.health_checks import HealthReport


@dataclass
class StageTiming:
    name: str
    runs: int          # e.g. allocation runs once per period
    seconds: float     # total across all runs of this stage


@dataclass
class RunReport:
    reference: str                                   # same id as the log lines' run=<id>
    generated_utc: str                               # "2026-09-19 12:54:09"
    version: str
    status: str                                      # "success" | "degraded"
    periods: str                                     # "1-10"
    lines: str                                       # "all" or a comma-separated list
    min_dos_entered: float | None                    # what the planner typed; NOT applied by the engine yet
    inputs: list[tuple[str, str]]                    # (label, "sha256=... size=...")
    stages: list[StageTiming]
    elapsed_seconds: float                           # until the report was written
    fallback_messages: list[str] = field(default_factory=list)   # run-level defaults applied
    capacity_messages: list[str] = field(default_factory=list)   # distinct capacity fallbacks
    health: HealthReport | None = None               # None = the checks could not run
