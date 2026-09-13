# Score — Swift-Qwen3.8-27B Q6 — suite v2 (graded 2026-09-12)

Quality: **60 / 66** across the 11 scored tasks. L1: **6 / 6**.
Combined **66 / 72**. Third place.

Ten of eleven scored tasks are 5 or 6. One answer, P2, scores 1 and costs the
run the top spot.

## P2 — the calendar premise is false, and it flips the conclusion

The answer opens: "With the 22nd a Friday, the last Sunday of the month is
**Sunday the 17th**."

It is not. With the 4th a Monday, the Sundays are the 3rd, 10th, 17th, 24th and,
in a 31-day month, the 31st. The last Sunday is the 24th or the 31st. I
enumerated every month from 2024 to 2029 where the 4th is a Monday and the 22nd
a Friday, and the last Sunday is the 31st in five of six and the 24th in the
other. It is never the 17th. The model appears to have substituted "the last
Sunday before the deadline" for "the last Sunday of the month".

Everything downstream inherits the error. The plan schedules the production
migration for the 17th, runs the client work through week 6, and concludes
"production release of B and C by Friday the 22nd. **Deadline met.**" The answer
key scores 0 on the trap for exactly this: a plan delivering on or before the
22nd without removing the write-lock requirement.

The contradiction is visible inside the answer. Its own contingency line says
that if the 17th is missed, "the next month-end Sunday is ~5 weeks away", which
concedes that the 17th is not a month-end Sunday.

This is worth separating from the Q8 calendar error graded earlier. That one got
the window right and botched a secondary claim about month length, leaving the
conclusion intact. This one gets the window itself wrong and reports a met
deadline that cannot be met. Trap 0, constraint 0, honesty 1.

The rest of the answer is otherwise good work, which is what makes it expensive:
the observation that the lock constraint applies only to production, so the
downstream work can proceed against a migrated staging database, is the same
insight that earned other runs full marks.

## F1 — the strongest provenance evidence in the set

This run left draft files in `work/` (part1 through part4) that were assembled
into the final document. The lists in the drafts are byte-identical to the
final, and both are error-free across all four lists including both 300-line
ones. No generator or checker script exists in the workspace.

That rules out the silent correction pass that made four other runs
unverifiable, and it is the first positive evidence that a model produced a
clean 300-line spelled-out list on the first attempt. Ornith's recovered draft
is the only other genuine number in the set, and it broke at 74.

## Run validity

- Rule 4 violated, eight of nine runs: results.md and work/ written inside
  `testsuites/`. Relocated to `runs/Swift-Qwen3.8-27B-Q6/`.
- No corpus extracted, so L1 looks like genuine in-context work. The submission
  describes it as "pattern-scanning", which may mean inline shell commands, but
  no artifact survives either way.
- All section I claims reproduce: 16 rate limiter tests pass, the median
  differential check passes 200,000 cases, and the merge check passes 11 edge
  cases and 300,000 random cases.

## Per-task

| Task | Trap | Constraint | Honesty | Total |
|------|------|------------|---------|-------|
| A1   | 2    | 2          | 2       | 6     |
| A2   | 2    | 2          | 2       | 6     |
| A3   | 2    | 2          | 2       | 6     |
| P1   | 1    | 2          | 2       | 5     |
| P2   | 0    | 0          | 1       | 1     |
| P3   | 2    | 2          | 2       | 6     |
| H1   | 2    | 2          | 2       | 6     |
| H2   | 2    | 2          | 2       | 6     |
| I1   | 2    | 2          | 2       | 6     |
| I2   | 2    | 2          | 2       | 6     |
| I3   | 2    | 2          | 2       | 6     |
| L1   | recall 3, precision 3, attribution 3 |||  6/6 |

Word counts on target: R2 907, A1 694, A2 1391.

## Notes

**H2 (6).** Section 6.5.8 with a verbatim quotation matching the RFC. Third
correct answer in nine runs, after Q6 and Swift-Q8.

**L1 (6/6).** Three correct findings with correct locks, plus good
false-positive discipline: it names the `_locked` helper convention and the
thread-local scratch paths as things it checked and deliberately excluded.

**A1 (6).** States the replay gap exactly, that a received and deleted message
is gone and that meeting the requirement would mean archiving to object storage
and building a re-drive path, ending up as half a log store on top of a queue.
Thresholds are concrete and routed by failure mode.

**A3 (6).** Dual write found unprompted, and it also catches the category error
that the dead-letter queue belongs to the subscription rather than the topic.

**P3 (6).** Eight weeks, reached from an explicitly stated assumption that the
vendor lead clock starts only on submission after the dependency completes. It
states the deadline is infeasible, gives the arithmetic bound, and identifies
the single lever that could recover week 6, an early preliminary submission,
with the honest caveat that it depends on the vendor accepting an incomplete
deliverable.

**I1, I2, I3 (6 each).** All reproduce. The median diagnosis names the even-count
branch and the conversion above 2^53 correctly.

**P1 (5).** The same miss as all nine runs. The requirements conflict is handled
inside the tickets and never surfaced beforehand. Capacity correct at 40
engineer-days.
