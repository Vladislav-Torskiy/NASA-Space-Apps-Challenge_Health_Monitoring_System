"""SQLite WAL-mode database connection and schema setup."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from typing import Iterator

from app.config import settings

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS mission_state (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    current_environment TEXT NOT NULL,
    mission_day INTEGER NOT NULL,
    readiness_score INTEGER NOT NULL,
    streak_days INTEGER NOT NULL,
    active_fault TEXT,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS health_metrics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    mission_day INTEGER NOT NULL,
    environment TEXT NOT NULL,
    heart_rate REAL NOT NULL,
    systolic_bp REAL NOT NULL,
    diastolic_bp REAL NOT NULL,
    blood_glucose_mg_dl REAL NOT NULL,
    temperature_c REAL NOT NULL,
    sleep_hours REAL NOT NULL,
    mood_score INTEGER NOT NULL,
    radiation_msv REAL NOT NULL,
    source TEXT NOT NULL,
    notes TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS vision_assessments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    mode TEXT NOT NULL,
    provider_used TEXT NOT NULL,
    severity TEXT NOT NULL,
    extracted_json TEXT,
    affected_zones_json TEXT NOT NULL,
    escalation_level TEXT NOT NULL,
    summary TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS routine_tasks (
    id INTEGER PRIMARY KEY,
    title TEXT NOT NULL,
    hazard_category TEXT NOT NULL,
    due_label TEXT NOT NULL,
    completed INTEGER NOT NULL DEFAULT 0,
    points INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS badges (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT NOT NULL UNIQUE,
    title TEXT NOT NULL,
    description TEXT NOT NULL,
    unlocked INTEGER NOT NULL DEFAULT 0,
    unlocked_at TEXT
);

CREATE TABLE IF NOT EXISTS ground_packets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    environment TEXT NOT NULL,
    owlt_seconds INTEGER NOT NULL,
    status TEXT NOT NULL,
    payload_json TEXT NOT NULL
);
"""


def get_connection() -> sqlite3.Connection:
    """Open a SQLite connection configured with WAL mode and Row factory."""
    db_path = settings.sqlite_db_path
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    return conn


@contextmanager
def db_session() -> Iterator[sqlite3.Connection]:
    """Provide a transactional SQLite session context manager."""
    conn = get_connection()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db() -> None:
    """Ensure all 6 tables exist in SQLite."""
    with db_session() as conn:
        conn.executescript(SCHEMA_SQL)
