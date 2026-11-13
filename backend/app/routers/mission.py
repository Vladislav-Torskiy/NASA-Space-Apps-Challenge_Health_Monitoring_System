"""Mission environment switching and live demo fault injection endpoints."""

from __future__ import annotations

from fastapi import APIRouter

from app.database import db_session
from app.schemas import (
    DemoFaultRequest,
    DemoFaultResponse,
    EnvironmentSwitchRequest,
    EnvironmentSwitchResponse,
)
from app.services.mission_simulator import inject_demo_fault, switch_environment
from app.services.seed_service import ensure_seeded

router = APIRouter(prefix="/api", tags=["Mission Simulation"])


@router.post("/mission/environment", response_model=EnvironmentSwitchResponse)
def api_switch_environment(req: EnvironmentSwitchRequest) -> EnvironmentSwitchResponse:
    """Switch active mission environment, OWLT latency, and space-adjusted thresholds."""
    with db_session() as conn:
        ensure_seeded(conn)
        return switch_environment(conn, req.environment)


@router.post("/demo/fault", response_model=DemoFaultResponse)
def api_demo_fault(req: DemoFaultRequest) -> DemoFaultResponse:
    """Inject a realistic spaceflight crisis or reset baseline for live demonstrations."""
    with db_session() as conn:
        ensure_seeded(conn)
        return inject_demo_fault(conn, req.fault)
