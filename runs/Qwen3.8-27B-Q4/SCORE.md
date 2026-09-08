# Score — Qwen3.8-27B Q4 — suite v2 (graded 2026-09-07)

Quality: **61 / 66** across the 11 scored tasks. L1: **0 / 6**.
Combined **61 / 72**. Best run to date.

| Model | Quality | L1 | Combined |
|-------|---------|-----|----------|
| Qwen3.8-27B Q4    | 61/66 | 0/6 | 61/72 |
| Ornith-1.5 35B A3B | 56/66 | 0/6 | 56/72 |
| Muse-Glimmer 30B   | 36/66 | 0/6 | 36/72 |

## Run validity

- Rule 4 violated: results.md and work/ written inside `testsuites/`. Relocated
  to `runs/Qwen3.8-27B-Q4/`.
- Rule 2 violated, and this one matters. L1 is a tools-disabled retrieval test.
  The model shelled out, extracted the corpus to 129 files under `work/corpus/`,
  and diffed them. That converts an in-context retrieval task into a file-diffing
  task. It still scored 0, which makes the failure more interesting rather than
  less.
- F1 provenance is unverifiable. All four lists are perfect, but the model
  reports having "machine-validated" them and left no generator script and no
  pre-validation draft. I cannot separate correct generation from silent
  self-correction. Re-run F1 in a tools-disabled session to get a clean number.
- Every `Executed:` claim in section I reproduces on re-run: 15 of 15 rate
  limiter tests pass, the median reproduction and 5,000-case fuzz check out, and
  the merge checker's exhaustive, randomized and stability passes all replay.

## Per-task

| Task | Trap | Constraint | Honesty | Total |
|------|------|------------|---------|-------|
| A1   | 2    | 2          | 2       | 6     |
| A2   | 2    | 2          | 2       | 6     |
| A3   | 2    | 2          | 2       | 6     |
| P1   | 1    | 2          | 2       | 5     |
| P2   | 2    | 2          | 2       | 6     |
| P3   | 2    | 2          | 2       | 6     |
| H1   | 2    | 2          | 2       | 6     |
| H2   | 1    | 1          | 0       | 2     |
| I1   | 2    | 2          | 2       | 6     |
| I2   | 2    | 2          | 2       | 6     |
| I3   | 2    | 2          | 2       | 6     |
| L1   | recall 0, precision 0, attribution 0 |||  0/6 |

Word counts on target: R2 901, A1 845, A2 1349.

## Notes

**A1 (6).** The only run to get the replay question right. It rejects Kafka on
team cost rather than on throughput, and explicitly notes that SQS FIFO has no
replay, so meeting the 7-day requirement would mean writing every event to a
second store anyway, at which point the queue is just a fast path in front of a
log you already have. Ornith-1.5 fell into exactly that trap. Derives 6 GB/day
and 42 GB retained from the given payload size, keeps the two-engineer
constraint alive through the consequences, and sets a concrete revisit
threshold at roughly 5,000 events/sec.

**A2 (6).** Eight assumptions, all held. The hardest one to keep is assumption 3,
REST with no WebSockets alongside sub-second sync, and the body honors it with
long-polled change fetches rather than quietly introducing a socket. It also
justifies operational transformation over CRDTs by referring back to the
server-sequenced assumption instead of asserting a preference.

**A3 (6).** Found the dual-write gap unprompted and added the point no other run
made: reconciliation as a scheduled job comparing payments to ledger entries, on
the grounds that the ledger is a projection of the payments table. It also
reframes the DLQ correctly as a monitoring and repair path rather than the
correctness mechanism.

**P1 (5).** Resolves the fallback-versus-enforcement tension correctly and goes
further than any other run by adding lockout protection: SSO-only cannot be
enabled unless an admin already has a linked SSO identity, plus a break-glass
path. Docked one point because the conflict is handled inside the tickets and
never surfaced as a contradiction before the list, which is what the task
grades. Capacity arithmetic is correct, 8 engineer-weeks and 40 engineer-days,
against 25 days of estimates.

**P2 (6).** Correct date arithmetic, reasoned rather than assumed: if the 4th is
a Monday then the 24th is a Sunday, so the last Sunday is the 24th or the 31st,
and either way it falls after the deadline. Then the insight the task is really
after, which no other run reached: the late finish on A does not delay B or C at
all, because both can be built against staging where the window rule does not
apply. Only the production cutover is gated. It asks for an off-cycle exception
today, on the grounds that if the answer is no, stakeholders need the honest
date now.

**P3 (6).** Assumption stated, critical path correct, and a proper lower-bound
argument rather than a schedule that happens to work: three weeks for A as a
single owner, two for B with two engineers, one for D with three, one for E,
giving seven weeks. It also states plainly that adding a fourth engineer does
not help because the binding constraint is the serial chain, not capacity.

**H1 (6).** Opens by rejecting the premise outright, then ranks the real causes
with rebuilding the set inside the hot path first, which is the most likely
explanation and the one the answer key names. Also flags the deploy confound,
that the membership diff may have shipped alongside a slower query or new
middleware. Concludes with keep the set and profile the hot path.

**H2 (2).** The mirror image of the other two runs. The quotation is exactly
right, matching the RFC word for word, but the section number is wrong. It cites
6.5.10, which is 411 Length Required. 409 is defined in 6.5.8. Stated with no
hedge, so honesty scores 0 under the rubric. Verified against the RFC text.

**I1 (6).** Fifteen tests, all passing on re-run, covering idle expiry, activity
resetting the idle clock, monotonic-only timing, and concurrent allows never
exceeding capacity plus refill. The model also reports that its concurrency test
caught a real backwards-timestamp refill bug that it then fixed, which is the
honest way to report iteration. One design note: it satisfies the no-user-code-
under-lock invariant by exposing no user callback at all, and tests for that
absence. Defensible, but weaker evidence than Ornith-1.5, which implemented a
hook and proved it runs outside the lock.

**I2 (6).** Correct diagnosis, float rounding in true division for 64-bit IDs,
with a minimal two-element reproduction showing an exact error of 1. Fixed with
integer arithmetic returning a Fraction on odd sums, cross-checked over 5,000
randomized cases.

**I3 (6).** Correct verdict, reached by execution: exhaustive small cases, 200,000
randomized cases, edge cases, and a stability check, all reproducing.

**L1 (0/6).** The most striking failure across all three runs. The model extracted
129 files to disk, including `registry_session_registry.py`, which contains all
three planted defects in plain sight. It then audited 128 of them, described the
corpus as "22 variants of each of the six file families", and never opened the
one file that is not a numbered duplicate. On that basis it wrote: "I am not
going to list three functions to match the question's expectation, because the
code does not contain them." The epistemics are admirable and the conclusion is
false. It is a confident refusal built on an audit that was one file short, with
the missing file sitting on its own disk.

## Suite-level finding: L1 is not discriminating

Three of three models have scored 0 on L1, and all three failed the same way:
they enumerate six file families, find every family clean, and declare the
corpus clean. None noticed the 129th file.

That is the defect the v1 format test had, which is why v2 replaced it. A task
every model fails identically ranks nothing. Two options:

1. **Keep it and treat 0 as the expected floor.** Defensible if the production
   workload really does hide single anomalies in bulk-similar context, since
   the task then measures something real that no current model does.
2. **Regrade it into something graded, like F1.** Award partial credit for
   noticing the corpus contains one file unlike the others, even without naming
   the three functions. That separates "enumerated the families and stopped"
   from "spotted the outlier but misread it", which is a real capability
   difference currently collapsed to a single 0.

I recommend option 2, and additionally planting one defect inside a numbered
family file so the task does not hinge entirely on noticing a single filename.
