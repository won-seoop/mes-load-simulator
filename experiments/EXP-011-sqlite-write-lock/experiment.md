# EXP-011 SQLite Write-Lock Contention: WAL Mode Tried and Rejected

## Goal

PAR-014 (2026-09-28) found 2 real `database is locked` 500s buried in one day's
`server.log` during the routine 50 VU/3min daily load test. Reproduce the
contention on demand, measure it, and fix it.

## Hypothesis

The default sqlite3 rollback-journal mode gives a writer a brief EXCLUSIVE
lock at commit time that also blocks concurrent readers. With the autonomous
simulation engine's background tick thread committing on its own
`SessionLocal()` at the same time as request-handling threads, this should be
reproducible under sustained concurrent load, and WAL mode (which lets readers
proceed against the last-committed snapshot instead of blocking) should
reduce or eliminate it.

## Problem Measurement (Baseline)

`database is locked` is a genuinely rare event: 2 occurrences out of 16,208
requests (0.012%) in the one historical occurrence (PAR-014).

A single-process, single-endpoint thread-pool harness (hammering
`PATCH /equipment/{id}/status` directly via TestClient) could not reproduce it
at all, even at 9,000 tight-loop requests across 15 threads (matching the
default SQLAlchemy pool capacity of 5+10). Python's sqlite3 driver already
applies a 5s busy-timeout by default, which absorbed all contention in that
harness.

We then switched to the realistic reproduction: a real uvicorn process with
the autonomous simulation engine's background writer turned on
(`POST /simulation/start`), hit with the full Locust endpoint mix
(`scripts/repro_sqlite_lock.sh`), at **exactly the production cadence (50 VU)
for double the original duration (6 min instead of 3 min)**:

| Run | Requests | Failures | `database is locked` | Server 5xx |
|---|---:|---:|---:|---:|
| Baseline run 1 (unmodified) | 29,878 | 0 | 0 | 0 |
| Baseline run 2 (control rerun) | 30,473 | 0 | 0 | 0 |

Across ~60,000 repro requests at the exact production VU count, over 2x the
original run's duration, the error did not reproduce once. Combined with the
single-endpoint harness's 9,000 requests, that is three independent attempts
and 0 reproductions. **We could not reproduce PAR-014's failure on demand.**
This itself is a legitimate finding, not a gap to paper over: the event
appears to depend on timing/scheduling conditions (e.g. shared container CPU
contention — PAR-013 already documented similar session-level noise) that a
dedicated repro harness does not reliably recreate.

## Alternatives

Because the original failure could not be reproduced, "fewer `database is
locked` errors" could not be used as the comparison metric. Instead, each
alternative was measured against the two non-WAL baseline runs above, on the
same identical workload (50 VU, 6 min, `scripts/repro_sqlite_lock.sh`), using
p95/p99 latency and RPS as the metric — any config change must not regress
these under normal load, since the exact failure to fix cannot be observed in
this harness.

- **B: WAL journal mode + `synchronous=NORMAL` + `busy_timeout=15000`**
  (`PRAGMA` set via a SQLAlchemy `connect` event listener). This was the
  initially-chosen approach, since WAL is the textbook fix for
  reader-vs-writer blocking in rollback-journal mode. Implemented and
  measured on the identical workload:

  | Run | Requests | RPS | p95 | p99 | max | `database is locked` |
  |---|---:|---:|---:|---:|---:|---:|
  | WAL mode | 19,210 | 53.36 | **1400ms** | **1700ms** | 3517ms | 0 |

  This is a **severe regression**: RPS dropped 35% (83→53) and p95 latency
  grew **4.5x** (310ms→1400ms) versus baseline, with 0% failures (the server
  didn't error, it just got much slower). The `-wal` file grew to **over
  300MB** during the 6-minute run and was still growing at shutdown. This
  points to WAL checkpoint starvation: with FastAPI's connection pool
  constantly servicing new concurrent read requests, there is rarely a
  moment with zero open reader snapshots, so SQLite's passive auto-checkpoint
  cannot reclaim old WAL frames fast enough to keep the file (and therefore
  every read's cost) bounded under this app's continuous mixed read/write
  traffic.

  To rule out this being session-level noise (back-to-back heavy test runs in
  the same container — the kind of confound PAR-013 already flagged) rather
  than a real WAL-specific effect, baseline run 2 above was run *after* the
  WAL run, with no code change, and it returned to baseline (p95 270ms,
  p99 590ms) — matching baseline run 1 and nothing like the WAL run. The
  regression is attributable to WAL mode itself, not run ordering.

  **Rejected**: trading an unreproduced, ~0.012%-frequency error for a
  measured, repeatable 4.5x latency regression under normal load is a bad
  trade. A real fix would need explicit checkpoint tuning (e.g. a forced
  periodic `PRAGMA wal_checkpoint`) which is more engineering investment than
  today's scope, especially for a failure mode we cannot even confirm we've
  reproduced.

- **A: just raise the sqlite3 driver's own busy-wait timeout**
  (`connect_args={"timeout": 15}`, up from the driver's 5s default — no
  journal mode change). Measured on the identical workload:

  | Run | Requests | RPS | p95 | p99 |
  |---|---:|---:|---:|---:|
  | Alternative A (timeout=15s) | 29,238 | ~81 | 360ms | 720ms |

  This is within the same range as both non-WAL baselines (270-310ms p95,
  590-670ms p99) — no measurable regression. Since the modified value only
  matters when a writer is actually contended (which, per the measurements
  above, is rare enough that we couldn't trigger it even once), raising it
  costs nothing under normal load and gives the rare contention case 3x more
  room to resolve before failing outright.

  **Adopted.**

## Decision

Keep SQLite's default rollback-journal mode (do not enable WAL). Raise the
sqlite3 driver's busy-wait from 5s to 15s via `connect_args={"timeout": 15}`
in `app/database.py`. This is a deliberately modest, low-risk change: it adds
headroom for the one confirmed-but-unreproducible failure mode without
touching anything that this experiment measured to regress performance.

WAL mode (with proper checkpoint tuning) remains a candidate worth revisiting
if `database is locked` is ever observed again in a daily report — see
ROADMAP "다음 후보".

## Regression Test

`tests/test_database.py::test_sqlite_busy_timeout_raised_above_driver_default`
asserts `PRAGMA busy_timeout` reads back as 15000 on a fresh connection from
the app's engine, so a future refactor of `app/database.py` cannot silently
drop this back to the 5s driver default.

## Failure Case Preserved

The WAL-mode measurement above is kept in this file (not deleted) per
CLAUDE.md's "실패한 실험" principle: the hypothesis that WAL would help was
wrong for this specific workload shape (continuous concurrent reads +
writes through a small pooled set of connections), and that negative result
is as valuable as a positive one for anyone revisiting this area later.
