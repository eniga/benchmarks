## P1
Two engineers, four weeks = 8 engineer-weeks of capacity. The breakdown below totals ~7 engineer-weeks, leaving ~1 week of buffer for the riskiest item (SAML). Estimates are in engineer-weeks (ew).

**Tickets**

| ID | Ticket | Est | Depends on |
|----|--------|-----|------------|
| T1 | SSO integration layer + **OIDC** (auth-code + PKCE, ID-token validation, claims→user mapping) | 1.0 | — |
| T2 | Per-org SSO config: data model + API (provider type, client/SP settings, `enabled`, `sso_only`) | 0.5 | — |
| T3 | Admin settings UI: choose provider, enter credentials, "test connection", toggle SSO / SSO-only | 0.5 | T2 |
| T4 | **SAML** SP integration (metadata, ACS endpoint, assertion + signature validation, NameID) | 1.0 | T1 |
| T5 | Account linking: map SSO subject to existing user by email; first-login link flow; collision handling | 0.5 | T1, T2 |
| T6 | Login routing: org with SSO enabled → redirect to IdP; keep password login as fallback when allowed | 0.5 | T1, T4, T5 |
| T7 | SSO-only enforcement: block password login for `sso_only` orgs; notice/migration for affected users | 0.5 | T6 |
| T8 | Logout (SAML SLO / OIDC back-channel), session handling, state/CSRF hardening | 0.5 | T1, T4 |
| T9 | Integration + e2e tests against test IdPs (OIDC and SAML), security review | 1.0 | T3, T4, T6, T7, T8 |
| T10 | Docs, admin help, monitoring/alerts, staged rollout | 0.5 | T9 |

Total: 7.0 ew.

**Two-engineer schedule (4 weeks)**

- **Engineer A (backend):** Wk1 T1 → Wk2 T4 → Wk3 T6 → Wk4 T9.
- **Engineer B (full-stack):** Wk1 T2 + T3 → Wk2 T5 → Wk3 T7 + T8 → Wk4 T10.

Dependencies are respected: T6 (A, Wk3) needs T4 (A, Wk2), T1 (A, Wk1) and T5 (B, Wk2); T7 (B, Wk3) needs T6 (A, Wk3) — so T6 lands early in Wk3 and T7 follows; T9 (A, Wk4) needs T3/T4/T6/T7/T8, all done by end of Wk3.

**Risks / notes**
- SAML (T4) is the riskiest (XML, signatures, clock skew, NameID). The 1 ew buffer absorbs slippage; if it blows up, cut scope by shipping OIDC first and deferring SAML to a fast-follow (both are behind the same T1 layer, so this is a clean cut line).
- Account-linking collisions (T5) and SSO-only lockout (T7) are the main user-safety risks; both are gated behind T9's e2e tests before rollout.
- Password fallback is preserved by default (T6) and only disabled per-org via `sso_only` (T7), so existing users are unaffected until an admin opts in.

## P2
**The deadline cannot be met as stated — and the first thing the revised plan must say is why.**

Today is Thursday the 6th. Working backwards, the 1st of this month is a Saturday, so the **first Monday of this month was the 3rd** — already past. The change-advisory board only permits schema changes on the first Monday of a month, with no exception process, and its next meeting is after the deadline. The deadline is Friday the 28th of the *same* month. The next first Monday is therefore in **next month, after the 28th**. The 45-minute exclusive-lock migration is a schema change, so it cannot legally run before the first Monday of next month. **The cutover is infeasible on the 28th.**

**Revised plan**

1. **Move the deadline (formally).** Request the deadline be re-set to the first Monday of next month (the earliest permitted cutover), plus a one-week buffer for the cutover itself and any rollback. Since the standing first-Monday rule already permits the change, this does not require the quarterly board meeting — it only needs the first-Monday window and a scheduled change record.

2. **Use the interim (6th → first Monday of next month) to finish and de-risk everything that is *not* the lock:**
   - **Finish the half-built API layer** that reads the new schema, and test it against a staging copy of the new schema (the migration code is already done and staging-tested, so a staging new-schema exists).
   - **Build the client work** (not started) and test it against staging.
   - **Add a backward-compatible read path (dual-read)** so the old API keeps serving during the window and we can roll back the read path instantly if the new schema misbehaves.
   - **Rehearse the cutover end-to-end in staging:** measure the *actual* lock duration for 400 GB against the 45-minute budget, run the rollback script, and validate data (row counts + checksums) before/after.
   - **Prepare the 45-minute exclusive-lock window:** user comms, an off-peak maintenance slot, a go/no-go checklist, and a named rollback owner. During the lock the table is unavailable, so this is a real outage for writers and must be scheduled and announced.

3. **On the first Monday of next month:** execute the rehearsed cutover (45-minute lock) with the finished API and client going live in the same coordinated window, then monitor and keep the dual-read fallback available for a rollback period.

**Why this is the right call.** The board's rule is a hard external constraint with no exception path, so no amount of engineering effort on the two remaining engineers makes the 28th possible. The value we *can* deliver before the (re-set) date is: a finished, tested API + client, a rehearsed and timed cutover, a rollback plan, and a dual-read safety net — i.e., the cutover becomes a low-risk, well-understood 45-minute event rather than a first attempt under deadline pressure. The one thing to avoid is pretending the 28th is achievable and burning the interim period on work that can't ship until the first Monday anyway.

## P3
**Assumptions**
- **Splitting:** W is single-owner and cannot be parallelised (given). I assume X, Y, Z and V *can* be split across engineers: X across up to 3, Z across up to 4, V across up to 2, Y across 1. (If a task is less splittable than assumed, its duration lengthens and the plan slips — see slack note.)
- **Auditor notice:** I assume the 3-week notice can be sent **at project start (week 1)**, because we can commit to an audit window in advance. The 3-week lead time then runs in parallel with W/X/Z and does **not** extend the critical path. (This assumption is load-bearing: if the notice could only begin once Z was complete, the 3-week lead would push V to week 10 and the 8-week deadline would be missed.)

**Week-by-week plan (4 engineers: E1–E4)**

| Week | E1 | E2 | E3 | E4 | Notes |
|------|----|----|----|----|-------|
| 1 | W | send auditor notice (book wk 8) | prep (env, test data) | prep (SDK scaffolding) | W starts; notice sent early |
| 2 | W | prep | prep | prep | |
| 3 | W | prep | prep | prep | |
| 4 | W (done) | prep | prep | prep | W complete end of wk 4 |
| 5 | X | X | X | Y | X (3 eng) + Y (1 eng) start |
| 6 | X (done) | X (done) | X (done) | Y (done) | X, Y complete end of wk 6 |
| 7 | Z | Z | Z | Z | Z (4 eng) — 4 ew in 1 wk |
| 8 | V | V | buffer/fixes | buffer/fixes | V (2 eng) — audit; delivery |

**Critical path:** W → X → Z → V.
- W: 4 wk (single owner, fixed)
- X: 2 wk (6 ew ÷ 3 engineers)
- Z: 1 wk (4 ew ÷ 4 engineers)
- V: 1 wk (2 ew ÷ 2 engineers)
- **Total: 4 + 2 + 1 + 1 = 8 weeks.**

Y (2 ew, weeks 5–6) runs in parallel with X and is **not** on the critical path. The auditor notice (sent week 1) is also off the critical path under the stated assumption.

**Delivery date: end of week 8** — exactly on the 8-week deadline, with **zero slack** under the integer-week allocation above.

**Slack / sensitivity.** The critical path is the whole budget. If X is compressed to 1.5 weeks (4 engineers) and V to 0.5 weeks, the chain shortens to 4 + 1.5 + 1 + 0.5 = 7 weeks, giving 1 week of buffer. Any slip in W (the fixed 4-week single-owner task) or in the X→Z→V chain consumes that buffer directly. The single biggest schedule risk is over-optimistic splitting of Z (4 ew in 1 week needs 4 genuinely independent workstreams); if Z can only use 2 engineers, it takes 2 weeks and delivery slips to week 9 — so confirming Z's split-ability in week 1 is the key early de-risking action.
