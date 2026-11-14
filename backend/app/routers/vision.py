"""Hybrid Vision/CV analysis and holistic risk evaluation endpoints."""

from __future__ import annotations

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from app.database import db_session
from app.schemas import (
    EnvironmentType,
    RiskEvaluateRequest,
    RiskEvaluationResponse,
    VisionAnalyzeResponse,
    VisionMode,
)
from app.services.risk_engine import evaluate_risk
from app.services.seed_service import ensure_seeded
from app.services.vision_service import analyze_vision_image
from typing import cast

router = APIRouter(prefix="/api", tags=["AI / Vision & Risk Engine"])


@router.post("/vision/analyze", response_model=VisionAnalyzeResponse)
async def api_vision_analyze(
    image: UploadFile = File(...),
    mode: VisionMode = Form(...),
    environment: EnvironmentType | None = Form(None),
    context_notes: str = Form(""),
) -> VisionAnalyzeResponse:
    """Analyze ultrasound, skin/eye photo, or medical device display via Hybrid Vision + OpenCV fallback."""
    image_bytes = await image.read()
    if not image_bytes:
        raise HTTPException(status_code=400, detail="Uploaded image file is empty.")

    with db_session() as conn:
        ensure_seeded(conn)
        try:
            if environment is None:
                row = conn.execute(
                    "SELECT current_environment FROM mission_state WHERE id = 1"
                ).fetchone()
                resolved_env = cast(
                    EnvironmentType,
                    row["current_environment"] if row else "spacecraft",
                )
            else:
                resolved_env = environment

            return analyze_vision_image(
                conn=conn,
                image_bytes=image_bytes,
                mode=mode,
                environment=resolved_env,
                context_notes=context_notes,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/evaluate/risk", response_model=RiskEvaluationResponse)
def api_evaluate_risk(
    req: RiskEvaluateRequest | None = None,
) -> RiskEvaluationResponse:
    """Run holistic risk assessment combining metrics, 14-day trends, and latest vision findings."""
    body = req or RiskEvaluateRequest()
    with db_session() as conn:
        ensure_seeded(conn)
        return evaluate_risk(
            conn=conn,
            environment_override=body.environment,
            include_latest_vision=body.include_latest_vision,
        )
