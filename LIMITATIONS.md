# Known Limitations

Running list of known limitations, data-quality dependencies, and open questions
for the client. Each entry says what the limitation is, what the tool does today,
and (where relevant) what would remove it.

This file is additive — bugs that are fixed stay documented here only if a
residual limitation remains.

---

## L1 — RCCP is matched to the plan by product name text, not Link Code

**What it is.** The Manual Input **RCCP** sheet identifies each product only by a
free-text `Link Code Desc` (e.g. `CDM 20`, `Silk Bubbly Large SEA`). The MPS
Input / MPS Output files identify the same product by a numeric **Link Code**.
`engine/consolidation.py` joins **Priority and MOQ** by normalising and matching
that text. (Target DOS is no longer on this join — see #8.)

**Impact.** When a product's description in the plan does not exactly match any
`Link Code Desc` in RCCP, that SKU gets **no Priority and no MOQ**. In the client
sample data this affects ~19 SKUs across 5 lines — for example `Mignonettes`,
`CDM 10 Rural`, `CDM Milkinis Large` / `Small`, `Silk Bubbly Large Nepal`,
`BVL 50% Orange`, `BVL 70% Orange`, and the EDGE range.

**What the tool does today.** Every unmatched SKU is flagged on the amber banner
and in the `Assumption Applied` tab, and is planned using fallback defaults:
priority by file order, and **no run-length (MOQ) constraint — its full volume is
distributed in Run 2** (see L2). Target DOS still resolves via `Linkcode_DIFC`
(#8), so an unmatched SKU can still have a real DOS gap. Before the
`fix/missing-moq-nan` fix, an unmatched SKU with a zero DOS gap was instead
dropped from the plan entirely (blank row); that is now resolved.

**Open question for the client.** *Can the RCCP sheet include the numeric Link
Code column* (alongside or instead of the text description)? That would make the
Priority / MOQ join exact and remove this entire class of issue.

---

## #8 — Target DOS source

**Resolved (`fix/target-dos-from-difc`).** Target DOS is read **solely** from
`Linkcode_DIFC.Avg_min_dos_target` (MPS Output), joined by numeric Link Code —
real per-product values (0–60 days in the sample), available even for SKUs with
no RCCP text match. It is not taken from Manual Input at all. If a Link Code has
no value in that column, `target_dos = opening_dos` (so the DOS gap is 0). Every
run flags the source in the amber banner and the `Assumption Applied` tab.

**Assumption to confirm with the client:** that `Avg_min_dos_target` in
`Linkcode_DIFC` *is* the intended Target DOS. The name ("average minimum DOS
target") strongly implies it, and the sample value range fits.

---

## L2 — Behaviour when a SKU's MOQ is missing

**What it is.** MOQ ("Maximum Run-Length") comes from RCCP. A SKU can be missing
it either because the whole Manual Input file was not supplied, or because that
one SKU had no RCCP match (L1), or because its MOQ cell is blank.

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

## L3 — REQ-CR-03 (MOQ as Maximum Run-Length) is not implemented; MOQ is currently a *minimum* floor, and the ground-truth doc contradicts itself on which it should be

**What it is.** BRD v2.0 / REQ-CR-03 (sub-items 3 & 5 only; sub-items 1–2 excluded
by client scope decision) redefines MOQ from a minimum batch size into a
**Maximum Run-Length**, with the input field relabeled accordingly:

> *"If FIN < 1.5 × MOQ — schedule as a single run. If FIN ≥ 1.5 × MOQ — split
> into two approximately equal runs. The DOS hard constraint always overrides
> the split."*

**The ground-truth flow doc contradicts this in its own Run 2 rules**, which still
say *"No production run may fall below moq_hrs (the MOQ floor in hours)"* — i.e.
MOQ as a **minimum**, the opposite of REQ-CR-03. `engine/allocation.py` currently
implements the *minimum-floor* reading (Case B/C produce "one MOQ batch"; Run 2's
`H1` rule never starts a run below the MOQ floor) — i.e. today's code matches the
older, pre-CR-03 language, not REQ-CR-03 itself.

**Two things need resolving before this can be built, not just one:**

1. **What does "a run" mean physically?** MOQ's own unit is *days* (confirmed
   from the legacy VBA: `moq_hrs = MOQ_value * 24`, and from the RCCP sample
   values themselves — 1, 1.5, 2, 3, 3.5 — which read as day-counts, not
   tonnage). A "run" is most plausibly a continuous production campaign/batch
   (standard manufacturing usage — the reason to cap a "run-length" at all is to
   stop one SKU monopolizing a line indefinitely), not a calendar week. Note this
   is a *different* use of the word "run" than the engine's own "Two-Run"
   terminology (Run 1 / Run 2 = the two allocation *passes* — already settled,
   unrelated question).
2. **Does "split into two approximately equal runs" mean only a quantity split**
   (each run's *size* halved, still placed by today's greedy per-week fill, same
   Run-1-then-Run-2 pass structure), **or does it also require leaving scheduling
   room between the two runs** for other SKUs' production on the same line
   (the actual manufacturing reason a run-length cap exists)? The second reading
   is a real scheduling/sequencing change, not a quantity tweak.

**This is not a cosmetic choice — tested it empirically.** Implementing only the
narrowest reading (quantity split — Case B's Run 1 target becomes `FIN / 2`
instead of one MOQ batch, when `FIN ≥ 1.5 × MOQ`; Cases C/D unchanged per the DOS
override) against the full real dataset (periods 1–6) changed:

- **135 of 568 rows** (24%) — individual SKU-period swings up to **+140.9 T** and
  **−126.3 T** on a single row.
- Aggregate total produced barely moved (+94.5 T net, ~0.17% of total FIN) —
  confirming this is almost entirely a **redistribution between SKUs sharing a
  line**, not a change in total capacity used. `gap_vs_fin` stayed 0 throughout
  (no volume lost).

The mechanism: Run 1 completes for *every* SKU on a line (in priority order)
before Run 2 starts for *any* SKU (matches the legacy VBA's own two-loop
structure exactly, confirmed line-by-line). Growing a Case-B SKU's Run 1 claim
from a small MOQ batch to up to half its FIN lets it lock in materially more of
the shared, priority-ordered capacity *during the Run 1 pass* — at the direct
expense of other SKUs on the same line, purely as a side effect of which pass
gets the bigger claim. A client reviewing this needs to see that trade-off, not
just the requirement text.

**Open questions for the client (Amit/Vijay):**

1. Is REQ-CR-03 (v2.0, "Maximum Run-Length") meant to fully replace the older
   "MOQ floor" language still present in the flow doc's Run 2 rules (v1),
   or should both coexist somehow?
2. Does "two approximately equal runs" mean a quantity split only, or does it
   require the schedule to leave a gap for other SKUs between the two runs?
3. Does the DOS-override in sub-item 5 apply only when a SKU has a real DOS gap
   (Cases C/D), leaving Case B as the only case the split rule actually changes —
   or was something broader intended?

Nothing has been built against a guessed answer to any of these — `moq_case`
"B"/"C"/"D" and the MOQ-as-floor behavior in `allocation.py`/Run 2's `H1` rule
are unchanged pending a client answer.
