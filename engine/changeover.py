"""
REQ-CR-05 -- Month-end changeover / split-week handling.

This is a DELIBERATE NO-OP. The business rule for identifying "the last SKU
running at month-end" and how it should carry over as the opening SKU for
the next month is not yet defined by the client (pending a session between
Amit/Intelytics and Vijay/Mondelez -- see Architecture Document, Section 8,
and Development Planning Document, Risk Register item 1).

Do NOT implement guessed logic here. This function exists purely as the
seam the Development Planning Document (Section 2.2, "engine/changeover.py")
calls for, so that when the real rule is provided, it plugs in here without
requiring changes to allocation.py, reconciliation.py, or anything upstream.

Contract:
    consumes: ReconciledResult
    produces: ReconciledResult, unchanged (pass-through)
"""
from __future__ import annotations

from engine.reconciliation import ReconciledResult


def apply(reconciled: ReconciledResult) -> ReconciledResult:
    """No-op. See module docstring."""
    return reconciled
