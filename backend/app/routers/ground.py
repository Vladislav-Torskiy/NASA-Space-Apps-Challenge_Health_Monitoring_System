"""Ground Link Telemetry & Medical Packet transmission endpoint."""

from __future__ import annotations

from fastapi import APIRouter

from app.database import db_session
from app.schemas import GroundTransmitRequest, GroundTransmitResponse
from app.services.ground_service import transmit_to_ground
from app.services.seed_service import ensure_seeded

router = APIRouter(prefix="/api/ground", tags=["Ground Link (OWLT)"])


@router.post("/transmit", response_model=GroundTransmitResponse)
def api_ground_transmit(
    req: GroundTransmitRequest | None = None,
) -> GroundTransmitResponse:
    """Build and log a Telemetry & Medical Packet for Flight Surgeon review."""
    request_body = req or GroundTransmitRequest()
    with db_session() as conn:
        ensure_seeded(conn)
        return transmit_to_ground(conn, request_body)
