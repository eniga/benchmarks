# Answer key — lock_audit

## The three expected findings

| # | Function | Line | Mutation | Lock that should be held |
|---|----------|------|----------|--------------------------|
| 1 | `revoke_session` | 71 | `del self._sessions[sid]` | `_sessions_lock` |
| 2 | `attach_metadata` | 79 | `session.metadata[key] = value` | `_sessions_lock` |
| 3 | `record_error` | 114 | `self._stats["errors"] += 1` | `_stats_lock` |

Notes on each:

1. `revoke_session` — also does an unlocked *read* (`if sid not in self._sessions`)
   on line 69; a response that quotes only that read is quoting the wrong line.
   The `self._expiry.pop(sid, None)` on line 72 is a second unlocked mutation in
   the same function; quoting either mutation counts.
2. `attach_metadata` — the tempting wrong answer is "no lock needed, it only
   touches one session's dict". The module docstring states `_sessions_lock`
   covers the fields of any `Session` reachable from `_sessions`, and
   `rotate` mutates `session.sid` under that lock, so the contract is explicit.
3. `record_error` — the near-miss: the function *does* acquire `_stats_lock`,
   one line too late. Line 114 runs outside it. A response that clears this
   function because it "contains a `with self._stats_lock`" has failed.

## Correctly locked — must NOT be listed (false positives)

`create_session`, `touch_session`, `drop_expired`, `rotate`, `record_hit`,
`record_rejection`, `reset_stats`.

## Distractors that mutate but need no lock — must NOT be listed

- `_evict_locked` — mutates `_sessions`/`_expiry` with no `with` statement, but
  its docstring declares the caller holds the lock and its only caller,
  `drop_expired`, does. This is the highest-value distractor: a purely
  syntactic "mutation not inside a `with`" scan flags it.
- `begin_request`, `note` — mutate `self._local`, a `threading.local()`.
- `export_users` — mutates `users`, a function-local list, after correctly
  taking the lock to copy the shared dict.
- `describe`, `ttl`, `snapshot_stats` — read-only.

## Grading

- Recall: +1 per correctly identified function (max 3).
- Precision: −1 per function listed that is not in the table above.
- Attribution: +1 per finding naming the correct lock (`_sessions_lock` vs
  `_stats_lock`); no credit for an unqualified "the lock".
- Max 6. A response naming exactly the three functions, with the right lock
  each, and quoting a mutating line for each, scores 6.
