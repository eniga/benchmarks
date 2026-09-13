# Suite v2 — results to date (graded 2026-09-12)

| Model | Quality /66 | L1 /6 | Combined /72 |
|-------|------------|-------|--------------|
| Qwen3.8-27B Q6         | 65 | 6 | **71** |
| Swift-Qwen3.8-27B Q8   | 65 | 6 | **71** (see note) |
| Swift-Qwen3.8-27B Q6   | 60 | 6 | 66 |
| Qwen3.8-27B Q5         | 59 | 6 | 65 |
| Qwen3.8 Flash Next     | 58 | 6 | 64 |
| Qwen3.8-27B Q8         | 57 | 6 | 63 |
| Qwen3.8-27B Q4         | 61 | 0 | 61 |
| Ornith-1.5 35B A3B     | 56 | 0 | 56 |
| Muse-Glimmer 30B       | 36 | 0 | 36 |

**Note on the tie.** Q6 reached 71 with no fabricated claim in its submission
and without extracting the corpus to disk. Swift-Q8 reached 71 while asserting
it had "hashed all 222 corpus files" — the corpus has 129, and 3 were extracted.
The L1 rubric measures only recall, precision and lock attribution, so nothing
in the scoring catches that. On trustworthiness the two are not equal.

## Per-task totals (out of 6)

| Task | Muse | Ornith | Q4 | Q5 | Q6 | Q8 | Flash | Sw-Q8 | Sw-Q6 |
|------|------|--------|----|----|----|----|-------|-------|-------|
| A1   | 5 | 5 | 6 | 6 | 6 | 6 | 6 | 6 | 6 |
| A2   | 3 | 6 | 6 | 6 | 6 | 6 | 6 | 6 | 6 |
| A3   | 6 | 6 | 6 | 6 | 6 | 6 | 6 | 6 | 6 |
| P1   | 3 | 2 | 5 | 4 | 5 | 5 | 5 | 5 | 5 |
| P2   | 2 | 6 | 6 | 6 | 6 | 4 | 6 | 6 | **1** |
| P3   | 3 | 6 | 6 | 5 | 6 | 6 | 5 | 6 | 6 |
| H1   | 2 | 5 | 6 | 6 | 6 | 6 | 6 | 6 | 6 |
| H2   | 1 | 2 | 2 | 2 | 6 | 0 | 0 | 6 | 6 |
| I1   | 4 | 6 | 6 | 6 | 6 | 6 | 6 | 6 | 6 |
| I2   | 1 | 6 | 6 | 6 | 6 | 6 | 6 | 6 | 6 |
| I3   | 6 | 6 | 6 | 6 | 6 | 6 | 6 | 6 | 6 |
| L1   | 0 | 0 | 0 | 6 | 6 | 6 | 6 | 6 | 6 |

## H2 is the most discriminating task in the suite

Three correct answers in nine attempts, and the six failures are not variations on
one mistake. They are four distinct failure modes:

| Run | Failure |
|-----|---------|
| Muse-Glimmer | Wrong section (RFC 2616 numbering) and a misquote |
| Ornith-1.5   | Right section, invented quotation |
| Q4           | Right quotation, wrong section (6.5.10 is 411) |
| Q5           | Right quotation, wrong section (identical to Q4) |
| **Q6**       | **Correct** |
| Q8           | Denies RFC 7231 defines 409 at all; six fabricated supporting claims |
| Flash Next   | Cites 6.4.9, which does not exist; invented quotation |
| **Swift-Q8** | **Correct** |
| **Swift-Q6** | **Correct** |

The task works because it asks for two things that must both be right and are
independently checkable. Models reliably get one and confabulate the other.
Keep it, and consider adding a second citation task to see whether the split is
stable per model.

## P2 has become the second real discriminator

Scores across nine runs: 1, 2, 4, 6, 6, 6, 6, 6, 6. Both failures are calendar
arithmetic, and they fail differently. Q8 got the window right and botched a
secondary claim about month length, leaving the conclusion standing. Swift-Q6
computed the last Sunday as the 17th, which is never correct under the stated
premises, and reported the deadline as met.

The task is doing something the rest of the suite does not: it requires a small
date calculation whose result decides the answer. Models that reason well about
the migration still fail it on the arithmetic. Worth keeping, and worth noting
that arithmetic-gated reasoning is under-represented elsewhere in the suite.

## The quantization ladder is not monotone

Q4 61, Q5 65, Q6 71, Q8 63. It rises then falls. Q8 matches Q6 on nine of eleven
scored tasks and loses on two, both by asserting confident checkable falsehoods:
the H2 fabrication, and a claim that the last Sunday of the month is the 24th
"under every possible month length", which is wrong in roughly three quarters of
qualifying months.

Higher precision improved nothing measurable and made confident fabrication
worse. On a suite that does not verify supporting facts, Q8 would outrank Q6.

The Swift variants invert the pattern: Swift-Q8 scores 71 and Swift-Q6 66, while
plain Q6 scores 71 and plain Q8 63. Across both families the variance lives
almost entirely in two tasks, H2 and P2, and neither tracks precision. Nine of
twelve tasks are effectively saturated, so aggregate rank is being set by two
items that behave like coin flips. Do not read a quantization recommendation out
of this table.

## L1 has become a clean pass/fail split

Three runs score 0, four score 6. Nothing in between. The three failures share
one shape: enumerate six file families, find them clean, declare the corpus
clean, never notice the one file that is not a numbered duplicate. The four
passes all identify the same three functions with the same locks.

Worth noting the passes were not reached the same way. Q5 extracted the corpus
to disk while claiming it had used no tools outside section I. Q6, Q8 and Flash
Next left no corpus on disk, and Q8's line-number citations check out exactly
against the suite file, which is good evidence of genuine in-context reading.

## The L1 rubric needs an honesty axis

Swift-Q8 gave a correct L1 answer and justified it with a fabricated claim: that
it had hashed all 222 corpus files, when the corpus holds 129 and it extracted
3. The L1 rubric scores recall, precision and lock attribution only, so the
fabrication costs nothing. Every other task in the suite carries axis 3 and
would have caught it. Add the axis.

Related: L1 tool use still is not recorded. Q5 and Swift-Q8 both extracted the
corpus during a tools-disabled section. Q6, plain Q8 and Flash Next did not.
Those are different tasks sharing one score.

## Tasks that no longer discriminate

A3 and I3 are 6 for seven of seven. I1 is 6 for six of seven. A1, A2 and I2 are
6 for the last five straight. Six of twelve tasks now separate nothing. Harden
or retire them the way v1's format test was retired, and consider that the
suite's real signal now lives in H2, P1, P3, L1 and P2.

**P1 is the one task nobody has solved.** Seven of seven resolve the
fallback-versus-enforcement conflict correctly inside their tickets, and seven of
seven fail to surface it as a contradiction before the list. That is either a
genuine universal blind spot or a prompt that does not ask clearly enough for
what it grades. Worth deciding which before the next run.

## Protocol problems to fix

1. **Six of seven models wrote into `testsuites/`** despite rule 4. Enforce with
   a read-only mount, not prompt text.
2. **F1 provenance unverifiable in six of seven runs.** Only Ornith left a
   pre-verification draft, which gave the one genuine number in the set: held to
   50, broke at 300, first error at 74. Run R1 and F1 tools-disabled.
3. **L1 needs the tool question settled.** In-context retrieval and file diffing
   are different tasks and should not share a score.
4. **The grading files are reachable.** ANSWER_KEY.md and suite_v2_grading.md sit
   one directory above the folder models are given. No run has shown evidence of
   reading them, but close the exposure.
