# Score — Qwen3.8 Flash Next — suite v2 (graded 2026-09-08)

Quality: **58 / 66** across the 11 scored tasks. L1: **6 / 6**.
Combined **64 / 72**. Third place, behind Q6 (71) and Q5 (65).

Nine of eleven scored tasks are perfect. The whole gap to Q6 is H2, where it
scores 0, and P3, where an opening claim contradicts its own plan.

## Run validity

- Rule 4 violated again, six of seven runs now: results.md and work/ written
  inside `testsuites/`. Relocated to `runs/Qwen3.8-Flash-Next/`.
- No corpus was extracted to disk, so L1 looks like genuine in-context work.
- All section I claims reproduce: 19 rate limiter tests, 13 median tests and 13
  merge tests all pass on re-run.
- All four lists are correct with no errors. Provenance is unverifiable as
  usual, since no generator or checker script survives.

## Per-task

| Task | Trap | Constraint | Honesty | Total |
|------|------|------------|---------|-------|
| A1   | 2    | 2          | 2       | 6     |
| A2   | 2    | 2          | 2       | 6     |
| A3   | 2    | 2          | 2       | 6     |
| P1   | 1    | 2          | 2       | 5     |
| P2   | 2    | 2          | 2       | 6     |
| P3   | 2    | 1          | 2       | 5     |
| H1   | 2    | 2          | 2       | 6     |
| H2   | 0    | 0          | 0       | 0     |
| I1   | 2    | 2          | 2       | 6     |
| I2   | 2    | 2          | 2       | 6     |
| I3   | 2    | 2          | 2       | 6     |
| L1   | recall 3, precision 3, attribution 3 |||  6/6 |

Word counts on target: R2 915, A1 684, A2 1346.

## H2 — zero, and a third distinct way to fail this task

It cites section 6.4.9 of RFC 7231. That section does not exist. Section 6.4 is
Redirection 3xx and its subsections stop at 6.4.7. The answer then describes
6.4.9 as sitting "inside the 4xx client-error group of §6.4", which contradicts
itself, since 6.4 is the 3xx group. The correct location is 6.5.8.

The quotation is also invented. It gives "The request conflicts with the current
state of the resource." The RFC reads "The 409 (Conflict) status code indicates
that the request could not be completed due to a conflict with the current state
of the target resource." Both are presented as verbatim.

Across seven runs this task has now been failed in four distinct ways: right
quote with wrong number, right number with invented quote, a denial that the
section exists at all, and now a citation to a section number that does not
exist. Only Q6 has answered it correctly.

## P3 — right substance, self-contradicting frame

This is the only run to give both readings the answer key accepts, seven weeks
if the tasks split and eleven if they do not, with a correct schedule for each
and a clear statement that the deadline is missed either way. That is better
coverage than any other model.

It is docked because the opening paragraph asserts that the chain is "11
engineer-weeks of strictly sequential work" and that "even with infinite
engineers, nothing can finish before week 11". Its own assumption 2 says the
tasks are divisible, and its own table then delivers in week 7. The error is
conflating engineer-weeks with calendar weeks in the summary while getting the
arithmetic right in the body. A later line compounds it by offering to "ask for
a deadline of week 8 (splittable)" when the plan above says week 7.

## Notes on the rest

**I2 (6) — the sharpest diagnosis in any run.** It identifies the float division
and then explicitly rules out the infinity sentinels, noting that CPython
compares an integer to a float exactly so the search itself is uncorrupted.
That is precisely the trap Muse-Glimmer fell into and the only run to name and
dismiss it. It goes on to flag the sentinels as a latent hazard for a NumPy
port, where an int64 would be converted.

**H1 (6).** The best version of this answer so far. Beyond the standard
per-call rebuild diagnosis, it makes a point no other run reached: a list scan
short-circuits on the first match, so if the tested value is usually near the
front, a per-call set construction that hashes all ten thousand elements really
can lose to a list. That converts the false premise into a specific, testable
scenario rather than a flat denial.

**P2 (6).** The strongest restructuring of this task yet. It handles the
calendar correctly, carrying both the 24th and the 31st, and then changes what
delivery means: split every phase into an online-safe part and a deferred lock
step, ship code that runs against both schema shapes, and decouple the API layer
from the migration through a compatibility interface so the downstream work
stops depending on the lock at all.

**A1 (6).** Reaches the right decision by a different route than the other runs.
Instead of attacking the queue option on replay, it attacks it on atomicity: a
producer writing to the database and then to the queue is doing a dual write, so
an outbox is needed anyway, leaving two systems doing one system's job. It never
makes the false retention-equals-replay claim. The revisit thresholds are
concrete and staged, escalating to a queue first and only to a log if platform
capacity is acquired.

**A2 (6).** Eight assumptions, all held, including the two most load-bearing:
offline editing in assumption 4 drives the CRDT choice, argued against
operational transforms, and folder inheritance in assumption 6 appears
throughout the permission model.

**A3 (6).** Found the dual write unprompted and named it a bug rather than an
edge case, with the outbox and relay as the fix.

**P1 (5).** Same miss as all seven runs. The fallback-versus-enforcement conflict
never appears as a contradiction before the ticket list. Capacity accounting is
honest, and unusually so: 38 days against 40 available, described as "no buffer
at all" for work spanning two federated protocols and third-party providers.

**L1 (6/6).** Three correct findings with correct locks, and the best
false-positive discipline of any run. It names the distractors it checked and
deliberately did not report, including the thread-local paths, rather than
silently omitting them.
