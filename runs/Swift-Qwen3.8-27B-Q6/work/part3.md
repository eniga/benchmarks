## A1
# ADR-001: Event transport for the order-processing service

**Status:** Accepted
**Deciders:** Backend engineering (2 engineers, no platform team)

### Context

The new order-processing service must publish order-lifecycle events (created, paid, shipped, cancelled) to downstream consumers in billing, fulfilment, and analytics. Requirements:

- Peak 40 events/sec, about 3M events/day, average payload 2 KB (roughly 6 GB/day, 42 GB/week).
- Strict per-customer ordering: events for one customer must be consumed in production order. Global ordering is not required.
- The last 7 days of events must be replayable for reprocessing.
- Two backend engineers, no dedicated platform team.
- Already running Postgres 16 (managed) and AWS; no Kubernetes.

The binding constraint is operational capacity, not throughput: the transport must be boring.

### Options considered

#### 1. Kafka (Amazon MSK)

Kafka gives per-partition ordering (partition by customer id), 7-day retention as a configuration, and native replay via consumer groups. It is the most powerful option and the most expensive to operate: a minimum MSK deployment is a three-broker cluster that we would size, patch, monitor, and alert on ourselves; the client library, schema registry, and consumer-group semantics add real learning and maintenance cost; and at 40 events/sec we would use a tiny fraction of its capacity. With no platform team, Kafka becomes a second product we must own.

#### 2. AWS SQS FIFO

SQS FIFO provides strict per-`MessageGroupId` ordering, which maps exactly to per-customer ordering, and supports retention up to 14 days, so a 7-day window is a configuration. It is fully managed and cheap. The fatal gap is replay: once a consumer receives and deletes a message, it is gone. "Replay the last 7 days" would require archiving every message to S3 on receipt and building a re-drive path from S3, plus per-consumer replay positions that SQS does not track. We would end up building half a log store on top of a queue.

#### 3. Postgres as a queue

An `events` table (`customer_id`, `seq`, `payload`, `created_at`, `status`) with consumers polling `SELECT ... WHERE status = 'pending' FOR UPDATE SKIP LOCKED`. Postgres 16 is already running and managed. Per-customer ordering falls out of a `(customer_id, seq)` index; 7-day replay is a re-scan with `created_at > now() - interval '7 days'`, and retention is a nightly delete; 40 inserts/sec and a handful of consumer polls/sec are trivial for a modest RDS instance. The costs are real but bounded: polling latency (a 100 ms poll interval is ample), at-least-once delivery (consumers must be idempotent, which they should be anyway), and table hygiene (monthly partitioning, vacuuming).

### Decision

**Use Postgres as the event queue.**

It is the only option that satisfies all four hard requirements — per-customer ordering, 7-day replay, team size, existing infrastructure — without adding a new system to operate. The throughput is two orders of magnitude below what Postgres comfortably handles, and the replay requirement, which rules out SQS FIFO as-is, is the strongest constraint in the list.

### Consequences

- Consumers poll with `SKIP LOCKED` and must be idempotent (dedupe on event id).
- The events table is partitioned monthly; a job deletes rows older than 7 days once replay consumers have passed them.
- Delivery latency target is ~100 ms p99 under normal load. If a consumer later needs lower latency, we add `LISTEN`/`NOTIFY` as a wake-up on the same table — no protocol change.
- This is a queue, not a log: there is no shared consumer-group offset store, so each consumer tracks its own high-water mark in a small `consumer_cursors` table.
- Monitoring: table depth, per-consumer lag (max produced seq minus max consumed seq), and poll error rate.

### What would change the decision

- Sustained throughput above ~1,000 events/sec, or many independent consumer types each needing its own replay position and retention: move to MSK Kafka, partitioned by customer id with 7-day retention.
- A hard sub-50 ms delivery-latency SLA: Kafka, or Postgres plus `LISTEN`/`NOTIFY` with a dedicated publisher.
- Cross-region replication of the event stream: Kafka.
- If a second service must consume the same stream with different durability needs, re-evaluate SQS FIFO plus an S3 archive, since the fan-out cost of Postgres polling grows with the number of consumers.

## A2
# Design: multi-tenant document collaboration service

### Assumptions

1. SaaS product; the tenant is an organisation, and every user belongs to exactly one organisation.
2. Clients are web and mobile apps speaking REST/JSON over HTTPS; no custom binary protocol.
3. Documents are block-based rich text (an ordered list of typed content blocks) with binary attachments; a document is at most 10 MB.
4. Real-time collaboration: up to about 20 concurrent editors per document; eventual consistency is acceptable and conflicts resolve automatically (no user-visible merge dialogs).
5. Primary store is Postgres; binary attachments live in S3.
6. Authentication is delegated to an existing identity provider; the public API uses OAuth 2.0 bearer tokens.
7. Scale target: 10,000 organisations, 1M users, 1M documents, 500 concurrent editors, p95 API latency under 300 ms.
8. Single-region deployment initially; TLS in transit, KMS encryption at rest.
9. Organisations have per-organisation quotas on document count and storage.
10. Deletion is soft, with a 30-day recovery window, then hard delete including S3 objects.

### Tenancy isolation strategy

Shared schema, shared tables, with `org_id` on every tenant-owned row. Isolation is enforced at two layers. First, Postgres row-level security policies make `org_id = current_setting('app.org_id')` a hard filter on every tenant table: even a buggy query cannot read across tenants, and the application sets the GUC from the verified token at connection time. Second, the application service layer re-checks ACLs for each operation (RLS answers "is this row in my tenant?"; ACLs answer "may this user do this to this row?"). All tenant rows carry `org_id` and are indexed with it as the leading column. Connection pooling pins the GUC per connection and resets it between uses. Cross-tenant data (nothing in this design) would require a separate schema. This buys a single deployment for all tenants with a database-level backstop against the most dangerous class of bug: a missing `WHERE org_id = ...`.

### Document storage

- `documents(id, org_id, title, root_folder_id, created_by, created_at, updated_at, deleted_at, version)` — one row per document; `version` is a monotonically increasing revision counter bumped per committed change-set.
- `blocks(id, document_id, org_id, block_id, parent_block_id, position, content jsonb, created_at, deleted_at)` — the document body. `block_id` is a client-generated UUID that is stable across the document's life, so edits reference blocks by identity, not array index. `position` is a fractional rank (64-bit floating fraction) giving O(1) inserts; a periodic rebalance keeps ranks healthy.
- `attachments(id, document_id, org_id, s3_key, filename, size, content_type, uploaded_by, created_at)`.
- `document_snapshots(id, document_id, org_id, version, crdt_state bytea, created_at)` — a snapshot every 500 updates and on every 24 h of inactivity; snapshots bound the replay needed to reconstruct a document and power the version history UI.
- The authoritative live state is a CRDT document (see below) stored as a compressed binary in `documents.crdt_state`, updated transactionally with `version`.

The write path is one short transaction: merge the incoming delta into the CRDT state in memory, then `UPDATE documents SET crdt_state = $1, version = version + 1 WHERE id = $2 AND version = $3`. The optimistic version check turns a lost write into a `409` that the client resolves by re-merging against the new state. Block rows are updated in the same transaction for read-path convenience, so a plain `GET` never has to decode a CRDT. Snapshots are written asynchronously by a background job that reads the persisted state, never on the write path, so snapshot cost never affects editor latency.

### Concurrent editing model

Editing is block-granular CRDT (Yjs/Automerge-style). Each editing session: the client opens a WebSocket to the collaboration endpoint, receives the current CRDT state (or a snapshot plus deltas), and then exchanges updates. The server merges updates into the document's CRDT — CRDT merge is commutative, so concurrent edits from any number of clients converge without a central arbiter — persists the merged state, and fans out the updates to the other sessions. Because blocks are the unit of edit, most conflicts are local: two people editing different blocks never interact; two people editing the same block merge at character level inside the block's own CRDT. Deletes are tombstoned (soft) so a late-arriving edit on a deleted block is a no-op. Offline edits work because CRDT updates are self-describing; on reconnect the client sends its pending updates and the server merges them. The REST API remains the source of truth for non-collaborative access: reads return the rendered block list from the persisted state, and non-collaborative writes (e.g., mobile offline sync) submit CRDT deltas through the same merge path, so there is one code path for all mutations.

Sessions are ephemeral and stateless on the server: the collaboration worker holds no per-session memory beyond the open socket, so a worker crash costs nothing — the client reconnects, re-fetches state, and replays its pending updates. The merge step is the only place document state changes, and it runs one delta at a time per document, which keeps the critical section short. A document is pinned to one worker process, and documents are load-balanced across workers by hash, so 500 concurrent editors spread over many documents is far from the per-document ceiling; a single document with 20 editors is the worst case, and it is bounded by the merge throughput of one process.

### Permissions

Two levels. Organisation level: `owner`, `admin`, `member`. `owner`/`admin` manage members, SSO, billing, and can access any document; `member` can only access documents explicitly shared with them (or with a group they belong to). Document level: each document has an ACL of entries `(principal, role)` where principal is a user, a group, or `org:all`, and role is `editor`, `commenter`, or `viewer`. The document creator is `owner` of the document (can delete, manage ACL, restore). Sharing is additive: a user's effective role is the maximum of the roles granted across all matching principals. Public links are a special principal (`public`) with `viewer` or `commenter`, an optional password, and an expiry. Enforcement: RLS for the tenant boundary, then an ACL check in the service layer for the operation (read needs viewer+, write needs editor+, ACL changes need owner). All ACL changes are written to an audit log (`org_id`, actor, target, action, timestamp) that is append-only.

Revocation is immediate: removing an ACL entry invalidates the affected user's cached authorization, and a session that is mid-write is checked against the ACL again at commit time, so a revoked editor's in-flight edits are rejected. Public-link secrets are stored hashed, and link expiry is enforced at the edge, not just in the application. The audit log also records every access made through a public link, which is the data a customer's security team will ask for after an incident.

### Public REST API

Base URL `/v1`, JSON, bearer auth, cursor pagination (`?cursor=`, `next_cursor` in responses), RFC 7807 `application/problem+json` errors, and `Idempotency-Key` headers on all `POST`s.

Documents:

- `GET /documents?folder_id=&cursor=` — list documents the caller can see.
- `POST /documents {title, folder_id}` — create; returns the document with its `blocks` empty.
- `GET /documents/{id}` — metadata plus rendered blocks.
- `PATCH /documents/{id} {title?, folder_id?}` — rename / move.
- `DELETE /documents/{id}` — soft delete (owner role).
- `GET /documents/{id}/blocks` — current block list.
- `POST /documents/{id}/updates {delta}` — submit a CRDT delta (the non-collaborative write path).
- `GET /documents/{id}/versions` and `POST /documents/{id}/restore {version}` — history and restore (owner).

Shares:

- `GET /documents/{id}/shares` — list ACL entries.
- `POST /documents/{id}/shares {principal: {type: "user"|"group"|"public", id?}, role, password?, expires_at?}` — grant.
- `PATCH /documents/{id}/shares/{share_id} {role?, expires_at?}` — change.
- `DELETE /documents/{id}/shares/{share_id}` — revoke.

Example:

```
POST /v1/documents/d_9f3/shares
{"principal": {"type": "user", "id": "u_77"}, "role": "editor"}

201 Created
{"id": "sh_12", "document_id": "d_9f3", "principal": {"type": "user", "id": "u_77"},
 "role": "editor", "granted_by": "u_5", "created_at": "2026-02-18T10:00:00Z"}
```

Errors use standard problem types: `404 document_not_found`, `403 forbidden` (with a `required_role` detail), `409 conflict` for stale-version writes, `422 quota_exceeded` when an org limit is hit.

Real-time collaboration uses a WebSocket endpoint (`/v1/documents/{id}/collab`) with the same bearer authentication; the REST surface above is what the public API exposes, and it is the surface the mobile client and third-party integrations use. All endpoints are versioned under `/v1`; breaking changes get a new major version with at least six months of dual support. Rate limits are per token (default 600 requests/minute, burst 100), reported via `X-RateLimit-*` headers and a `429` with `Retry-After`. Bulk operations (export, restore) are asynchronous: the `POST` returns `202` with a job id, and `GET /v1/jobs/{id}` reports progress.

## A3
The design has the right shape (event-driven fan-out, ledger as a subscriber) but four things would change:

1. **Close the event-loss window with a transactional outbox.** As described, the payment row is committed and the SNS publish happens afterwards, outside the transaction. A crash in that gap loses the event permanently: the ledger silently misses rows and nothing can detect it. Write the `PaymentCreated` event into an `outbox` table in the *same* database transaction as the payment, and have a relay (polling or CDC) publish to SNS and mark the row published. This makes "payment committed" and "event durably recorded" one atomic step.

2. **Fix the retry story: the DLQ is on the SQS side, not SNS.** SNS itself does not retry for a consumer; each subscriber must be an SQS queue (SNS → SQS) to get visibility timeouts, redrive, and a dead-letter queue. "Retry from the SNS DLQ" should be "retry from the ledger queue's DLQ", and that needs alerting, a replay tool, and the knowledge that DLQ replay is unordered.

3. **Handle ordering and duplicates explicitly.** SNS gives no ordering guarantee, so ledger entries can arrive out of order. Include a per-payment (and per-ledger-account) sequence number in the event; the ledger writer applies idempotently (unique constraint on the payment reference) and detects gaps rather than assuming arrival order. Delivery is at-least-once in any case, so idempotency is mandatory, not optional.

4. **Add reconciliation as the safety net.** A scheduled job that compares the payments table against ledger balances (per payment and in aggregate) and alerts on drift. Even with the outbox, this is the mechanism that *proves* the pipeline is lossless; without it, a silent loss is only found by an accountant.

On the SNS-vs-SQS rationale: fan-out is a legitimate reason to keep SNS, and the per-subscriber SQS design above preserves it. But if only the ledger consumes today, a plain SQS queue is simpler and SNS can be introduced when the second consumer actually appears.

Recommended shape: payment service (outbox) → relay → SNS topic → per-consumer SQS (ledger queue + DLQ) → idempotent, sequence-checking ledger writer, plus reconciliation.

## P1
Two engineers (E1, E2), 4 weeks = 40 engineer-days. Estimates in engineer-days (ed).

| # | Ticket | Est. | Dependencies |
|---|--------|------|--------------|
| T1 | Spike: pick provider matrix (Okta, Azure AD, Google + generic SAML/OIDC); stand up Keycloak as test IdP | 3 | — |
| T2 | Data model: `org_sso_config` (provider, issuer/metadata URL, client id/secret in KMS, attribute mapping, `enforce_sso` flag), `user_identities` (external_id, provider); migration | 4 | — |
| T3 | OIDC integration: authorization-code + PKCE, login callback, token validation | 4 | T1, T2 |
| T4 | SAML integration: metadata fetch/validate, SP-initiated flow, ACS endpoint, assertion mapping | 5 | T1, T2 |
| T5 | Account linking: match on verified email; manual link fallback; anti-takeover checks (don't merge accounts on unverified email) | 3 | T2 |
| T6 | SSO-only enforcement: block password login for `enforce_sso` orgs at the auth layer; keep password as fallback when SSO is off | 2 | T2, T3 |
| T7 | Settings UI: per-org SSO config form, "test connection", status indicator, enforce toggle with confirmation | 4 | T2, T3 |
| T8 | Security hardening: secret storage review, audit logging of SSO events, session/CSRF review | 2 | T3, T4 |
| T9 | E2E tests against Keycloak matrix, admin docs, staged rollout plan | 3 | T3–T8 |

Total: 30 ed, leaving ~10 ed of buffer for review, fixes, and the unknowns of real IdP quirks.

Schedule:
- **Week 1:** T1 (E1), T2 (E2). Milestone: schema merged, test IdP running.
- **Week 2:** T3 (E1), T5 (E2). Milestone: OIDC login works end-to-end.
- **Week 3:** T4 (E1), T6 + T7 (E2). Milestone: SAML works; settings UI usable; enforcement on.
- **Week 4:** T8 (E1), T9 (both). Ship at end of week 4.

Critical path: T1 → T4 → T8 → T9 (SAML is the long pole). Risks: SAML IdP variance (mitigated by the Keycloak matrix in T1), KMS approval for secret storage (start in week 1), and scope creep on provider support — ship with the four providers above and treat the rest as follow-ups.

## P2
Calendar: today is Monday the 4th (week 4 starts); the deadline is Friday the 22nd (week 6 ends). With the 22nd a Friday, the last Sunday of the month is **Sunday the 17th** — the only possible maintenance window, and it falls at the start of week 6.

Key insight: the write-lock constraint applies to **production** only. Everything else can proceed against a migrated dev/staging database right now.

Revised plan (two engineers, E1/E2):

- **Week 4 (4th–8th):** E1 builds the API layer (B) against the migrated staging DB — the migration runs freely there. E2 finalizes the production migration runbook (exact 20-minute script, rollback plan, verification queries) and starts client integration (C) scaffolding against the agreed API contract (stubs/mocks), so C is not idle.
- **Sunday the 17th:** run the production migration in the approved window. Pre-staged so the window is pure execution: script tested on staging, rollback rehearsed, on-call assigned.
- **Week 5 (11th–15th):** E1 finishes B and deploys it to staging (staging has been on the new schema since week 4, so this is a deploy, not a rebuild). E2 continues C against staging, where the real API is available.
- **Week 6 (18th–22nd):** C completes, integration testing, UAT; production release of B and C by **Friday the 22nd**. Deadline met.

Contingency: if the 17th window is missed, the deadline is unachievable (the next month-end Sunday is ~5 weeks away) — so the plan treats the window as a hard gate: the runbook, the approval, and the on-call are all locked in during week 4, and any slip in B is absorbed by E2's parallel C work, not by the window.

## P3
Assumptions: (a) B, C, and D can each be split across multiple engineers; (b) A is single-owner and cannot be parallelized (as stated); (c) E is vendor-driven — the 1 engineer-week is coordination effort spread over the vendor's 2-week lead time, and the lead time starts only when the review request (which needs D complete) is submitted.

Week-by-week (3 engineers: E1, E2, E3):

| Week | E1 | E2 | E3 | Notes |
|------|----|----|----|-------|
| 1 | A | — | — | A starts; only A is unblocked |
| 2 | A | — | — | |
| 3 | A | — | — | A complete end of week 3 |
| 4 | B (½) | B (½) | C (½) | B and C unblock; B takes 2 engineers, C takes 1 |
| 5 | B (½) | B (½) | C (½) | B done end of week 5 (4 ed total); C done (2 ed) |
| 6 | D (⅓) | D (⅓) | D (⅓) | D done end of week 6 (3 ed); submit vendor review request |
| 7 | E (coordination) | — | — | Vendor lead time running |
| 8 | E (coordination) | — | — | Security review complete; deliver |

**Critical path:** A → B → D → E = 3 + 2 + 1 + 2 = **8 weeks**.

**Delivery date: end of week 8 — two weeks past the six-week deadline.**

The deadline is infeasible as stated: even with unlimited engineers on B and D, the chain A(3) + B(≥4/3) + D(≥3/3) + E lead(2) ≥ 7.3 weeks. To actually hit week 6, the only lever is the vendor lead time: submit the security review request *before* D completes (e.g., at the end of week 4 against the design and an early SDK build, if the vendor accepts a preliminary submission). That overlaps the 2-week lead with D's week 6, and delivery lands at the end of week 6. If the vendor will not review an incomplete deliverable, negotiate the deadline to week 8.
