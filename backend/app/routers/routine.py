"""Mission routine checklist and gamification endpoints."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.database import db_session
from app.schemas import RoutineCompleteResponse
from app.services.routine_service import complete_routine_task
from app.services.seed_service import ensure_seeded

router = APIRouter(prefix="/api/routine", tags=["Routine & Gamification"])


@router.post("/{task_id}/complete", response_model=RoutineCompleteResponse)
def api_complete_routine_task(task_id: int) -> RoutineCompleteResponse:
    """Mark a mission routine task complete, award readiness points, and check badges."""
    with db_session() as conn:
        ensure_seeded(conn)
        try:
            return complete_routine_task(conn, task_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
