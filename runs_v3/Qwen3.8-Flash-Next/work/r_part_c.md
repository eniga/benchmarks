## A1

### ADR-014: Data synchronisation strategy for offline-first field technician app

**Status:** proposed
**Date:** as of sprint 41 planning
**Deciders:** mobile leads (2), backend lead (1)

### Context

Field technicians create and edit job records on Android/iOS devices that may be offline for up to 72 hours. Each record is owned by exactly one technician; the backend enforces single ownership at assignment time, so two *technicians* never edit the same record. One technician may carry a phone and a tablet and edit the same record on both while offline — that is the only genuine concurrent-editing scenario. A record is ~40 flat fields (text, numbers, enums, timestamps) plus photo references; photos already upload out of band. Regulators require that every field change be attributable to a named person with a **server-assigned** timestamp, and that the stored history be readable by an auditor with no special tooling. Team: three engineers, no platform team. Backend is Postgres 16 behind REST.

### Options considered

**(1) CRDT library (Automerge/Yjs-class).** Merges any replica set deterministically, offline-safe. Costs: an unfamiliar dependency in a mobile-first team; document-shaped CRDTs in Swift/Kotlin are immature relative to JS; the merge document for a 40-field record is a blob Postgres must store opaquely, which conflicts with the audit requirement — a CRDT history is human-readable only through the library, and "server-assigned timestamp" fits poorly with values that converge only when replicas meet. Library-upgrade and cross-version compatibility risk over a 72-hour offline population lands entirely on us.

**(2) Server-authoritative per-field last-write-wins + append-only change log.** Client sends its pending field-level edits; server appends each edit to a `change_log` (append-only, one row per field change: record id, field, old value, new value, device, technician, `received_at timestamptz DEFAULT now()`); the materialised record is updated field-by-field with the server's arrival order deciding the winner.

**(3) Record-level optimistic concurrency + manual conflict resolution.** Client sends the whole record with a version; on mismatch a human resolves. With a 72-hour offline window and no connectivity, "manual" resolution means a blocked technician who cannot close a job, or a backlog for the office. It also yields `old/new` record snapshots rather than field-level attribution, weakening the audit story.

### Decision

**Option 2: server-authoritative last-write-wins per field, with an append-only change log as the single source of audit truth.**

Rationale:
- The invariants we actually have are narrow: one owning technician, one backend that decides order. LWW at *field* granularity preserves everything either device wrote; a phone/tablet conflict only arises when the same field is edited on both, and the loser is preserved in the log — nothing is silently destroyed, only superseded.
- It is the only option where the regulator's requirement is a plain Postgres table: `SELECT field, old_value, new_value, technician, server_time FROM change_log WHERE record_id = ? ORDER BY server_time` is the audit artefact, readable in `psql`, indexable, and exportable to the audit PDF we generate.
- Server-assigned timestamps fall out naturally: the arrival order *is* the conflict resolution order, so attribution and ordering come from one authority.
- Implementation surface is small: a `pending_edits` outbox table on-device, a bulk `POST /records/{id}/edits` endpoint, a trigger or service-layer append to `change_log`, That fits three engineers.

Deliberately excluded: field-level *semantic* merges (e.g. numeric summation), which would be the strongest argument for a CRDT. Photo reference lists, the only collection field, become append-only sets (union by id, tombstone for deletes); no CRDT needed.

### Consequences

**Positive.** Deterministic, explainable conflict resolution ("the server saw it later"). Audit trail is a first-class table, not a side effect of a library. Offline edits never block the technician. Client and server can be shipped independently; a client that never upgrades still converges because the server owns resolution.

**Negative, accepted.** Concurrent same-field edits produce a winner and a loser; the loser is not applied to the record, so we must (a) surface superseded edits in the app's record history view so the technician can see and re-apply them, and (b) log the supersede event so the auditor can follow why a change did not stick. LWW is not "correct" for collaborative semantics; we accept it because the ownership model makes collaboration rare and same-field simultaneous edits rarer. Device clock skew is irrelevant to ordering: `client_observed_at` is stored as a hint only. Photo-reference tombstones add one column and one rule.

**Follow-on work.** On-device outbox retention limits; a nightly job that rebuilds the materialised record from the change log and alerts on drift (protects the log-as-truth invariant); an explicit "assignment transfer" flow, since single ownership is the load-bearing assumption.

### What would change the decision

1. If two technicians can ever co-edit one record (e.g. a "assist me on this job" feature), single-owner ordering breaks and a CRDT or operational-transform approach becomes worth its cost.
2. If field semantics become merge-able (quantities summed, checklists co-authored), per-field LWW loses real work; revisit CRDTs then, per-field, not per-record.
3. If auditors accept a tool-mediated history (a viewer we own), the opacity objection to CRDTs disappears and option 1 becomes viable.
4. If offline windows grow to weeks with heavy editing, log replay and reconciliation costs dominate; we would then want snapshot+delta compaction inside the log, or document-shaped state.
5. If the regulator requires *the client's* claimed time rather than server arrival time, we need vector clocks or client-signed edit sequences, which changes the model materially.

## A2

Assumptions (numbered; changes are called out where they occur):

1. "p99 80 ms end-to-end at the edge" means from the first byte of the request arriving at our edge to the response byte leaving it, for order creation and status reads.
2. Orders are created by an authenticated customer (or a session bound to one); `customer_id` is always known before routing.
3. A customer's home region is fixed at account creation and stored in a cheap, cached directory; changing it is a rare, controlled migration.
4. Within a region, cross-AZ round trip is ≤ 5 ms and we may place 3 replicas in 3 AZs.
5. Writes only need to survive the loss of any single AZ in the home region to satisfy "an accepted order is never lost"; loss of an entire region is a disaster scenario, handled by a recovery procedure with an explicit, documented RPO (see §4 and assumption 13).
6. Cross-region replication may be asynchronous; nothing in the API contract implies cross-region read-after-write for a brand-new order.
7. Order status transitions are driven only by our services, never by third parties writing the same partition concurrently.
8. Read volume ≈ 20× write volume; status reads are dominated by "the order I just placed".
9. Postgres 16 (assumed, matching our stack) per region, partitioned by `customer_id`.
10. Clients are retry-safe: they send an idempotency key and tolerate a `202` with a non-final status.
11. No requirement for global ordering of orders *across* customers; ordering guarantees are per order/per customer.
12. Edge = our CDN/anycast front with TLS termination and auth, co-located with a regional API tier.
13. (Introduced in §4.) Full-region loss may lose up to `T_rep` seconds of *not-yet-replicated* mutations for orders already acknowledged as accepted; we accept this only for acknowledged orders whose durable home-region quorum write is also destroyed, i.e. whole-region loss.

### 1. Data partitioning

`orders` is hash-partitioned by `customer_id` (Postgres declarative hash partitioning, 1024 logical buckets collapsed onto a small number of physical partitions), and each partition set has exactly one writable home region. A region owns the partitions of its resident customers; every other region holds read-only replicas of everything. This makes the vast majority of writes single-partition, single-region, and conflict-free — no multi-leader, no CRDT, no cross-region transaction.

Physical layout per region: a 3-AZ Postgres cluster with synchronous quorum commit (1 leader + 2 synchronous followers, or a consensus group with 5 voters if AZ-loss-without-quorum-loss must be tolerated) for the *order* tables; a separate append-only acceptance journal (WAL-shipped plus object-store shipping) for disaster recovery.

### 2. The write path (`POST /v1/orders`)

1. Edge terminates TLS, authenticates, reads `customer_id`, looks up home region (cached, TTL 60 s, signed).
2. Edge proxies to the **home region** API tier. For a Frankfurt-resident customer writing from Singapore, this costs one inter-region hop — see §6 for the budget consequence and the mitigation.
3. API computes the order id deterministically from `(customer_id, idempotency_key)` and issues `INSERT ... ON CONFLICT DO NOTHING` into `orders` (status `pending`) **plus** an `order_events` row (status transition `created`) in the same Postgres transaction. Single transaction = no "order exists but no event" state.
4. Postgres commits with synchronous quorum in 3 AZs. This is the point of no return: the order is now durable against any single AZ loss.
5. Response `201 Created` (or `409`/`200` on idempotent replay) carrying `order_id`, `status`, and `order_version`.
6. Asynchronously: logical decoding from the home region streams `order_events` to (a) the other two regions' read replicas, (b) the search/analytics projection, (c) the outbox for partner webhooks. Cross-region lag is exported as `replication_lag_seconds` and alerted at > 10 s.

There is no cross-region commit anywhere in the accepted path. That is the whole design decision: the latency budget makes synchronous inter-region agreement physically impossible (Frankfurt↔Virginia alone is 90 ms RTT > 80 ms budget), so durability is established regionally and replication is asynchronous.

### 3. Reads

- **Status of an order just created:** served by returning state in the write response; for subsequent reads, `GET /v1/orders/{id}` is served from the home region's leader for the first 5 minutes (bounded "recent write" window) so read-your-writes holds without any client token, then from any replica.
- **General status reads:** served from the *nearest* region's replica, with `ETag`/`order_version`. Clients that need monotonic reads pass `If-order-version` and get a `304`/refresh accordingly; we guarantee monotonic reads and reads-of-own-orders, not global freshness. `Cache-Control: private, max-age=0, must-revalidate` plus in-region Redis (TTL 1 s, jittered, invalidated on event) protects Postgres from status polling.
- **Cross-region reads during replication lag** may return a slightly older status; the response always carries `order_version` and `status_observed_at` so clients and support tooling can see exactly what they are looking at.

### 4. Failure behaviour

**Single AZ loss in home region:** quorum re-elects, writes continue, p99 rises briefly. No data loss (assumption 5).

**Home region degraded (high CPU/IO, no crash):** writes queue at the API layer with a bounded admission queue and shed load with `503 + Retry-After` rather than exceeding the budget; the client's idempotency key makes retrying safe.

**Cross-region link down:** unaffected for writes. Replicas in the other two regions go stale; their status reads serve stale data with `order_version` visible and a `degraded: true` header. Webhooks/search are delayed. When the link returns, logical replication resumes from the slot; the slot is bounded (`max_slot_wal_keep_size`) so a long break cannot fill home-region disk — a broken slot is rebuilt from a base backup plus journal replay.

**Home region isolated (split-brain):** the isolated region keeps serving its own customers only if it retains quorum; regions without quorum stop accepting writes and return `503 Retry-After`. We never auto-promote another region to writable for the same partitions: a fenced-off leader writing concurrently is exactly how "never lost" dies. Promotion is a manual, two-person, fenced procedure: (1) confirm the old region has no quorum and revoke its write fence via a consensus key stored in a *third* region's quorum (Singapore arbitrates for Frankfurt/Virginia pairs and vice versa), (2) promote a replica after replaying its log to the fence point, (3) open writes. **Assumption 13 (new):** promotion may discard up to `T_rep` seconds of acknowledged-but-unreplicated orders. Mitigation: the acceptance journal (every accepted order's canonical JSON, streamed to object storage cross-region with versioning, `T_journal ≈ 2 s`) means an order acknowledged as accepted is recoverable from the journal even if the whole region is destroyed; recovery replays the journal into the new leader and marks replays `needs_review` if any acknowledgement cannot be matched. This is the one place we change an assumption: durability against *whole-region* loss is provided by the journal, not by replication.

**Order-loss analysis:** an acknowledged order is lost only if (a) home quorum lost, (b) journal object for that order lost. Journal has cross-region versioning and object-lock, so loss requires correlated destruction of two regions plus journal — accepted residual risk, with monthly restore drills.

### 5. Public API contract

`POST /v1/orders` — headers `Idempotency-Key` (required, 24 h retention), `X-Customer-Region` (advisory only). Body validated → `201` with `order_id`, `status="pending"`, `order_version`; `200` on replay of a completed key; `409 idempotency_conflict` if the key is reused with a different body; `422` validation; `429`/`503` with `Retry-After` and `Idempotency-Key` preserved. **Rule for clients: if you do not get a response, retry with the same key; the effect is exactly-once per key.** `status` values: `pending` (durably accepted, not yet dispatched), `dispatched`, `confirmed`, `cancelled`, `failed_validation`; transitions are monotonic and each transition is an append-only `order_events` row. `GET /v1/orders/{id}` returns `status`, `order_version`, `status_observed_at`, ETag. `PATCH /v1/orders/{id}/status` is internal-only, requires an expected `order_version` (conditional update; `412` on mismatch) so status writes cannot interleave. All endpoints: no silent retries of non-idempotent operations, `Retry-After` always present on `503`, `Deprecation`/`Succeeded-By` headers for future version moves.

### 6. Latency budget

p99 at edge, same-region client (majority): auth 3 ms + route/dir lookup 1 ms + API handler 6 ms + home-region Postgres quorum commit 12 ms + response 3 ms ≈ **25 ms**, leaving ~55 ms of headroom for GC/queues/stragglers.

For a customer writing from the wrong side of the world (Singapore client, Frankfurt-resident customer): one extra inter-region RTT = 220 ms, which cannot meet 80 ms. **Consequence stated plainly: the budget holds for same-region-origin writes only.** Options, in order of preference: (a) classify p99 per origin-region and set a 300 ms budget for the 3% cross-hemisphere cohort; (b) `202 Accepted` fast-acknowledge against the *edge* journal (edge durable append + async forward) for a documented `pending_edge` state — this trades a weaker durability story for latency, so it is off by default and only enabled for clients that opt into `Prefer: respond=queued`.

### 7. Operations

SLOs: write p99 (per origin region), replication lag, journal shipping lag, idempotency replay rate, `503` rate, quorum elections. Every failover has a runbook plus a game-day test; the fence/promote path is unexercised by normal traffic, so it is tested quarterly against a replica in a scrubbed region.

## A3

It is a reasonable cache-aside sketch, but three of its sentences are load-bearing in a way the design does not survive.

**1. "Delete after the DB write" still loses to a concurrent reader.** Timeline: reader misses, `SELECT`s the old row → writer updates Postgres, deletes the key → reader writes the *old* row into Redis. The key now holds a stale value for the full 10-minute TTL. The delete is not a synchronisation point; it only clears what existed at the moment it ran. Fix: attach a monotonic version to cached values and to the invalidation, taken from the row (`xmax`, a `version` column, or a per-namespace generation counter bumped inside the write transaction). A cache writer may only store a value whose version is ≥ the last invalidation watermark for that key, checked with a Lua script / `WATCH`-`MULTI` compare-and-set. That turns the race into a no-op instead of a 10-minute lie.

**2. "Fire-and-forget" deletes are where most staleness will come from.** A dropped delete (timeout, Redis failover, `maxmemory` eviction of the connection, a deploy mid-loop) is silently indistinguishable from success. Do it transactionally instead: update the Postgres row and insert an `invalidation` outbox row in the *same* transaction; a worker drains the outbox with retries, a DLQ, and a metric for invalidation lag. Deletes are idempotent, so at-least-once is safe. If the volume makes a row per delete too expensive, keep the outbox per aggregate (bump a `generation` on the catalogue root and embed the generation in cache keys) — that also makes rolling deploys and "invalidate the whole catalogue" trivial.

**3. The TTL is not a backstop, it is the staleness window.** Today the failure mode is "wrong for up to 10 minutes"; that number should be chosen per data class (price vs. description vs. stock) rather than globally. Add jitter (±20%) so a fleet of keys does not expire in lockstep and stampede Postgres.

Other things I would change or add:

- **Stampede protection.** On a hot key (a popular product after expiry), N concurrent misses each run the same `SELECT`. Use single-flight/leader election per key in the app, or Redis `SET NX` lock with wait-and-reread, plus serve-stale-while-revalidate (store value + fetched_at; return stale and refresh in background) so a miss never puts full read load on Postgres.
- **Where reads read from.** If any reader hits a Postgres replica while the cache is cold, the replica's lag can be *written into* the cache and become authoritative for 10 minutes. Cache only from the primary, or record the replica's LSN and refuse to cache below the current watermark.
- **Redis failure mode.** When Redis degrades, every read becomes a Postgres read — the outage amplifies. Add a breaker with a small in-process cache (1–2 s) and a load-shedding policy, plus health-based routing so a slow Redis is failed out fast, not waited for.
- **Consistency promises in the API.** "Delete so the next read repopulates" means a client that writes then immediately reads may see the old value (its own write lost to replication or to a cache refill). For user-visible writes, either read-your-writes from the primary or return the new value/etag from the write call and let the client render it.
- **Consider write-through for low-churn, high-read rows.** If reads dominate writes by orders of magnitude and rows are small, updating the cache inside the write path (with the same version CAS) removes a whole class of misses and lets TTL be much longer. The stated reason for delete-not-update — never reconciling cache and DB — is right in spirit, but the version CAS gives the same peace of mind without the extra read burst.
- **Observability and tests.** Hit ratio, p99 for cache and DB path, invalidation lag histogram, key churn, and a `stale_reads_total` counter built from comparing cache version against row version in sampled requests. Plus an integration test that reproduces race #1 on the old design and passes on the new one.

Net change: keep cache-aside with deletes, but make invalidation **transactional and retried**, make cache writes **version-checked**, choose **TTLs per data class with jitter**, and add **stampede and Redis-failure handling**. The reasoning in the proposal ("delete, don't update; TTL as backstop") is fine as a philosophy and unsafe as an implementation.
