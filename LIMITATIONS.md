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
`engine/consolidation.py` joins the two by normalising and matching that text.

**Impact.** When a product's description in the plan does not exactly match any
`Link Code Desc` in RCCP, that SKU gets **no Priority, no MOQ, and no Target DOS**.
In the client sample data this affects ~15 SKUs across 5 lines — for example
`Mignonettes`, `CDM 10 Rural`, `CDM Milkinis Large` / `Small`,
`Silk Bubbly Large Nepal`, `BVL 50% Orange`, `BVL 70% Orange`, and the EDGE range.

**What the tool does today.** Every unmatched SKU is flagged on the amber banner
and in the `ASSUMPTIONS_APPLIED` tab, and is planned using fallback defaults:
priority by file order, DOS gap treated as 0, and **no run-length (MOQ)
constraint — its full volume is distributed in Run 2** (see L2). Before the
`fix/missing-moq-nan` fix, an unmatched SKU with a zero DOS gap was instead
dropped from the plan entirely (blank row); that is now resolved.

**Open question for the client.** *Can the RCCP sheet include the numeric Link
Code column* (alongside or instead of the text description)? That would make the
join exact and remove this entire class of issue.

---

## L2 — Behaviour when a SKU's MOQ is missing

**What it is.** MOQ ("Maximum Run-Length") comes from RCCP. A SKU can be missing
it either because the whole Manual Input file was not supplied, or because that
one SKU had no RCCP match (L1), or because its MOQ cell is blank.

**What the tool does today.** Per the Fallback Matrix (Development Planning
Document, Section 5): MOQ absent → run-length constraint not enforced → Run 1's
Case A/B/C/D branching is skipped for that SKU and **100% of its FIN is
distributed in Run 2**. This is applied per-SKU, not only when the whole file is
absent. Each affected SKU is flagged in `ASSUMPTIONS_APPLIED`.

**Requested change (pending).** Planning preference is that a missing-MOQ SKU
should instead be split into **two approximately equal runs**, flagged as such.
This is deferred because it depends on the same unresolved definition as the
"more than two runs" issue (what a "run" physically constrains — see
REQ-CR-03 sub-item 3). It would also require updating the Fallback Matrix. To be
revisited together with that item.
