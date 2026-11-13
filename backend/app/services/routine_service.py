"""Mission routine checklist and gamification badge engine."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

from app.schemas import (
    BadgeItem,
    GamificationSummary,
    RoutineCompleteResponse,
    RoutineTaskItem,
)
from app.services.risk_engine import evaluate_risk


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def get_gamification_summary(conn: sqlite3.Connection) -> GamificationSummary:
    """Read current readiness_score, streak_days, and all badges."""
    state = conn.execute(
        "SELECT readiness_score, streak_days FROM mission_state WHERE id = 1;"
    ).fetchone()
    badge_rows = conn.execute("SELECT * FROM badges ORDER BY id ASC;").fetchall()
    badges = [
        BadgeItem(
            code=b["code"],
            title=b["title"],
            description=b["description"],
            unlocked=bool(b["unlocked"]),
            unlocked_at=b["unlocked_at"],
        )
        for b in badge_rows
    ]
    return GamificationSummary(
        readiness_score=int(state["readiness_score"]),
        streak_days=int(state["streak_days"]),
        badges=badges,
    )


def get_routine_tasks(conn: sqlite3.Connection) -> list[RoutineTaskItem]:
    """List mission routine tasks."""
    rows = conn.execute("SELECT * FROM routine_tasks ORDER BY id ASC;").fetchall()
    return [
        RoutineTaskItem(
            id=int(r["id"]),
            title=r["title"],
            hazard_category=r["hazard_category"],
            due_label=r["due_label"],
            completed=bool(r["completed"]),
            points=int(r["points"]),
        )
        for r in rows
    ]


def unlock_badge_if_needed(conn: sqlite3.Connection, code: str) -> bool:
    """Unlock a badge by code if currently locked. Returns True if newly unlocked."""
    row = conn.execute(
        "SELECT unlocked FROM badges WHERE code = ?;", (code,)
    ).fetchone()
    if row is None or int(row["unlocked"]) == 1:
        return False
    conn.execute(
        "UPDATE badges SET unlocked = 1, unlocked_at = ? WHERE code = ?;",
        (_utc_now_iso(), code),
    )
    return True


def complete_routine_task(
    conn: sqlite3.Connection, task_id: int
) -> RoutineCompleteResponse:
    """Mark a mission routine task completed, update streak, readiness score, and badges."""
    task_row = conn.execute(
        "SELECT * FROM routine_tasks WHERE id = ?;", (task_id,)
    ).fetchone()
    if task_row is None:
        raise KeyError(f"Routine task {task_id} not found")

    already_completed = bool(task_row["completed"])
    newly_unlocked: list[str] = []

    if not already_completed:
        conn.execute(
            "UPDATE routine_tasks SET completed = 1, due_label = 'Completed' WHERE id = ?;",
            (task_id,),
        )
        # Increment streak once on the first completed task of the active day (6 -> 7 unlocks Vitals Streak)
        completed_count_row = conn.execute(
            "SELECT COUNT(*) AS cnt FROM routine_tasks WHERE completed = 1;"
        ).fetchone()
        if int(completed_count_row["cnt"]) == 1:
            conn.execute(
                "UPDATE mission_state SET streak_days = streak_days + 1, updated_at = ? WHERE id = 1;",
                (_utc_now_iso(),),
            )

        # Map specific routine task to corresponding badge
        task_badge_map = {
            1: "hydration_glucose_ace",
            2: "bone_guardian",
            3: "radiation_shield",
            4: "circadian_master",
        }
        badge_code = task_badge_map.get(task_id)
        if badge_code and unlock_badge_if_needed(conn, badge_code):
            newly_unlocked.append(badge_code)

        # Check 7-day streak badge
        state = conn.execute("SELECT streak_days FROM mission_state WHERE id = 1;").fetchone()
        if int(state["streak_days"]) >= 7 and unlock_badge_if_needed(conn, "vitals_streak_7"):
            newly_unlocked.append("vitals_streak_7")

    # Recalculate readiness_score cleanly via risk engine
    evaluate_risk(conn)

    updated_task = conn.execute(
        "SELECT * FROM routine_tasks WHERE id = ?;", (task_id,)
    ).fetchone()

    return RoutineCompleteResponse(
        task=RoutineTaskItem(
            id=int(updated_task["id"]),
            title=updated_task["title"],
            hazard_category=updated_task["hazard_category"],
            due_label=updated_task["due_label"],
            completed=bool(updated_task["completed"]),
            points=int(updated_task["points"]),
        ),
        gamification=get_gamification_summary(conn),
        newly_unlocked_badges=newly_unlocked,
    )
