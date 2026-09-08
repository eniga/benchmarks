# Score — Qwen3.8-27B Q6 — suite v2 (graded 2026-09-07)

Quality: **65 / 66** across the 11 scored tasks. L1: **6 / 6**.
Combined **71 / 72**. Best run by a wide margin, and the first clean H2.

## Run validity

- Rule 4 violated again: results.md and work/ written inside `testsuites/`.
  Relocated to `runs/Qwen3.8-27B-Q6/`.
- Rule 2 partially violated, and self-reported. The submission says the lists
  were "machine-verified against an independent spelling reference" and that R2
  is "exactly 900 words (verified by word count)". Both are tool use outside
  section I. No artifacts for either survive on disk, so F1 provenance is again
  unverifiable, though verification is a lighter violation than generation.
- **L1 appears to have been solved in context.** Unlike Q5, this run left no
  `work/corpus/` directory: the only scratch files are the four section I
  scripts. That makes it the cleanest L1 result so far. One claim I cannot
  verify: it reports "counting every lock acquisition and mutation line across
  all 128 copies against the expected per-copy counts". If that counting was
  done with inline shell commands, it is another rule 2 violation; if by
  reasoning alone, it is a strong claim with no artifact behind it. The three
  findings are correct either way.
- Every section I claim reproduces on re-run: 11 of 11 rate limiter tests pass,
  the median reproduction and 20,000-case fuzz replay, and the merge verifier's
  12 edge cases and 200,000 random trials pass.

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
| H2   | 2    | 2          | 2       | 6     |
| I1   | 2    | 2          | 2       | 6     |
| I2   | 2    | 2          | 2       | 6     |
| I3   | 2    | 2          | 2       | 6     |
| L1   | recall 3, precision 3, attribution 3 |||  6/6 |

Word counts on target: R2 900 exactly, A1 695, A2 1277. All four lists correct.

## Notes

**H2 (6) — the first correct answer to this task.** Section 6.5.8 and a
quotation that matches the RFC word for word. Both other Qwen builds gave the
correct sentence under section 6.5.10, which is 411 Length Required, so the
family-artifact reading I offered on the Q5 report does not survive contact
with Q6. The quantization level is the only variable that changed, and it moved
this answer from wrong to right.

**L1 (6/6).** Three findings, correct file, correct mutating line quoted for
each, correct lock named for each, no false positives. Catches both subtleties:
that the error counter is incremented one line before its lock is taken, and
that the revoke function leaves a second unlocked mutation behind it.

**A1 (6).** Identifies the replay gap in the FIFO option in the same terms Q4
and Q5 used, that the queue deletes messages once processed so the requirement
is not expressible. Rejects Kafka on operations rather than throughput, keeps
the two-engineer constraint alive, and sets a concrete revisit threshold at
roughly 1 to 2 thousand events per second.

**A2 (6).** Ten assumptions, all held, including the one most runs drift on:
assumption 3 sets an explicit attachment size, and the storage section honors
it rather than quietly changing scope.

**A3 (6).** Found the dual write unprompted, plus the point the answer key
lists as a bonus signal and no other run made cleanly: the proposal's "SNS DLQ"
is a category error, since a dead-letter queue belongs to an SQS subscription
rather than to the topic itself.

**P1 (5).** The one imperfect answer, and it fails the same way every run has.
The fallback-versus-enforcement tension is resolved correctly inside ticket T5
but never surfaced as a contradiction before the list, which is what the task
grades. Everything else is right: capacity is correctly stated as 40 person-days
against 22 estimated, and it designs last-admin lockout protection in rather
than bolting it on.

**P2 (6).** Correct date arithmetic, escalation as the first move with a
deadline that still holds if an exception is granted, and the observation that
the migration is already applied in staging so both engineers can proceed on
the API layer now. Only the production cutover is gated.

**P3 (6).** Lands on eight weeks where the key expects seven, and earns full
marks anyway, because the task asks the model to state its assumptions and this
one does so explicitly: the vendor lead is counted from when the review can be
requested, which requires the dependency complete. The delivery date follows
from that assumption. It then closes the hole Q5 left open by proving the
deadline fails under the other reading too, since the review could only land in
week 6 if the dependency finished by week 5, which the four-engineer-week task
before it makes impossible. That argument is why this scores 6 and Q5's
similar answer scored 5.

**I1 (6).** Eleven tests, all passing on re-run, including key expiry at ten
minutes, a recently-used key surviving eviction, backward clock jumps, absence
of background threads, and an exact-capacity concurrency test. The invariant has
a dedicated test, `test_clock_never_called_under_lock`, which checks the
property directly rather than satisfying it by having no user code at all.

**I2 (6).** Correct diagnosis with the cleanest minimal demonstration of any
run, showing that converting 2^53 + 1 to a float silently drops the increment.
Fixed with sentinels replaced by None and exact integer arithmetic, verified at
0 mismatches over 20,000 cases.

**I3 (6).** Correct verdict from real execution, and like Q5 it pasted its first
failing run verbatim, including two bugs in its own test code, rather than
quietly presenting only the clean rerun.
