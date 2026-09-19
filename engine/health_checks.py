"""
Run-time health checks on a finished run's reconciled rows.

Read-only: this module inspects SkuAllocation rows and reports; it never
changes a quantity. A failed check does not stop the run or block the output
-- orchestration logs it loudly and surfaces it to the user (client decision:
"still produce the output with a loud warning").

Checks:
    conservation  produced + carryover_out == FIN + carryover_in, per row.
                  Every quantity is rounded to 0.1 T at each step, so exact
                  equality is not achievable. Measured on the client's real
                  data (942 rows): worst deviation 0.22 T, mean 0.02 T. The
                  tolerance is therefore 0.5 T -- comfortably above rounding
                  noise, far below anything that would be a real fault (a
                  lost or double-counted Link Code is tens of tonnes). The
                  observed maximum is always reported so drift is visible.
    nan           no quantity field is NaN/None (a NaN silently passes every
                  numeric comparison, so it needs its own check).
    negative      no quantity is negative (production/carryover cannot be).

Contract:
    consumes: list[SkuAllocation] (all periods, post-reconciliation)
    produces: HealthReport -- consumed by orchestration (logging, RunResult)
              and, later, by the output layer's Run Report.
"""
from __future__ import annotations

from dataclasses import dataclass, field

CONSERVATION_TOLERANCE_T = 0.5
NEGATIVE_TOLERANCE_T = 0.05
_QUANTITY_FIELDS = (
    "wk1a", "wk1", "wk2", "wk3", "wk4", "wk5",
    "carryover_next", "carryover_fin_in", "current_fin",
)


@dataclass
class HealthCheck:
    name: str
    ok: bool
    detail: str                                            # one line, for logs and the Run Report
    failures: list[str] = field(default_factory=list)      # row-level messages, empty when ok


@dataclass
class HealthReport:
    checks: list[HealthCheck]

    @property
    def ok(self) -> bool:
        return all(c.ok for c in self.checks)

    @property
    def warnings(self) -> list[str]:
        """One short line per failed check -- shown to the user."""
        return [f"{c.name}: {c.detail}" for c in self.checks if not c.ok]


def _row_key(row) -> str:
    return f"{row.plant_line}/{row.link_code}/P{row.period}"


def _is_nan(value) -> bool:
    return value is None or value != value  # NaN is the only value not equal to itself


def check(rows: list) -> HealthReport:
    conservation_failures: list[str] = []
    nan_failures: list[str] = []
    negative_failures: list[str] = []
    max_dev = 0.0

    for row in rows:
        bad_fields = [f for f in _QUANTITY_FIELDS if _is_nan(getattr(row, f))]
        if bad_fields:
            nan_failures.append(f"{_row_key(row)}: {', '.join(bad_fields)} is NaN")
            continue  # arithmetic on NaN is meaningless

        for f in _QUANTITY_FIELDS:
            value = getattr(row, f)
            if value < -NEGATIVE_TOLERANCE_T:
                negative_failures.append(f"{_row_key(row)}: {f}={value:.2f} is negative")

        dev = (row.total_all + row.carryover_next) - (row.current_fin + row.carryover_fin_in)
        max_dev = max(max_dev, abs(dev))
        if abs(dev) > CONSERVATION_TOLERANCE_T:
            conservation_failures.append(
                f"{_row_key(row)}: produced+carryover_out differs from FIN+carryover_in by {dev:+.2f} T"
            )

    n = len(rows)
    return HealthReport(checks=[
        HealthCheck(
            "conservation", not conservation_failures,
            f"rows={n} max_dev={max_dev:.3f}T tol={CONSERVATION_TOLERANCE_T}T "
            f"violations={len(conservation_failures)}",
            conservation_failures,
        ),
        HealthCheck("nan", not nan_failures, f"rows={n} violations={len(nan_failures)}", nan_failures),
        HealthCheck("negative", not negative_failures, f"rows={n} violations={len(negative_failures)}", negative_failures),
    ])
