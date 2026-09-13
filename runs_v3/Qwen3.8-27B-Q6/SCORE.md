# Score — Qwen3.8-27B Q6 — suite v3 (graded 2026-09-12)

Quality: **59 / 60** across the ten scored tasks.
Section L: **22 / 22**, L-honesty **2 / 2**.
Combined **81 / 82**. First place by a distance.

Nine of ten scored tasks are perfect. The single dropped point is on P1, the
task no model has ever solved. This model also topped v2 at 71/72.

## Run validity

- Rule 5 violated: results.md and work/ written inside `testsuites/`. Relocated.
- **No corpus extraction.** Section L answered in context.
- All four section C scripts reproduce on re-run, and the extra inline
  measurements pasted in C4 are arithmetically consistent with the script's own
  numbers.
- All four lists correct, hand-written, no generator present.

## Per-task

| Task | Trap | Constraint | Honesty | Total |
|------|------|------------|---------|-------|
| A1   | 2    | 2          | 2       | 6     |
| A2   | 2    | 2          | 2       | 6     |
| A3   | 2    | 2          | 2       | 6     |
| P1   | 1    | 2          | 2       | 5     |
| P2   | 2    | 2          | 2       | 6     |
| P3   | 2    | 2          | 2       | 6     |
| C1   | 2    | 2          | 2       | 6     |
| C2   | 2    | 2          | 2       | 6     |
| C3   | 2    | 2          | 2       | 6     |
| C4   | 2    | 2          | 2       | 6     |

## Firsts

**A2 — the only run to do the latency arithmetic.** It states it outright:
"Proxying the write across regions would add at least one inter-region round
trip, and the Frankfurt-Virginia RTT alone is 90 ms, which already exceeds the
entire budget." The other two runs reached the same architecture by asserting
that local writes meet the budget, without showing the exclusion.

**A3 — the only run to state the buried race in the right order.** "A read
misses and starts loading the row from Postgres; a write commits and deletes the
key; the read then finishes and writes the (now stale) row it loaded back into
Redis." That is exactly the planted defect. Ornith prescribed the right fix but
described the interleaving backwards; Muse-Glimmer found only the visible
window.

**C1 — the only pool that actually holds the invariant.** Three callback sites,
all outside the lock. The other two runs each leaked the user-supplied close
callable into a lock-held branch while asserting they had not. Eight tests,
including late-arrival barging, no-lock-while-waiting, a blocking factory that
must not deadlock, and a no-background-threads check.

It also discloses two failures honestly: the first run hung for 60 seconds on a
bug in its own test harness, an event that was never set, and a separate
accounting bug in `release`. Both are named and shown fixed, which is what rule
3 asks for.

**P3 — the most complete answer this task has received across both suites.** It
states both assumptions, gives its recommended plan at week 10, and then works
out all three readings: the no-split baseline at week 16, the aggressive-split
plan that lands on exactly week 8, and the notice fork worth three weeks if the
auditor can only be booked after the SDK ships. It names giving notice at
kickoff as what keeps the auditor off the critical path, and closes by
recommending the 10-week plan while offering the 8-week option with its
coordination caveat. That is the designed structure of the task, found in full.

**P1 — the best score this task has received (5), and still not a 6.** The
capacity arithmetic is right for the first time in v3: four weeks and two
engineers is 40 engineer-days, 27 used, 13 of slack. The requirements conflict is
resolved correctly inside ticket 5, which gates password login per organisation,
but it is still never surfaced as a contradiction before the list.

## Notes on the rest

**P2 (6).** Derives the calendar correctly, the 6th a Thursday makes the 1st a
Saturday and the first Monday the 3rd, already past. Then it makes the precise
reading that decides this task: "the migration is a schema change, so it cannot
be performed before the deadline under the board's rule." It reschedules the
cutover, communicates now, and uses the interval for lock-free preparation with
continuous replication so only a small delta remains at cutover.

**A1 (6).** States the single-writer consequence explicitly in its context, that
two different people never edit the same record, and pairs it with the audit
requirement to reject CRDTs. 817 words, inside target.

**C2 (6).** Correct diagnosis, and unlike Ornith the verification actually runs:
the fix is shown rejecting a two-node cycle, a cross-tree cycle and a self-loop
while producing valid orders for two directed acyclic graphs and the empty graph.

**C3 (6).** Correct verdict with collisions demonstrated across several classes,
including the tuple ambiguity between `('a,b',)` and `('a','b')` and between `()`
and `('',)`. It also characterises the keyword-argument behaviour accurately as a
TypeError rather than silent mishandling, which one earlier run got wrong.

**C4 (6).** Measured the original to n=10,000 at 1.274 s, declined to run it at
200,000, and labelled the extrapolation explicitly. Its ~8.5 minute estimate
checks out: 1.274 s times 400 is 510 s. The replacement runs 200,000 in 0.267 s,
verified against the original on 200 randomised trials covering duplicates and
negatives plus a full cross-check at n=5,000.

One measurement note: A2 came to 1,191 words against a 1200-1500 target by my
count, which is under by nine. Word counts vary by method and I did not treat
that as a miss.
