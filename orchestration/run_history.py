"""
Run History — SQLite-backed, per Spec Document Section 3.4 (stdlib sqlite3,
no external database dependency; no multi-user concurrent-write need).

Contract:
    consumes: RunParams / RunResult
    produces: recent-runs list, single run lookup
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime

from orchestration.models import RunParams, RunResult, RunStatus

DEFAULT_DB_PATH = "run_history.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    start_period INTEGER,
    end_period INTEGER,
    lines TEXT,
    min_dos_override REAL,
    status TEXT,
    output_path TEXT,
    assumption_messages TEXT,
    errors TEXT
);
"""


def _connect(db_path: str = DEFAULT_DB_PATH) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.execute(_SCHEMA)
    return conn


def record_run(params: RunParams, result: RunResult, db_path: str = DEFAULT_DB_PATH) -> int:
    conn = _connect(db_path)
    with conn:
        cursor = conn.execute(
            """INSERT INTO runs
               (timestamp, start_period, end_period, lines, min_dos_override,
                status, output_path, assumption_messages, errors)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                result.timestamp.isoformat(),
                params.start_period,
                params.end_period,
                json.dumps(params.lines) if params.lines else None,
                params.min_dos_override,
                result.status.value,
                result.output_path,
                json.dumps(result.assumption_messages),
                json.dumps(result.errors),
            ),
        )
    conn.close()
    return cursor.lastrowid


def get_recent_runs(n: int = 10, db_path: str = DEFAULT_DB_PATH) -> list[dict]:
    conn = _connect(db_path)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT * FROM runs ORDER BY id DESC LIMIT ?", (n,)).fetchall()
    conn.close()
    return [dict(row) for row in rows]


def get_run(run_id: int, db_path: str = DEFAULT_DB_PATH) -> dict | None:
    conn = _connect(db_path)
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
    conn.close()
    return dict(row) if row else None
