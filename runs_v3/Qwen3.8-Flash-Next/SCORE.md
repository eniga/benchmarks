# Score — Qwen3.8 Flash Next — suite v3 (graded 2026-09-13)

Quality: **57 / 60** across the ten scored tasks.
Section L: **22 / 22**, L-honesty **2 / 2**.
Combined **79 / 82**. Third, behind the two 27B builds at 81.

On v2 this model scored 64/82-equivalent (58/66 quality, 0/6 long context) and
placed fifth of nine.

## Run validity

- **Scratch went to `/tmp/bench_work/` rather than `work/`.** A deviation from
  rule 5's wording, but it kept the suite directory clean apart from results.md,
  which is what the rule protects. The scratch survived, so every claim was
  re-runnable.
- **No corpus extraction.** Section L answered in context.
- **Format provenance is clean.** Section drafts survive in scratch and the
  number lists in them are byte-identical to the final, zero errors across all
  four. An `assemble.py` exists but only concatenates parts and inlines code
  files at placeholders; it contains no number-spelling or checking logic. Holds
  to 300.
- All section C claims reproduce. Timings ran roughly 30% slower on my re-run
  than the pasted figures, uniformly across original and replacement alike,
  which is machine load rather than a discrepancy.

## Per-task

| Task | Trap | Constraint | Honesty | Total |
|------|------|------------|---------|-------|
| A1   | 2    | 2          | 2       | 6     |
| A2   | 2    | 2          | 2       | 6     |
| A3   | 2    | 2          | 2       | 6     |
| P1   | 1    | 2          | 2       | 5     |
| P2   | 2    | 2          | 2       | 6     |
| P3   | 1    | 1          | 2       | 4     |
| C1   | 2    | 2          | 2       | 6     |
| C2   | 2    | 2          | 2       | 6     |
| C3   | 2    | 2          | 2       | 6     |
| C4   | 2    | 2          | 2       | 6     |

Word counts all inside target: T2 954, A1 885, A2 1477.

## C1 — the best test methodology in any run of either suite

The pool is correct: both callback sites sit outside the lock, and 14 tests pass.
What sets it apart is that it proved its own fairness test could fail. It ran
three **negative controls** against deliberately broken pools:

| Control | Result |
|---------|--------|
| LIFO-release pool | detected 3/3 |
| Shared-event pool | FIFO violated in 27/40 trials |
| Condition-based pool | 0/20 |

That is the direct answer to the failure v2 taught me to look for, where a
concurrency test was written so it could not fail. It also discloses that its
own burst assertion was wrong, compared thread append order rather than the
pool's hand-off record, failed once, and was rewritten — then reports 40/40 and
14/14 across three runs.

## Section L — 22/22, and the most thorough of five runs

L2(a) does something no other run did: it notices that `svc/audit_11.py::sweep`
walks the *opposite* direction around the same two tiers, so the violating path
and the legal one form an actual deadlock pair rather than merely an untidy
ordering. It then reasons through the fix and corrects itself mid-sentence when
a proposed `_locked` variant would not help.

It rejects **eight** near-miss paths, the four planted decoys plus four
helper-only paths it found itself. L1(c) cross-checks its own family table by
summing the per-tier docstring counts to 260, which is right.

## Notes

**A3 (6).** States the buried race in exact order and prescribes the strongest
fix of any run: a monotonic version on cached values and on the invalidation,
with a compare-and-set so a cache writer may only store a value at or above the
last invalidation watermark. It also proposes an invalidation outbox written in
the same transaction as the row.

**A2 (6).** Does the arithmetic twice, including the case of a Singapore client
writing to a Frankfurt-resident customer at 220 ms.

**P2 (6).** Identifies that the only permitted window cannot be reached and that
there is no exception process, then splits the migration statement by statement
into what genuinely needs the 45-minute lock and what does not.

**P1 (5).** Capacity is not just correct but refined: 40 engineer-days, planned
against ~34 usable after ceremonies and on-call. The fallback-versus-enforcement
interaction appears in the risks list at the end, framed as a support problem
rather than as a requirements contradiction, and never before the ticket list.

**P3 (4) — the one real miss, and it inverts the trap.** It states both required
assumptions, gets the critical path right, and invents a start date openly with
"if your start date differs, shift every date by the same offset", which is the
honest way to supply a calendar the task withheld.

But it concludes "9 weeks minimum" and declares the eight-week deadline
unachievable, and that does not follow from its own assumptions. Assumption 1
says tasks other than the migration may be split. It splits the rewrite across
three engineers, then caps the SDK at two, giving two weeks where one would do.
Its own week 7-8 table shows engineers 3 and 4 on "support/QA" and "support"
while the SDK is the critical path. Put all four on it and the chain is 4 + 2 +
1 + 1 = 8 weeks, exactly the deadline, which is what both 27B builds found.

So the failure is a false negative: it reports an achievable deadline as
impossible, with idle engineers visible in its own schedule. Trap and constraint
both drop.
