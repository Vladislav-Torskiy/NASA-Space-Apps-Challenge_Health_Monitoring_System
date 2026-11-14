"""Biometric metrics history and manual/OCR logging endpoints."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Query

from app.database import db_session
from app.schemas import (
    MetricCreateRequest,
    MetricCreateResponse,
    MetricRecord,
    MetricsHistoryResponse,
)
from app.services.risk_engine import compute_trends, evaluate_risk, get_thresholds_for_env
from app.services.seed_service import ensure_seeded

router = APIRouter(prefix="/api/metrics", tags=["Biometrics & Trends"])


@router.get("/history", response_model=MetricsHistoryResponse)
def api_metrics_history(
    days: int = Query(default=30, ge=1, le=90),
) -> MetricsHistoryResponse:
    """Return historical biometric measurements, space-adjusted thresholds, and trend alerts."""
    with db_session() as conn:
        ensure_seeded(conn)
        state = conn.execute(
            "SELECT current_environment FROM mission_state WHERE id = 1;"
        ).fetchone()
        env = state["current_environment"]

        rows = conn.execute(
            """
            SELECT * FROM (
                SELECT * FROM health_metrics
                ORDER BY mission_day DESC, id DESC
                LIMIT ?
            ) sub
            ORDER BY mission_day ASC, id ASC;
            """,
            (days,),
        ).fetchall()

        records_dict = [dict(r) for r in rows]
        records = [MetricRecord(**r) for r in records_dict]
        thresholds = get_thresholds_for_env(env)
        trend_alerts = compute_trends(records_dict)

    return MetricsHistoryResponse(
        environment=env,
        days_requested=days,
        records=records,
        thresholds=thresholds,
        trend_alerts=trend_alerts,
    )


@router.post("", response_model=MetricCreateResponse)
def api_create_metric(payload: MetricCreateRequest) -> MetricCreateResponse:
    """Log a new manual or OCR-confirmed biometric reading and re-evaluate mission risk."""
    now_iso = datetime.now(UTC).replace(microsecond=0).isoformat()
    with db_session() as conn:
        ensure_seeded(conn)
        state = conn.execute(
            "SELECT current_environment, mission_day FROM mission_state WHERE id = 1;"
        ).fetchone()
        env = state["current_environment"]
        mission_day = int(state["mission_day"])

        cursor = conn.execute(
            """
            INSERT INTO health_metrics (
                timestamp, mission_day, environment, heart_rate, systolic_bp, diastolic_bp,
                blood_glucose_mg_dl, temperature_c, sleep_hours, mood_score, radiation_msv, source, notes
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
            """,
            (
                now_iso,
                mission_day,
                env,
                payload.heart_rate,
                payload.systolic_bp,
                payload.diastolic_bp,
                payload.blood_glucose_mg_dl,
                payload.temperature_c,
                payload.sleep_hours,
                payload.mood_score,
                payload.radiation_msv_daily,
                payload.source,
                payload.notes,
            ),
        )
        row = conn.execute(
            "SELECT * FROM health_metrics WHERE id = ?;", (cursor.lastrowid,)
        ).fetchone()
        evaluation = evaluate_risk(conn)

    return MetricCreateResponse(
        record=MetricRecord(**dict(row)),
        evaluation=evaluation,
    )
