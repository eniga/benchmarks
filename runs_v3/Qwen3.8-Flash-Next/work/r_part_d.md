## P1

Capacity: 2 engineers × 4 weeks = 40 engineer-days; plan against ~34 usable days after ceremonies/on-call. Everything below is sized in engineer-days. Estimates are "focused days", with the two highest-risk items (SAML core, security review) deliberately padded.

| ID | Ticket | Est | Depends on | Owner | Planned |
|---|---|---|---|---|---|
| SSO-1 | Decision record + identity model: how a federated identity attaches to an existing user (email match? domain match? verified-email-only linking), account-link takeover rules, what "password fallback" means per org | 2 | — | A | W1 |
| SSO-2 | Migrations: `org_sso_config` (protocol, idp metadata, enabled, `enforce_sso`, grace_until), `federated_identity` (org, issuer/entity_id, subject, user_id, UNIQUE(issuer,subject)), audit events | 2 | SSO-1 | B | W1 |
| SSO-3 | OIDC core: code+PKCE, state/nonce, JWKS fetch+cache+rotation, claims validation (iss/aud/exp/nonce), subject selection, login callback, session issuance | 5 | SSO-2 | A | W1–W2 |
| SSO-4 | SAML core: POST binding, assertion signature + digest verification, audience/recipient/conditions, XSW/XXE hardening, cert rotation handling, IdP-initiated handling | 6 | SSO-2 | A | W2–W3 |
| SSO-5 | Linking & provisioning: verified-email linking, domain-based auto-provisioning policy, "must set password / must verify" transitions, unlink and re-link, duplicate-account merge guard | 3 | SSO-2 | B | W2 |
| SSO-6 | Admin API: config CRUD, metadata upload/parsing validation, permission checks (`org:sso:manage`), audit log, dry-run endpoint that validates metadata + mapping preview | 2 | SSO-2 | B | W3 |
| SSO-7 | Admin UI: per-org SSO settings page (protocol picker, IdP picker for Okta/Entra/Google, metadata paste, mapping editor, enforce toggle with warning + confirm, "test sign-in" button) | 4 | SSO-6 (API stub from W1) | B | W3–W4 |
| SSO-8 | Enforce SSO-only: auth policy in the login service (`enforce_sso` ⇒ password route 403 with reason), per-user break-glass list, grace period, session migration for already-logged-in users | 2 | SSO-3, SSO-4 | A | W4 |
| SSO-9 | Security hardening pass + external review: replay/fixation, redirect-URI allowlist, logout semantics (local vs SLO), cookie/CSRF interaction, threat model doc | 2 | SSO-3, SSO-4 | A | W4 |
| SSO-10 | Test harness: real test tenants (Okta dev + Entra test tenant), automated E2E (Playwright against both protocols), CI job, replayed real assertion fixtures | 3 | SSO-1 | B | W2–W3 (spread) |
| SSO-11 | Rollout: feature flag per org, 2 dogfood orgs, dashboards (login success by protocol, link rate, enforcement blocks), runbook, support docs, abuse/load check | 2 | all | B | W4 |
| SSO-12 | Client-facing docs + IdP setup guide per supported IdP | 1 | SSO-7 | B | W4 |

Total: 34 days ≈ usable capacity exactly. That is a full plate with no slack, which drives the sequencing advice below.

Week plan
- **W1:** A: SSO-1 → SSO-3. B: SSO-2, SSO-5 start, SSO-6 API stub published end of W1 so UI can begin. Gate: decision record approved (security + one mobile/web lead).
- **W2:** A: SSO-3 finish, SSO-4 start. B: SSO-5, SSO-10 harness (must have one real OIDC login working in CI by Friday W2).
- **W3:** A: SSO-4 (SAML). B: SSO-6, SSO-7 UI, SSO-10 finish. Gate: end of W3 — a dogfood org can sign in with both protocols on staging.
- **W4:** A: SSO-8, SSO-9. B: SSO-7 finish, SSO-11, SSO-12. Freeze W4 Wednesday; Thursday = security review; Friday = ship behind flag with 2 pilot orgs.

Dependencies that actually bite: SSO-4 is the long pole and has no parallelism (one person can own SAML correctly; splitting it is a bad idea). SSO-7 can only be built against SSO-6's API, so the API contract must exist by end of W1 — that is why SSO-2/SSO-6 stubbing comes first.

Scope-reduction options if W3's gate slips (pick in this order):
1. Ship OIDC fully supported and restrict SAML to Entra + Okta with pasted metadata XML (no ADFS, no signed requests, no SLO) — moves ~3 days off the critical path.
2. Admin UI v1 = validated form + JSON/JSON-schema-driven fields, no mapping preview and no "test sign-in"; support does the first setup for each org.
3. Enforcement v1 = per-org flag with break-glass list only (no grace period, no per-user exceptions).

Explicitly out of scope (call it out now, not in week 4): SCIM provisioning/deprovisioning, Just-in-Time provisioning beyond simple email/domain policy, session revocation on IdP logout (SLO), org-claimed-domain auto-enrolment, admin role inheritance, IdP-initiated login for unmanaged links.

Risks and mitigations
- **SAML rabbit hole (highest).** Mitigation: use a maintained library rather than hand-rolling XML signature work; SSO-4 has a 1-day "stop and escalate" trigger if we are still fighting canonicalisation.
- **Account-linking takeover.** Linking by unverified email lets an attacker attach a federated identity to someone's account. Decision record (SSO-1) must be signed before code; mitigation is verified-email-only linking plus a re-auth challenge on first link.
- **IdP test tenant access** (SSO-10) blocked by procurement/legal. Raise day 1 of W1; fallback to recorded fixtures + one manual test per release.
- **Security review scheduling.** Book it in W1 for Thursday W4; if it slips, the release slips (do not ship an SSO change unreviewed).
- **Password fallback + enforcement interaction** (users who lose their password under `enforce_sso`): define the admin-reset path in SSO-8, not later.
- **Two-engineer bus factor:** pairing on SSO-3/SSO-4 for the design halves the risk; the decision record plus runbook is the mitigation we can actually afford.

## P2

The binding constraint is not engineering: a 45-minute exclusive lock cannot be taken before Friday the 28th, because the only permitted window is the first Monday of a month and there is no exception process. So the plan must stop treating the lock as part of the deadline. Two things happen in parallel from today.

**Ask, in writing, today (and stop planning around the answer).** An email to the change board chair: what the change is, the blast radius, the rollback, and the two candidate dates. Copy the deadline's owner. This costs an hour and it is the only route to the original plan; everything below assumes "no".

**Re-scope so the deadline contains no long lock.** The 45 minutes is almost certainly a *rewrite/backfill* cost, not a semantic requirement, so the plan is to make the migration online and reduce the exclusive-lock step to a metadata-only swap.

Revised plan (Thu 6 → Fri 28)

- **Thu 6 (today, ~1 day): split the migration into "what needs the lock" and "what does not".** Write down, statement by statement, the DDL that needs the 45 minutes. In Postgres these are usually online and can be dropped from the locked window entirely: `CREATE INDEX CONCURRENTLY`, `ADD COLUMN` (nullable, no default), `CREATE TABLE` alongside, `CREATE TYPE`, triggers, logical replication. If any statement is a table rewrite (`ALTER COLUMN TYPE`, adding a `volatile` default, changing a `NOT NULL` on an old version, `CLUSTER`), reproduce it in staging and time a lock-free equivalent (new column + chunked backfill + rename). **Decision gate Friday noon:** if a lock-free path exists, the 28th is deliverable as originally scoped. If it does not, the deadline ships the compatibility layer and the physical migration is booked on the board's next first Monday.
- **Fri 7 (half day): freeze the API contract.** The API layer reads the new schema; the client has not started. Lock the HTTP/JSON contract now so client work can proceed against the contract regardless of which physical schema is live. Publish a versioned stub today.
- **Mon 10 → Fri 14: build the new structure next to the old and backfill without an exclusive lock.** Create `orders_new` (or the target partitioned set), then chunked `INSERT ... SELECT` batches of ~1–2 M rows inside business-hours throttling, or logical replication into the new table. 400 GB at a conservative 60 GB/night is under a week; keep a rolling validation job comparing row counts and per-partition checksums, and keep change-capture (trigger or logical decoding) running so the backfill stays converged.
- **Mon 17 → Wed 19: converge and switch traffic through a compatibility layer.** API writes go to both (or to a view with `INSTEAD OF` rules); API reads go new-first with old-fallback; run sampled shadow-read diffs and alert on any mismatch for 48 hours. Client work continues against the frozen contract.
- **Thu 20 → Fri 21: rehearse.** Full cutover + rollback rehearsal against a production-scale copy, including the rename swap: measure how long `ALTER TABLE ... RENAME` holds `ACCESS EXCLUSIVE` (metadata-only, typically milliseconds, but confirm there is no long-running transaction or autovacuum holding it; set `lock_timeout` and `statement_timeout` on the swap script). Publish timings in the change ticket.
- **Mon 24: code freeze for the deadline, dry run on staging.** Tue 25: readiness review with the API and client owners (client is the riskiest track — it started last and is on the deadline). Wed 26: go/no-go. Thu 27: hold day for client fixes. **Fri 28: ship** — flag flip / view-or-rename swap in seconds, old table kept intact and writable-through-capture for 7 days as the rollback.
- **After the deadline, on the board's next approved Monday:** the deferred exclusive-lock step runs in its 45-minute window, with rollback rehearsed; the compatibility layer is removed one week later, after the deferred step is verified. If the deferred step is "repack/partition-move" and we are confident, it can also be dropped entirely and replaced by online maintenance — revisit on the date.

What changes vs. the original plan: the deadline delivers the *logical* migration (new schema visible to API and client, contract stable, data validated) and the physical layout follows on the board-approved date. The cost of that trade is the compatibility layer lives for an extra ~2–4 weeks (extra write amplification, one more thing to test), which is strictly better than missing the deadline or taking an unsanctioned lock.

Risks: (1) the compatibility layer is where bugs hide — mitigate with the shadow-read diff and a kill-switch back to old-first reads; (2) client started last, so Wednesday go/no-go must be a real gate with a documented "client ships behind a flag on old schema" fallback; (3) backfill load — cap and monitor replication lag daily; (4) if the whole 400 GB migration is genuinely impossible online, then the deadline itself is the thing to renegotiate this week, with the board date as the immovable fact; do not let that conversation happen after the 28th.

## P3

Assumptions, stated up front: (1) estimates are engineer-weeks and tasks other than W may be split across engineers with the split cost ignored — Plan B adds that cost back; (2) W is single-owner, 4 consecutive weeks, cannot be compressed by adding people; (3) "needs complete" is a hard finish-to-start dependency (X cannot begin before W is done; Z cannot begin before X is done; V cannot begin before Z is done); (4) the auditor's 3-week notice is a lead-time on the audit *date*, can be given at any time from week 1, and does not have to be preceded by any task completion — the notice is served in week 1 and re-confirmed shortly before the audit (week 5 in Plan A, week 9 in Plan B), so it is never the constraint; (5) four interchangeable engineers, no holidays, 8 working weeks; (6) I need a calendar, so I assume the programme starts on Monday 5 January 2026; the 8-week deadline is therefore Friday 27 February 2026. If your start date differs, shift every date by the same offset.

The arithmetic that decides everything: the dependency chain W → X → Z → V contains 4 + 6 + 4 + 2 = 16 engineer-weeks in series. Team capacity is 4 × 8 = 32 engineer-weeks against 18 engineer-weeks of work, so **capacity is not the problem — the serial chain is.** With no splitting inside tasks, that chain alone is 16 calendar weeks. Even with aggressive splitting, the chain is 4 (W, irreducible) + 2 (X: 6 ÷ 3 engineers) + 2 (Z: 4 ÷ 2) + 1 (V: 2 ÷ 2) = **9 weeks minimum**. So the 8-week deadline is not achievable; it must be renegotiated, or the chain must be shortened by changing scope/dependencies. Below are both schedules.

Plan A — fastest legal schedule (best case, no split cost, X and Z and V split)

| Week | Eng 1 | Eng 2 | Eng 3 | Eng 4 |
|---|---|---|---|---|
| 1 | W: migration | *prep: X design doc, contract stubs, test harness (explicitly not the rewrite)* | *prep: Z partner API stub/contract* | *prep: telemetry schema* |
| 2 | W | prep | prep | prep |
| 3 | W | prep | prep | prep |
| 4 | W | prep | prep | prep |
| 5 | X | X | X | Y |
| 6 | X | X | X | Y |
| 7 | Z | Z | — | — |
| 8 | Z | Z | *support/QA on X, docs* | *support* |
| 9 | V (audit support) | V | *release* | *release* |

- **Critical path:** W(4) → X(6 eng-wks across 3 in 2 wks) → Z(4 across 2 in 2 wks) → V(2 across 2 in 1 wk) = 9 calendar weeks.
- Float: Y only (any 2 engineer-weeks after week 4; scheduled 5–6, one engineer).
- **Delivery: Friday of week 9 = Friday 6 March 2026 — one week past the deadline** (27 February), even under ideal conditions.

Plan B — schedule I would commit to (splitting costs, one engineer per task where it makes sense)

| Week | Eng 1 | Eng 2 | Eng 3 | Eng 4 |
|---|---|---|---|---|
| 1–4 | W (single owner) | X design, scaffolding, feature flag, contract stubs | telemetry schema + tooling (prep for Y) | partner SDK skeleton against stubs (explicitly not Z's core work) |
| 5–7 | X (week 7 = hardening/soak) | X | X | Y (weeks 5–6, verified in 7) |
| 8–11 | Z (single owner, 4 wks) | Z-support: tests, partner comms | telemetry dashboards, docs | X soak + on-call, docs |
| 12 | V (audit) | V-support | release | release |

- **Critical path:** W → X → Z → V = 4 + 3 + 4 + 1 = 12 weeks wall-clock (X split over 3 engineers, Z single-owner).
- **Delivery: Friday of week 12 = Friday 27 March 2026.**
- Auditor notice served week 1 (covers any audit date from week 4 onward); re-confirmed week 9 for the week-12 audit — the notice period is never the constraint.

What must change to hit 8 weeks (ranked by leverage)
1. **Shorten W — it is the only unsplittable item and it owns the front of the critical path.** Descope the migration (4 → 2 weeks by migrating only hot tables and shadowing the rest behind a flag) buys 2 weeks. This is the single highest-leverage change.
2. **Break the X → Z dependency.** Contract-first: freeze X's external interface in week 2 and let Z build against stubs from week 5, integrating in week 8 instead of starting in week 7. Buys ~2 weeks and costs integration risk.
3. **Split X properly** (2 engineers, 3 weeks) with the module boundaries drawn in weeks 1–4 — buys 1 week vs. Plan B, at the cost of coordination.
4. **Shrink V.** A 2-week audit with a pre-submitted evidence pack (weeks 7–9) and 3 days of auditor time is often acceptable; if the auditor agrees, that is another week back.
5. **Descope Z to a smaller SDK surface** (or ship the partner a hosted API for launch and the SDK in phase 2) — up to 3 weeks.
6. Last resort: add engineers — buys nothing on the chain, only on Y and support work.

Recommendation: present Plan A as the honest floor (9 weeks, delivery Friday 6 March 2026), take options 1 and 2 to the deadline owner this week, and hold Y and telemetry as the float you sacrifice first if the chain slips.
