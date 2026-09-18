# Known Limitations

Running list of known limitations, data-quality dependencies, and open questions
for the client. Each entry says what the limitation is, what the tool does today,
and (where relevant) what would remove it.

This file is additive — bugs that are fixed stay documented here only if a
residual limitation remains.

---

## L1 — RCCP was matched to the plan by product name text, not Link Code

**Resolved (REQ-CR-01 rebuild).** The old Manual Input **RCCP** sheet identified
each product only by a free-text `Link Code Desc`, joined to the plan by
normalizing and matching that text — ~19 SKUs across 5 lines had no match at
all (e.g. `Mignonettes`, `CDM 10 Rural`, `CDM Milkinis Large`/`Small`, `Silk
Bubbly Large Nepal`, `BVL 50%/70% Orange`, the EDGE range).

RCCP has been replaced entirely by **`Priority(Linkcode Level)`**, joined by
**(Link Code, Plant, Line)** — a numeric, exact join, not text matching. The
same Link Code can carry a different Priority/MOQ depending on which physical
line produces it (confirmed against the real client file), which is why the
join key is three fields, not one. Checked against the real client dataset:
**100% join coverage** — every (Link Code, Plant, Line) combination that
actually appears in the FIN sheet has a matching row, zero misses.

Priority is now read per-period (columns `1`–`14`, matching `Linkcode_DIFC` /
`2.Demand Input`'s own convention) instead of a single static value, so it can
differ month to month for the same Link Code/Line (the actual ask behind
REQ-CR-01). MOQ stays a single value — not extended to a month dimension
(client decision, since it was never formally in CR-01's scope).

**Bundled fix.** A separate bug found during this rebuild is now also fixed:
a Link Code with no match used to get a bare file-order counter that could
land *ahead of or tied with* a Link Code with a real, planner-assigned
priority. Unmatched Link Codes now always sort strictly after every matched
one in their (Plant/Line, Period) group, then by file order among themselves.

**SKU-level priority is out of scope — structurally, not by coincidence.**
`Priority(Linkcode Level)` has no SKU column at all. SKU-level priority
sequencing (the two-key language in the flow doc's "SKU Sequencing and
Prioritization" section, and CR-04's SKU-vs-Link-Code hierarchy) has no basis
in this or any other current input. This is a structural fact about the input
set, independent of whether SKU happens to equal Link Code in today's data —
that coincidence is not the reason SKU-level priority is out of scope, and
shouldn't be relied on as one.

---

## #8 — Target DOS source

**Resolved (`fix/target-dos-from-difc`).** Target DOS is read **solely** from
`Linkcode_DIFC.Avg_min_dos_target` (MPS Output), joined by numeric Link Code —
real per-product values (0–60 days in the sample), available even for SKUs with
no Priority(Linkcode Level) match. It is not taken from Manual Input at all. If a Link Code has
no value in that column, `target_dos = opening_dos` (so the DOS gap is 0). Every
run flags the source in the amber banner and the `Assumption Applied` tab.

**Assumption to confirm with the client:** that `Avg_min_dos_target` in
`Linkcode_DIFC` *is* the intended Target DOS. The name ("average minimum DOS
target") strongly implies it, and the sample value range fits.

---

## L2 — Behaviour when a SKU's MOQ is missing

**What it is.** MOQ ("Maximum Run-Length") comes from Priority(Linkcode Level).
A SKU can be missing it either because the whole Manual Input file was not
supplied, or because that one Link Code/Plant/Line had no match (L1), or
because its MOQ cell is blank.

**What the tool does today.** Per the Fallback Matrix (Development Planning
Document, Section 5): MOQ absent → run-length constraint not enforced → Run 1's
Case A/B/C/D branching is skipped for that SKU and **100% of its FIN is
distributed in Run 2**. This is applied per-SKU, not only when the whole file is
absent. Each affected SKU is flagged in `Assumption Applied`.

**Requested change (pending).** Planning preference is that a missing-MOQ SKU
should instead be split into **two approximately equal runs**, flagged as such.
This is deferred because it depends on the same unresolved definition as the
"more than two runs" issue (what a "run" physically constrains — see
REQ-CR-03 sub-item 3, L3 below). It would also require updating the Fallback
Matrix. To be revisited together with that item.

---

## L3 — REQ-CR-03: sub-item 3 (split into two runs) is implemented as a Run-1-half quantity split; "what a run is physically" and the min-vs-max wording remain open

**What it is.** BRD v2.0 / REQ-CR-03 (sub-items 3 & 5 only; sub-items 1–2 excluded
by client scope decision) redefines MOQ from a minimum batch size into a
**Maximum Run-Length**, with the input field relabeled accordingly:

> *"If FIN < 1.5 × MOQ — schedule as a single run. If FIN ≥ 1.5 × MOQ — split
> into two approximately equal runs. The DOS hard constraint always overrides
> the split."*

**What the tool does now (`feature/cr03-split-case-b`).** Sub-item 3 is
implemented for the one case it applies to:

- **Case B** (DOS gap = 0, no urgency) with `FIN ≥ 1.5 × MOQ` → Run 1's target
  is **`FIN / 2`** (was: one MOQ batch); Run 2's existing remainder pass
  produces the other ≈ half. In practice this is *every* Case-B Link Code that
  has a real MOQ, because Case A already claims everything with
  `FIN < 1.5 × MOQ`. The `CASE` column still reads `"B"`.
- **Case A** is already a single run — unchanged, and it *is* sub-item 3's
  "schedule as a single run" branch.
- **Cases C and D** are DOS-gap-driven, so **sub-item 5** ("DOS hard constraint
  always overrides the split") is honoured by leaving them untouched.
- **Missing-MOQ Link Codes** (see L2 above) are unchanged — still 100 % via
  Run 2, no split.

Measured on the full real dataset (10 periods, 942 rows): 258 rows (all Case B)
move from a one-MOQ-batch Run 1 to a `FIN/2` Run 1. Aggregate volume unchanged,
`gap_vs_fin` stays 0 — it is a **redistribution between Link Codes sharing a
line**: Run 1 is a full pass over every Link Code before Run 2 starts, so a
bigger Run 1 claim locks in more of the shared, priority-ordered capacity
during that pass.

**What is deliberately NOT changed — the residual limitation:**

1. **This is the *quantity-split* reading.** "Two runs" = Run 1 takes half,
   Run 2 the rest; both halves are still placed by the same greedy per-week
   fill, in the same two-pass structure. No distinct schedulable "run /
   campaign" object is introduced, and **no scheduling gap is reserved between
   the two runs** for other Link Codes on the line. If the client means a real
   sequencing change (the usual manufacturing reason to cap a run length), this
   needs redoing — the current change would be the quantity layer of it, not
   the whole thing.
2. **MOQ is still also a *minimum floor* elsewhere in the engine.** Run 2's
   `H1` rule still won't *start* a sub-MOQ run in an empty week, and Case C
   still produces "one full MOQ (floor)". The flow doc's Run 2 rule ("no
   production run may fall below `moq_hrs`", a **minimum**) and CR-03's
   "Maximum Run-Length" label still coexist unreconciled. It doesn't make this
   change ambiguous — the split only sizes Run 1's claim — but the field-label
   contradiction stands.

**Open questions still worth putting to the client (Amit/Vijay):**

1. Does REQ-CR-03's "Maximum Run-Length" fully replace the older "MOQ floor"
   language in the flow doc's Run 2 rules, or should both coexist?
2. Does "two approximately equal runs" mean the quantity split now shipped, or
   does it also require the schedule to leave a gap for other Link Codes
   between the two runs?

---

## L4 — SKU Master is the designated SKU↔Link Code mapping sheet, but it has no column literally named "SKU", and is not consumed anywhere today

**What it is.** The MPS Input workbook's `SKU Master` sheet is intended as the
SKU↔Link Code mapping (per its own column header comment in
`engine/parsers/mps_input_parser.py`), but `engine/consolidation.py` currently
pulls SKU and Link Code straight off the FIN sheet (MPS Output's
`SKU Line Loading 1`) instead, which already carries both columns per row.
`SKU Master` is parsed and confirmed non-empty, then never read again.

**The sheet itself has a gap.** `SKU Master`'s actual columns are `Brand`,
`Link Code`, `Link Desc Description`, `List Code`, `List Description` — there
is no column literally named `SKU`. `List Code` is the closest analog (and
equals `Link Code` in every sample row, consistent with SKU == Link Code 1:1
today), but this has not been confirmed with the client as the intended SKU
identifier.

**Impact today.** None — SKU and Link Code are identical for all 991 client
rows, so sourcing the mapping from the FIN sheet instead of `SKU Master`
produces the same result either way.

**Why it matters going forward.** This stops being a non-issue the moment
either (a) the parked FIN-source switch to `Link Code Line Loading 1` happens
— that sheet has no SKU column at all, making `SKU Master` the *only* place a
genuine SKU↔Link Code mapping could come from — or (b) CR-04's SKU-vs-Link-Code
granularity question is ever resolved in favor of real SKU-level planning.
Code now carries an explicit note (in `mps_input_parser.py`'s module docstring
and a comment at `consolidation.py`'s FIN-sheet melt) pointing future work at
`SKU Master`, not the FIN sheet, for this mapping — but the missing `SKU`
column still needs a client answer before anything can actually be wired to
depend on it.

**Open question for the client.** Does `List Code` in `SKU Master` represent
the SKU, or is a dedicated `SKU` column needed?
