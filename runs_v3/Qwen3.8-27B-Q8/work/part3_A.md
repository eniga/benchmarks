## A1
# ADR: Offline-first synchronisation for field-technician job records

**Status:** Accepted
**Deciders:** Mobile team (2 engineers), Backend (1 engineer)

### Context

We are building an offline-first mobile app for field technicians who record job data. Each job record is owned by exactly one technician; the backend enforces single ownership at assignment time, so two technicians never edit the same record. A technician may, however, use two devices (phone and tablet) and edit the same record from both while offline. Devices are offline for up to 72 hours. A record is a flat set of about 40 fields (text, numbers, enums, timestamps, and a list of photo references); photos upload separately to object storage.

A regulator requirement shapes the design: every field change must be attributable to a named person with a server-assigned timestamp, and the stored change history must be human-readable during an audit without any tooling. We have three engineers (two mobile, one backend) and no dedicated platform team. The backend is Postgres 16 behind a REST API.

The central question is how to reconcile edits that diverge while offline and then meet again at the server.

### Decision

We will use **server-authoritative, per-field last-write-wins (LWW), backed by an append-only change log**.

Each field edit made on a device is captured locally as a change entry: `{record_id, field, new_value, technician_id, client_edit_ts, client_device, client_op_id}`. `client_op_id` is a client-generated UUID that makes re-sync idempotent. Entries are stored in a local SQLite queue and shipped to the server when connectivity returns. On receipt the server appends the entry to a Postgres change-log table (adding a server-assigned `server_ts`) and updates the record's current field value using per-field LWW: the entry with the greatest `client_edit_ts` (tie-broken by `server_ts`) wins. The change log is append-only and never rewritten, so the full history is always present. The current value of each field is a projection of the log (the winning entry); the log itself is the source of truth for the audit.

### Consequences

Positive:
- **Meets the regulator requirement directly.** The change log is a flat, human-readable table: one row per field change, with the technician's name, the server-assigned timestamp, the field, and the old/new values. An auditor can read it in `psql` or a plain `SELECT` with no tooling.
- **Simple and small-team-friendly.** Per-field LWW is a few lines of SQL per field; there is no merge library to learn, operate, or debug. Two mobile engineers and one backend engineer can own it.
- **Matches the real conflict profile.** Because a record has a single owner, the only conflicts are one person editing the same field on two devices. Per-field LWW resolves those sensibly (the person's most recent edit wins) without bothering them.
- **Idempotent and resumable.** `client_op_id` makes retransmission safe, which matters over flaky field connectivity and 72-hour outages.

Negative / risks:
- **Clock skew between the two devices.** LWW relies on `client_edit_ts`. If the phone and tablet clocks differ, the "most recent" edit may not be the one that actually happened last. Mitigation: use the server-receipt `server_ts` as the tie-breaker; in practice the same person editing one field on two devices within a short window is a rare, low-stakes case.
- **Loser values are not current.** LWW keeps the winner as the current value; the losing edit is still preserved in the append-only log (so nothing is destroyed and the audit is complete), even though it is not the live value.
- **Log growth.** The change log grows with edits. For ~40 fields and a 72-hour window this is small, but we will partition the log by record and retain it for the regulator's retention period.

### Alternatives considered

**CRDT library.** CRDTs give automatic convergence for concurrent multi-writer edits. That is overkill here: there is a single writer per record and a server that can assign authoritative timestamps, so we do not need conflict-free merge semantics. A CRDT would add a dependency to learn and operate, non-obvious merge state that is *not* human-readable (working against the audit requirement), and storage overhead, for no benefit a three-person team can exploit. Rejected.

**Record-level optimistic concurrency with manual conflict resolution.** This stamps the whole record with a version and forces the user to resolve conflicts when two devices diverge. It is the wrong granularity (a conflict on one field blocks all 40), produces poor UX (the technician must guess which of their own two devices is "right"), and conflicts would be common given two devices and 72-hour outages. It also does not naturally produce the per-field, per-person, timestamped history the regulator wants. Rejected.

### What would change the decision

- If records could be edited by **multiple technicians concurrently**, per-field LWW would silently discard one person's work and we would move to CRDTs or field-level vector clocks with explicit conflict surfacing.
- If the regulator required **preserving every divergent value as equally valid** (not just the winner), we would need a richer merge model than LWW.
- If device clocks could not be trusted at all and edit order became legally significant, we would introduce server-issued sequence numbers per record (a lightweight logical clock) instead of relying on `client_edit_ts`.
- If the team grew a platform group and the conflict profile expanded, revisiting CRDTs would become reasonable.

## A2
# Write path for a three-region order service

### Assumptions

1. The public API is globally reachable (anycast/GeoDNS) and, under normal operation, routes a customer's requests to their **home region's** edge. A customer has exactly one home region.
2. "An order, once accepted, must never be lost" means: (a) the API returns success for an order **only after** it is durably persisted (WAL fsync / local quorum) in a region, and (b) every accepted order is **asynchronously replicated** to at least one other region, so a single-region failure does not lose accepted orders. The recovery point objective (RPO) for a full home-region loss is the replication lag, targeted at sub-second.
3. The 80 ms p99 write budget applies to the **normal path**: the request lands in the customer's home region and is durably committed there. No synchronous cross-region round trip is on the write path, because every inter-region RTT (90–220 ms) already exceeds the budget.
4. Order **status** reads are strongly consistent when served from the home region (the source of truth) and eventually consistent when served from a replica; replica reads are flagged as such.
5. Each customer's orders are written by **one region at a time** (the home region, or a designated failover region while the home is isolated). This single-writer property is enforced by a per-customer lease and is what prevents split-brain conflicts.
6. Inter-region replication is **asynchronous and log-based**: each region appends committed orders to a local log and ships that log to the other two regions.
7. Re-homing a customer to a different region is out of scope (a rare, offline migration).

I hold to these throughout. Where I later relax assumption 2's "never lost" to a sub-second RPO, I flag it explicitly.

### Data partitioning

Orders are partitioned by customer, and each customer belongs to one home region. The home region is the **source of truth** for that customer's orders and holds the primary (writable) copy. The other two regions hold **read replicas** of that customer's data, maintained by the async log. Partitioning by customer (not by order) means all of a customer's orders live together in one region, so a customer's write and read path is local to one region in the normal case, and failover is a per-customer (or per-region) unit rather than a per-order one. Within the home region, the primary store is a durable local database (Postgres) fronted by a write-ahead log; the WAL is the durability boundary.

### The write path (normal case)

1. A customer's `POST /orders` arrives at the home region's API edge (routed there by GeoDNS, assumption 1).
2. The edge validates the payload and checks the client-supplied `Idempotency-Key`. If the key was already used with the same payload, it returns the original order (no duplicate). This is what makes client retries safe and is load-bearing for the "never lost" guarantee.
3. The edge appends the order to the region's WAL and **fsyncs**. This durable local commit is the point at which the order is "accepted." A local fsync is single-digit milliseconds, far inside the 80 ms budget.
4. The edge returns `201 Created` with the `order_id` and initial status `accepted`.
5. In the background, the order is applied to the primary Postgres and shipped on the replication log to the other two regions.

The entire acknowledged path is local to one region: validate, idempotency check, WAL fsync, respond. There is no cross-region hop, which is the only way to meet 80 ms given the 90–220 ms inter-region RTTs.

### How reads are served

`GET /orders/{id}` is served from the **home region** by default, giving a strongly consistent status. Because a customer's data is home-region-local, this is a local read in the normal case. If a client is physically in another region and latency matters, the API can serve from the **local replica** instead; that read is eventually consistent and the response carries `consistent: false` so callers can decide whether to re-read from the home region. Status values are monotonic (an order never moves backwards in its lifecycle), which keeps replica reads safe to display.

### Failure behaviour when a region is isolated

A region can be isolated by a full outage or a network partition.

- **A non-home region is isolated:** no effect on writes (each customer writes to their own home region). Reads that would have used that region's replica fail over to the home region (a cross-region read, which has no 80 ms budget) or to the other replica.

- **A home region is isolated:** the customers whose home is that region are the affected ones. GeoDNS failover (assumption 1) routes their requests to a **secondary region's edge**. That edge:
  1. Takes over the customer's **writer lease** (assumption 5) once the home region's lease expires, so exactly one region writes for that customer.
  2. Durably appends the order to the secondary's own WAL and returns `201` once it is queued — the order is now durably stored in the secondary region, so it is not lost even though the home is down.
  3. Processes the order in the secondary's store and continues to replicate it onward.
  4. When the home region recovers, the secondary ships the orders it accepted during the outage back to the home region. Because only one region wrote for the customer at any time (the lease), the two logs never contain concurrent writes to the same order; they are merged in sequence order and the home region resumes as source of truth.

  This preserves both "never lost" (every accepted order is durably queued before the ack) and availability (the customer keeps ordering during the outage), at the cost of a temporary relocation of the customer's home that is reconciled on recovery.

- **Split brain** is prevented by the per-customer lease: the home region and a secondary can never both hold the write lease for the same customer, so there is no window in which two regions both accept writes for one customer.

### Public API contract

`POST /orders`
- Request: `customer_id`, order payload, and an `Idempotency-Key` header (required).
- `201 Created`: `{ order_id, status: "accepted", created_at }`. Returned only after durable local commit.
- `200` (idempotent replay): the original order, when the same key+payload is resent.
- `400` invalid payload; `409` idempotency key reused with a different payload; `429` rate limited; `503` the home region and its failover queue are both unavailable (the order was **not** accepted, so nothing is lost).

`GET /orders/{order_id}`
- `200`: `{ order_id, status, updated_at, consistent }`. `status` is one of `accepted → confirmed → shipped → delivered` or `cancelled`. `consistent` is `true` when served from the home region, `false` when served from a replica.

Guarantees: an order that returns `201` is durably stored and will not be lost; status is monotonic; retries with the same idempotency key never create a duplicate.

### Trade-offs

The design trades a sub-second RPO (assumption 2) for the 80 ms write budget: true RPO=0 would require synchronous cross-region replication, which is impossible at 90–220 ms RTT. In exchange, a single-region failure loses nothing (the replica has the data), and only a simultaneous loss of the home region **and** its not-yet-replicated tail — bounded by the replication lag — could lose orders. If the business later requires strict RPO=0, the options are to raise the write-latency budget, to accept synchronous replication to the nearest region only (Frankfurt↔Virginia at 90 ms still exceeds 80 ms, so even that fails), or to co-own each customer's writes across two regions — each of which is a product decision, not an engineering one.

## A3
The overall shape — cache-aside reads with invalidate-on-write — is a sound, standard pattern, and deleting (rather than updating) the key on write is the right instinct. But the stated rationale is wrong in an important way, and several omissions would bite in production. Here is what I would change and why.

**1. "Delete so we never disagree" is false.** Delete-on-write does not guarantee the cache and Postgres agree. The classic race:
- Reader A misses the key and reads the old row V_old from Postgres.
- Writer B commits V_new to Postgres, then deletes the key.
- Reader A (slower) now writes V_old into Redis — *after* the delete.
Redis now holds V_old while Postgres holds V_new, and it stays wrong until the 10-minute TTL expires. Deleting shrinks the stale window compared with updating (an update could be clobbered by a slow reader's stale write), but it does not eliminate it. I would state the real guarantee: the cache is *eventually* consistent, bounded by the TTL, and a short stale window after a write is possible.

**2. Bound and monitor staleness; don't call the TTL a "backstop."** Ten minutes of a stale price or stock level in a product catalogue is a real correctness and commercial risk, not a backstop. I would (a) set the TTL to the product's actual acceptable-staleness (often much shorter for price/stock), (b) add TTL jitter so keys do not all expire together and stampede Postgres in a wave, and (c) treat a stale read after a write as an expected, measured SLA rather than an accident.

**3. Fire-and-forget deletes are unsafe.** If the delete fails (Redis blip, network), the stale key lives for the full TTL with no retry and no signal. I would make the delete retried (a few attempts, then a fallback to overwrite-with-fresh-value or a short TTL) and alert on delete failures. Better still, on write, *set* the key to the fresh value (or a versioned value) in addition to or instead of a blind delete, so a failed delete still leaves a correct value.

**4. Handle the thundering herd.** On a miss or right after a delete, every concurrent reader for a hot product misses and hammers Postgres at once. Popular catalogue items are exactly the hot keys. I would add single-flight / request coalescing so only one loader populates a key while others wait, plus negative caching (a short-TTL "not found" marker) to stop cache penetration from invalid IDs.

**5. Invalidate derived caches, not just the row key.** A write to a product also invalidates anything that embeds it — category listings, search results, "related items," aggregated counts. Deleting only the single row key leaves those stale. I would enumerate the derived keys per product (or use tag/version-based invalidation) and invalidate them on write.

**6. Make the consistency model explicit and version the value.** Store a version or generation with each cached value (e.g., the Postgres row's `updated_at` or a sequence). On write, bump it. This lets a reader detect that a value it is about to write is already stale and discard it, which closes much of the race in point 1, and it makes monitoring (how stale is the cache?) trivial.

**7. Plan for Redis being empty or down.** A Redis restart empties the cache and the next hot reads stampede Postgres. I would ensure Redis is highly available (replication plus failover), warm or gracefully rate-limit the cache on cold start, and define behaviour when Redis is unavailable (fail open to Postgres with load protection, or fail the read explicitly — a product decision).

**8. Keep the cached value lean and the serializer stable.** Cache only the fields the read path needs, and version the serialization format so a schema change does not silently serve malformed values from old entries.

In short: keep cache-aside plus invalidate-on-write, but (a) correct the "never disagree" claim to "eventually consistent, bounded by TTL," (b) shorten and jitter the TTL to the real staleness budget, (c) make deletes retried and monitored (or write-through the fresh value), (d) add single-flight and negative caching, (e) invalidate derived keys, and (f) version cached values and plan for Redis failure. The pattern is fine; the assumptions around it are what need fixing.
