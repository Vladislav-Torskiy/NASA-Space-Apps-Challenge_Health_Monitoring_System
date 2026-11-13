"""Database seeding and baseline reset service."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

from app.config import load_seed_data


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def reset_to_baseline(conn: sqlite3.Connection) -> None:
    """Clear dynamic mission tables and load the nominal 24-day seed dataset."""
    seed = load_seed_data()
    mission = seed["mission"]
    now = datetime.now(timezone.utc).replace(microsecond=0)
    max_day = max((int(item["mission_day"]) for item in seed["metrics_history"]), default=24)

    conn.execute("DELETE FROM ground_packets;")
    conn.execute("DELETE FROM vision_assessments;")
    conn.execute("DELETE FROM health_metrics;")
    conn.execute("DELETE FROM routine_tasks;")
    conn.execute("DELETE FROM badges;")
    conn.execute("DELETE FROM mission_state;")

    conn.execute(
        """
        INSERT INTO mission_state (
            id, current_environment, mission_day, readiness_score, streak_days, active_fault, updated_at
        ) VALUES (1, ?, ?, ?, ?, ?, ?)
        """,
        (
            mission["environment"],
            int(mission["mission_day"]),
            int(mission["readiness_score"]),
            int(mission["streak_days"]),
            mission.get("active_fault"),
            now.isoformat(),
        ),
    )

    for entry in seed["metrics_history"]:
        day = int(entry["mission_day"])
        record_ts = (now - timedelta(days=(max_day - day))).isoformat()
        conn.execute(
            """
            INSERT INTO health_metrics (
                timestamp, mission_day, environment, heart_rate, systolic_bp, diastolic_bp,
                blood_glucose_mg_dl, temperature_c, sleep_hours, mood_score, radiation_msv, source, notes
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record_ts,
                day,
                entry.get("environment", mission["environment"]),
                float(entry["heart_rate"]),
                float(entry["systolic_bp"]),
                float(entry["diastolic_bp"]),
                float(entry["blood_glucose_mg_dl"]),
                float(entry["temperature_c"]),
                float(entry["sleep_hours"]),
                int(entry["mood_score"]),
                float(entry["radiation_msv"]),
                entry.get("source", "seed"),
                entry.get("notes", ""),
            ),
        )

    for task in seed["routine_tasks"]:
        conn.execute(
            """
            INSERT INTO routine_tasks (id, title, hazard_category, due_label, completed, points)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                int(task["id"]),
                task["title"],
                task["hazard_category"],
                task["due_label"],
                1 if task.get("completed") else 0,
                int(task["points"]),
            ),
        )

    for badge in seed["badges"]:
        unlocked = 1 if badge.get("unlocked") else 0
        unlocked_at = _utc_now_iso() if unlocked else None
        conn.execute(
            """
            INSERT INTO badges (code, title, description, unlocked, unlocked_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                badge["code"],
                badge["title"],
                badge["description"],
                unlocked,
                unlocked_at,
            ),
        )


def ensure_seeded(conn: sqlite3.Connection) -> None:
    """Seed the SQLite database once if mission_state is empty."""
    row = conn.execute("SELECT id FROM mission_state WHERE id = 1;").fetchone()
    if row is None:
        reset_to_baseline(conn)
