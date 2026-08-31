"""
Bundles everything the output layer (output/excel_writer.py) needs into one
object, so orchestration/run_manager.py has a single, clean handoff point
between the engine and the output generator.

Contract:
    consumes: ReconciledResult, DIFCResult, FallbackDecisions, capacity messages
    produces: EngineResult
"""
from __future__ import annotations

from dataclasses import dataclass, field

from engine.dos_difc import DIFCResult
from engine.fallback import FallbackDecisions
from engine.reconciliation import ReconciledResult


@dataclass
class EngineResult:
    reconciled: ReconciledResult
    difc: DIFCResult
    fallback: FallbackDecisions
    capacity_messages: list[str] = field(default_factory=list)

    @property
    def all_assumption_messages(self) -> list[str]:
        messages = list(self.fallback.messages) + list(self.capacity_messages)
        for row in self.reconciled.rows:
            messages.extend(row.assumptions)
        return messages
