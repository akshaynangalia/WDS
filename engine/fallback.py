"""
Implements the Fallback Matrix — Development Planning Document, Section 5.

MPS Input and MPS Output have no fallback (the run hard-stops if either is
missing — enforced by ValidationResult.can_run, checked in run_manager).
Manual Input (RCCP + Calendar) is the one input with defined defaults, applied
per missing field rather than as a single all-or-nothing switch.

Contract:
    consumes: ValidationResult
    produces: FallbackDecisions
"""
from __future__ import annotations

from dataclasses import dataclass, field

from engine.parsers.validation import ValidationResult


@dataclass
class FallbackDecisions:
    use_default_priority: bool = False
    use_default_moq: bool = False
    use_default_target_dos: bool = False
    use_default_calendar: bool = False
    use_monthly_avg_dos: bool = False
    messages: list[str] = field(default_factory=list)

    @property
    def any_fallback_applied(self) -> bool:
        return bool(self.messages)


def resolve(validation: ValidationResult) -> FallbackDecisions:
    decisions = FallbackDecisions()

    if not validation.priority_present:
        decisions.use_default_priority = True
        decisions.messages.append(
            "Priority not supplied — using file order. Sequencing does not reflect "
            "business urgency."
        )

    if not validation.moq_present:
        decisions.use_default_moq = True
        decisions.messages.append(
            "MOQ not supplied — run-length constraints not enforced."
        )

    if not validation.target_dos_present:
        decisions.use_default_target_dos = True
        decisions.messages.append(
            "Target DOS not supplied — no urgency-based front-loading; allocation "
            "is capacity-driven only."
        )

    if not validation.calendar_present:
        decisions.use_default_calendar = True
        decisions.messages.append(
            "Calendar not supplied — capacity is a coarse approximation (assumes a "
            "full 7-day week, zero downtime, no split-week carryover). Treat outputs "
            "from this run with caution."
        )

    if not validation.weekly_demand_present:
        decisions.use_monthly_avg_dos = True
        decisions.messages.append(
            "Weekly Demand not supplied — Weekly DIFC approximated from monthly "
            "average demand rather than true weekly demand."
        )

    return decisions
