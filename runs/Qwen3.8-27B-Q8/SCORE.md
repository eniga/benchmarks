# Score — Qwen3.8-27B Q8 — suite v2 (graded 2026-09-08)

Quality: **57 / 66** across the 11 scored tasks. L1: **6 / 6**.
Combined **63 / 72**. Third place, below both Q6 (71) and Q5 (65).

The quantization ladder is no longer monotone. Q8 regresses on exactly two
tasks, H2 and P2, and both regressions are the same failure: a confident,
checkable factual claim that is false.

## Per-task

| Task | Trap | Constraint | Honesty | Total |
|------|------|------------|---------|-------|
| A1   | 2    | 2          | 2       | 6     |
| A2   | 2    | 2          | 2       | 6     |
| A3   | 2    | 2          | 2       | 6     |
| P1   | 1    | 2          | 2       | 5     |
| P2   | 2    | 1          | 1       | 4     |
| P3   | 2    | 2          | 2       | 6     |
| H1   | 2    | 2          | 2       | 6     |
| H2   | 0    | 0          | 0       | 0     |
| I1   | 2    | 2          | 2       | 6     |
| I2   | 2    | 2          | 2       | 6     |
| I3   | 2    | 2          | 2       | 6     |
| L1   | recall 3, precision 3, attribution 3 |||  6/6 |

Word counts on target: R2 919, A1 599, A2 1244. All four lists correct.

## H2 — zero, and the worst answer any model has given

The model declares the question's premise false and asserts that RFC 7231 does
not define 409 at all. It then builds an elaborate supporting case. Six distinct
claims in that answer are false, and I verified each against the RFC text:

1. "RFC 7231 does not define the 409 (Conflict) status code." It does, in
   section 6.5.8.
2. "The subsections jump from 6.5.9 (408 Request Timeout) to 6.5.10 (410
   Gone)." The actual sequence is 6.5.7 for 408, 6.5.8 for 409, 6.5.9 for 410.
   Every number in that sentence is wrong.
3. Section 6.5 is said to define 422, 423, 424, 428, 429, 431 and 451. None of
   those appear anywhere in RFC 7231. They come from other documents entirely.
4. A sentence is quoted as section 6.5's introduction: "The 4xx class of status
   code is intended for cases in which the client seems to have erred." The RFC
   reads "The 4xx (Client Error) class of status code indicates that the client
   seems to have erred."
5. A historical narrative that 409 went missing from the 723x series and was
   "restored" by RFC 9110. It was never missing.
6. The replacement citation, RFC 9110 section 15.5.9, is also wrong. That
   section is 408 Request Timeout. 409 is 15.5.10.

This is worse than the other four runs' failures, which were a wrong section
number or an invented sentence. Here the model manufactures a structural claim
about a document's table of contents, complete with a fabricated enumeration and
a fabricated quotation, to justify refusing the question.

The likely mechanism is visible in the run itself. H1 immediately precedes H2
and does contain a genuine false premise, which this model rejects correctly and
well. H2 does not. The model appears to have carried the pushback pattern
forward, then generated evidence to support it. That makes the H1 and H2 pairing
more valuable than I credited when the suite was written: it separates
calibrated skepticism from the reflex to disagree.

## P2 — calendar arithmetic that does not hold

The conclusion is right and the trap is caught: the maintenance window falls
after the deadline and the date must be re-baselined immediately. But the
supporting arithmetic contains a checkable error stated as universal.

The model asserts that the last Sunday is "Sunday the 24th under every possible
month length (28-31 days)" and that "a 31st, if the month has one, is a
Thursday". With the 1st falling on a Friday, the Sundays are the 3rd, 10th,
17th, 24th and, in a 31-day month, the 31st. I enumerated every month from 2024
to 2029 in which the 4th is a Monday: in six of eight, the last Sunday is the
31st, not the 24th.

This propagates into the deliverable. The revised delivery date of Friday the
29th assumes cutover on the 24th. In a 31-day month the cutover is the 31st and
delivery lands in the following month. Q5 and Q6 both handled this correctly by
carrying "the 24th or the 31st" through their plans. Docked on constraint for
the wrong date and on honesty for the universal quantifier.

## Notes on the rest

**L1 (6/6) — the strongest long-context answer of any run.** Three findings,
correct locks, no false positives, and unlike every other model it cites line
numbers. I checked all six against the suite file: 7982, 7984, 7985, 7989, 7992,
8027 and 8028 are all exactly right. No corpus was extracted to disk, so this
looks like genuine in-context reading with accurate positional recall rather
than file diffing.

**A1 (6).** Identifies the replay gap in the FIFO option as fatal for the stated
requirements, rejects Kafka on ownership cost rather than throughput, and gives
a concrete revisit threshold. At 599 words it is the leanest ADR in the set and
still complete.

**A3 (6).** Found the dual write unprompted, framed as the ledger not being on
the critical path, plus the DLQ misuse, missing idempotency and reconciliation.

**P1 (5).** Same miss as all five runs: the fallback-versus-enforcement conflict
is handled inside the tickets but never surfaced as a contradiction before the
list. Capacity arithmetic is correct at 40 engineer-days against 28 estimated.

**P3 (6).** Nine weeks, reached rigorously. It states the vendor assumption
explicitly, proves the packing optimal by showing weeks 4 to 6 hold exactly nine
engineer-weeks of capacity against nine of work, and separates the engineering
finish, which lands on the deadline with zero slack, from full delivery.

**H1 (6).** Rejects the premise correctly and ranks per-call set rebuilding
first. Notably it also gives the one genuine case where a list can beat a set,
short-circuiting on long shared-prefix keys for lookups that miss.

**I1, I2, I3 (6 each).** All twenty rate limiter tests pass on re-run, the median
reproduction and fuzz replay, and the merge verification passes at both small
and 64-bit scale. The median fix uses exact integer arithmetic with a Fraction
for odd sums.
