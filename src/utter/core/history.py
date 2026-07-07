"""HistoryStore — local sqlite at %APPDATA%\\Utter\\history.db. Never transmitted (§16)."""

from __future__ import annotations

import sqlite3
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

from utter.paths import history_db_path

_SCHEMA = """
CREATE TABLE IF NOT EXISTS history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    raw TEXT NOT NULL,
    final TEXT NOT NULL,
    latency_ms REAL,
    model TEXT,
    language TEXT
)
"""


class HistoryStore:
    def __init__(self, path: Path | None = None) -> None:
        self._path = path or history_db_path()
        with closing(sqlite3.connect(self._path)) as con, con:
            con.execute(_SCHEMA)

    def _connect(self) -> closing:
        # connection per call (closed, not GC'd): thread-safe by construction
        return closing(sqlite3.connect(self._path))

    def add(
        self, raw: str, final: str, latency_ms: float, model: str, language: str
    ) -> None:
        with self._connect() as con, con:
            con.execute(
                "INSERT INTO history (ts, raw, final, latency_ms, model, language) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (datetime.now(UTC).isoformat(), raw, final, latency_ms, model, language),
            )

    def recent(self, n: int = 10) -> list[dict]:
        with self._connect() as con:
            con.row_factory = sqlite3.Row
            rows = con.execute(
                "SELECT ts, raw, final, latency_ms, model, language "
                "FROM history ORDER BY id DESC LIMIT ?",
                (n,),
            ).fetchall()
        return [dict(r) for r in rows]
