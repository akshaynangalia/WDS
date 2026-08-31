"""Shared dataclasses between orchestration/ and app/."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum


class RunStatus(str, Enum):
    SUCCESS = "success"
    DEGRADED = "degraded"   # succeeded, but with fallback defaults applied
    FAILED = "failed"


@dataclass
class RunParams:
    start_period: int
    end_period: int
    lines: list[str] | None = None          # None = all lines
    min_dos_override: float | None = None
    opening_carryover: dict | None = None    # {(plant_line, link_code): float}, first period only


@dataclass
class RunResult:
    status: RunStatus
    output_path: str | None
    assumption_messages: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    run_id: int | None = None
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
