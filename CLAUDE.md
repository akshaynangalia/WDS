# CLAUDE.md

This file gives Claude (or any AI coding agent working on this repo) the operating context needed to develop this project correctly. It **summarizes** the governing documents — it never overrides them. If anything here ever conflicts with the Architecture Document, Spec Document, or Development Planning Document, those win. Update this file to match them, never the other way around.

## Project, in one paragraph

This is a Python + Dash tool for Mondelez that converts a Monthly Production Plan (Line–SKU–Month) into a Weekly Production Plan (Line–SKU–Week), replacing an existing Excel/VBA process. Planners upload three input workbooks (MPS Input, MPS Output, Manual Input), configure a planning horizon and a few parameters, run the disaggregation, and download the result as Excel.

## Authoritative Documents (read in this order before writing any code)

1. **Architecture Document v1.0** — system layers, components, data flow
2. **Spec Document v1.0** — pinned tool/library versions
3. **Development Planning Document v1.1** — the actual execution playbook. Section 2 has the full file tree, per-file contracts, and the exact call sequence a run takes through the codebase. Section 4 has the phase-by-phase plan. **This is the document to work from.**

## Current Status

**Phase 0 through Phase 8 have an initial implementation drafted and passing 34 automated tests** (parsers, consolidation, capacity, allocation, reconciliation, carryover, DOS/DIFC, output, run manager end-to-end, layering, and the Dash layout-ID audit). This was built in a single compressed pass rather than strictly one phase at a time — Rule 1 still applies going forward from here. **Not yet done:** Phase 9 (full local UAT against a real, date-aligned dataset), Phase 10 (GitHub), Phase 11 (Posit Connect). Two open items were discovered during this pass and need client confirmation before Phase 9 can be considered complete:
1. RCCP identifies products by text description, not the numeric Link Code used elsewhere — the join in `engine/consolidation.py` is a best-effort text match.
2. Reconciliation closes a gap via active-bucket adjustment regardless of magnitude (per a literal reading of the ground-truth doc) — see the note in `tests/test_reconciliation_invariant.py::test_large_shortfall_still_closes_via_active_bucket_adjustment`.

> Update this section at every phase boundary from here on.

## Non-Negotiable Rules

(Full text: Development Planning Document, Section 1)

- Work through phases **strictly in order** (Dev Plan Section 4). Do not start Phase N+1 before Phase N's exit criteria — including its tests — are met.
- Define a module's interface (inputs/outputs) before writing its implementation. Check it against Dev Plan Section 2.2's contracts.
- Build and fully test `engine/` headless — no Dash/UI imports — before touching `app/`.
- A module is "done" when its output **matches the worked-example numbers** in the ground-truth logic doc (Induri ML, February), not when it merely runs without errors.
- `engine/` and `output/` must never import from `app/` or `orchestration/`. One direction only: `app` → `orchestration` → `engine`/`output`. `tests/test_layering.py` checks this.
- **Local host first, always.** Do not touch GitHub or Posit Connect until Phase 9 (local testing) is genuinely complete. No exceptions for convenience or "just to check."
- If something doesn't fit the plan — an ambiguous rule, a missing case — raise it and log it (Dev Plan Section 8, Risk Register). Don't quietly improvise a fix.

## File Map

Full directory tree, per-file responsibility, and the exact call sequence a run takes through the codebase are in the **Development Planning Document, Section 2**. Do not create files outside that structure without updating that document first.

Quick orientation:
```
app/            Dash UI — the only layer allowed to trigger a run
orchestration/  Run Manager + Run History — the seam between UI and engine
engine/         All business logic — parsers, consolidation, capacity, allocation, DOS/DIFC
output/         Excel workbook generation
tests/          One test file per engine/output module, plus layering + UI-ID audits
```

## Business Rules — Quick Reference

**Two-Run allocation heuristic (per SKU, in priority order):**

| Case | Condition | Run 1 produces |
|---|---|---|
| A | Monthly FIN < 1.5 × MOQ | Entire FIN in one run — skip Run 2 |
| B | DOS gap = 0 | One MOQ batch |
| C | DOS gap exists, < MOQ | One full MOQ (floor) |
| D | DOS gap exists, ≥ MOQ | Exactly the DOS gap |

Run 2 distributes whatever FIN remains against remaining weekly capacity, never below the MOQ floor per run.

**DOS Gap:** `Target DOS − Opening DOS` (positive = below safety threshold)

**Weekly capacity:** `24 × 7 − downtime_hours`, with W1 split into W1A (prior-month carryover days) and W1 (current-month days); W5 exists only when `month MOD 3 = 0`. GE% is applied as a separate multiplier — not pre-baked into the Throughput input.

**Weekly Closing DIFC:** `MAX((Opening_DIFC × Daily_Demand − Weekly_Demand + Production_W) / Daily_Demand, 0)`

**Reconciliation invariant (zero tolerance):** sum of all weekly buckets (W1A + W1..W5) must equal monthly FIN, always. Any residual gets distributed across active weeks, or rolled to `CARRYOVER_MPLUS1` if the SKU got no allocation at all.

## What NOT To Do

- Don't deploy anything to Posit Connect before Phase 11.
- Don't push to the GitHub remote before Phase 10 (local commits are fine and encouraged throughout).
- Don't guess at REQ-CR-05 (split-week changeover) logic — `engine/changeover.py` stays a documented no-op until the client provides the resolved rule. See Dev Plan Risk Register item 1.
- Don't add SKU-level Priority/MOQ handling — RCCP stays Link-Code level per client decision (Risk Register item 2).
- Don't reproduce the "ID not found in layout" Dash pattern seen in the reference prototype screenshots — `tests/test_ui_layout_ids.py` exists specifically to catch this (Risk Register item 5).
- Don't invent fallback behavior beyond Dev Plan Section 5's Fallback Matrix — if a genuinely new missing-input scenario comes up, flag it in the Risk Register rather than guessing a default.
