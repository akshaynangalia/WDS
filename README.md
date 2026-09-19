# Weekly Disaggregation Tool

A Python + Dash application that converts Mondelez's Monthly Production Plan (Line–SKU–Month) into a Weekly Production Plan (Line–SKU–Week), replacing the current Excel/VBA-based process. Planners upload three input workbooks, configure a planning horizon, and download a weekly plan as Excel.

## Status

**Initial implementation complete for Phases 0-8, all 34 automated tests passing.** This covers the full engine (parsers, consolidation, capacity, allocation, reconciliation, carryover, DOS/DIFC), the output workbook generator, the orchestration layer (run manager, run history), and the Dash UI. Phase 9 (thorough local UAT against a full, date-aligned dataset), Phase 10 (GitHub), and Phase 11 (Posit Connect) are not yet done — see CLAUDE.md's Current Status for the two open items that need client confirmation before Phase 9 can be signed off.

## Governing Documents

Read these, in this order, before touching code:

1. **Architecture Document v1.0** — system layers, components, data flow
2. **Spec Document v1.0** — pinned tool/library versions
3. **Development Planning Document v1.1** — the execution playbook: phase order, file-by-file plan, fallback rules, test requirements. This is the actual source of truth for "what to build next."

## Prerequisites

- Python 3.12.x (see Spec Document, Section 2 — confirm this matches what's available once Posit Connect is reached in Phase 11; local development doesn't depend on that yet)
- `pip`

## Local Setup

```bash
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

## Running the App Locally

```bash
python app/app.py
```

The app runs at `http://localhost:8050` (matching the reference UI mockups).

## Logging and Failure Handling

Every run writes one plain-text line per event (timestamps in **UTC**, marked `Z`) to **stdout** — on Posit Connect this is what appears in the content's Logs panel. Each line carries `run=<id>`; the same id is quoted as `[ref <id>]` in any failure message shown to the user, so a reported problem can be matched to its log lines.

```
2026-09-19 10:15:03Z | INFO    | run=20260919-101503-a1b2 | RUN_START periods=1-10 lines=all min_dos=None version=0.1.0+f332c67
2026-09-19 10:15:03Z | INFO    | run=20260919-101503-a1b2 | INPUT mps_input sha256=9f2c41ab07de size=1843201
2026-09-19 10:15:04Z | INFO    | run=20260919-101503-a1b2 | STAGE consolidation END 0.31s
2026-09-19 10:15:05Z | INFO    | run=20260919-101503-a1b2 | PERIOD 4 done rows=94 carryover_links=12 changeover_flags=3 0.19s
2026-09-19 10:15:06Z | INFO    | run=20260919-101503-a1b2 | HEALTH conservation ok rows=942 max_dev=0.218T tol=0.5T violations=0
2026-09-19 10:15:06Z | INFO    | run=20260919-101503-a1b2 | RUN_END status=degraded output=/tmp/weekly_plan_20260919_101506.xlsx duration=2.10s
```

- **A stage that crashes** is logged with its full traceback and shown to the user as `'allocation' failed (period 4): … [ref …]`. Grep the log for `RUN_FAILED`.
- **A failed run-time health check** (`INTEGRITY_FAILED`) does not block the output; the file is still produced, the status line carries an `INTEGRITY WARNING`, and the failing rows are logged.
- **Inputs are identified, not stored**: the log records each upload's short SHA-256 and size, so a developer can ask for the exact file behind a reported problem.
- **Run Report sheet**: every workbook produced by a run ends with a `Run Report` tab — reference (the same id as `run=` in the log), UTC time, tool version, status, input fingerprints, health-check results (a red banner if one failed), stage timings and run-level fallbacks. It is appended last so the four plan sheets keep their positions. It cannot know its own final duration (it is written inside the workbook), so it shows elapsed time *until the report was written*; the log's `RUN_END` line has the true total.
- Settings (all optional): `WDS_LOG_LEVEL` (default `INFO`; `DEBUG` adds per-period stage detail), `WDS_LOG_FILE` (extra log copy, ignored if it cannot be opened), `WDS_VERSION` (overrides the reported version).
- The version comes from the `VERSION` file (bump it in the release PR); on a development machine the short git commit is appended.

## Running Tests

```bash
pytest
```

Every engine module is validated against a hand-derived worked example (Induri ML, February — from the ground-truth disaggregation logic doc) before being considered complete. See `tests/fixtures/worked_example.py`.

## Input Files

Three Excel workbooks are needed for a run:

1. **MPS Input** — sheets: SKU Master, Demand Input, Period Calendar Matrix, SOC Sheet & Flag
2. **MPS Output** — sheets: SKU Line Loading 1 (monthly FIN), Linkcode_DIFC
3. **Manual Input** — sheets: Priority(Linkcode Level) (per-period Priority, MOQ — Link-Code level, joined by Link Code/Plant/Line), Calendar (working days, downtime)

**MPS Input and MPS Output are mandatory** — the run cannot proceed without them. **Manual Input is optional** — if it's missing or partial, the tool still runs, but falls back to conservative defaults and clearly flags every affected output (an amber banner in the UI, and an `Assumption Applied` tab in the downloaded workbook). See the Development Planning Document, Section 5, for the exact default applied per missing field.

## Project Structure

Full directory tree and per-file responsibilities are documented in the Development Planning Document, Section 2 — that's the canonical reference, not this file. In short:

- `app/` — Dash UI
- `orchestration/` — run management and run history
- `engine/` — the core disaggregation logic (pure Python, no UI dependency)
- `output/` — Excel workbook generation
- `tests/` — unit, integration, and UI tests

## Bug-Fix Workflow (UAT)

The project is in UAT, so fixes are kept **surgical** — only the files a fix strictly needs are touched, with no refactors, opportunistic cleanups, or new dependencies. One focused branch and commit per bug, landed via a pull request on the working GitHub repo.

Each fix goes through five steps, with a checkpoint for review before any code is changed:

1. **Plain-language explanation** of what is broken and why it matters.
2. **Impact and scope** — severity, rough size (files / lines), the proposed fix, the exact files and functions it touches, and whether a regression test is needed.
3. **Implementation plan** — the precise changes, and nothing beyond them.
4. **Plan review** — confirm it addresses exactly that bug and no more.
5. **Execute** — branch (`fix/<short-name>`), fix **plus its regression test**, run `pytest`, commit, push, open a PR, merge.

Every fix adds a regression test — placed in the existing `tests/` file for that area so it runs with the whole suite — that fails before the change and passes after, so the bug can't silently return.

The full text of this workflow is also in `CLAUDE.md`.

## Deployment

Not yet reached. Per project sequencing (Development Planning Document, Rule 7): local development and thorough testing happens first (Phase 9), GitHub publish comes next (Phase 10), and Posit Connect deployment comes last (Phase 11). This section will be filled in with real deployment instructions once those phases are complete.

## Open Items Discovered While Building (need client confirmation)

1. **Reconciliation gap magnitude.** Per a literal reading of the ground-truth logic doc, reconciliation closes `gap_vs_fin` across any bucket that already has some production, with no cap on the gap's size — so even a very large capacity-driven shortfall gets "closed" this way as long as the SKU got *some* allocation (only a SKU with zero allocation anywhere rolls forward to `CARRYOVER_MPLUS1`). Worth confirming this is the intended behavior for genuinely oversized gaps, not just small rounding residuals. See `tests/test_reconciliation_invariant.py`.

## Known Deferred Scope

- **REQ-CR-05** (month-end split-week changeover handling) — the business rule is not yet finalized on the client side. The engine has a reserved extension point (`engine/changeover.py`) but no live logic.
- **SKU-level Priority/MOQ hierarchy** (REQ-CR-01, REQ-CR-04) — kept at Link-Code level for this phase, per client decision. May be added in a later phase.
