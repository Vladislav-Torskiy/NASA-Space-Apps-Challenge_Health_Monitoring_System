"""Health check and main dashboard endpoints."""

from __future__ import annotations

from fastapi import APIRouter

from app.database import db_session
from app.schemas import DashboardResponse, HealthCheckResponse
from app.services.mission_simulator import get_latest_metrics, get_mission_context
from app.services.risk_engine import evaluate_risk
from app.services.routine_service import get_gamification_summary, get_routine_tasks
from app.services.seed_service import ensure_seeded
from app.services.vision_service import get_vision_provider_status, is_tesseract_available

router = APIRouter(prefix="/api", tags=["Dashboard & Health"])


@router.get("/health", response_model=HealthCheckResponse)
def api_health() -> HealthCheckResponse:
    """Verify backend availability, SQLite state, and Vision/Tesseract readiness."""
    with db_session() as conn:
        ensure_seeded(conn)
        row = conn.execute("SELECT mission_day FROM mission_state WHERE id = 1;").fetchone()
        mission_day = int(row["mission_day"]) if row else 24

    return HealthCheckResponse(
        status="ok",
        vision_provider=get_vision_provider_status(),
        tesseract_available=is_tesseract_available(),
        mission_day=mission_day,
    )


@router.get("/dashboard", response_model=DashboardResponse)
def api_dashboard() -> DashboardResponse:
    """Return full operational snapshot for the astronaut console."""
    with db_session() as conn:
        ensure_seeded(conn)
        evaluation = evaluate_risk(conn)
        mission = get_mission_context(conn)
        gamification = get_gamification_summary(conn)
        latest_metrics = get_latest_metrics(conn)
        routine_tasks = get_routine_tasks(conn)

    return DashboardResponse(
        mission=mission,
        gamification=gamification,
        body_zones=evaluation.body_zones,
        latest_metrics=latest_metrics,
        routine_tasks=routine_tasks,
    )
