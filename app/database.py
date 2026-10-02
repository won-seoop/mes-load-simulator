import os

from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

# Overridable so the test suite can point at an isolated sqlite file
# instead of the real ./mes.db used by the running server.
DATABASE_URL = os.environ.get("MES_DATABASE_URL", "sqlite:///./mes.db")

# EXP-011 / PAR-014: PAR-014 (2026-09-28) found 2 real `database is locked`
# 500s buried in one day's server.log. We could not reproduce that error on
# demand even across ~110k repro requests (50-120 VU, up to 6min, see
# experiments/EXP-011-sqlite-write-lock) -- it appears to be a very rare,
# timing-dependent race. We also tried enabling WAL journal mode as a fix,
# measured it under the identical workload, and REJECTED it: WAL's background
# checkpoint couldn't keep up with this app's continuous mixed read/write
# traffic (connection pool keeps several overlapping reader snapshots open
# at once), so the -wal file grew unboundedly (observed 300MB+ in 6 minutes)
# and p95 latency got *worse*, not better (310ms -> 1400ms, confirmed against
# a same-config control rerun to rule out session-level noise). Instead we
# just raise the sqlite3 driver's own busy-wait from its 5s default to 15s,
# which gives the rare contention case 3x more room to resolve on its own
# before failing, with zero measured cost under normal load (29238 vs 29878
# baseline requests, p95 360ms vs 310ms -- within run-to-run noise).
engine = create_engine(
    DATABASE_URL, connect_args={"check_same_thread": False, "timeout": 15}
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
