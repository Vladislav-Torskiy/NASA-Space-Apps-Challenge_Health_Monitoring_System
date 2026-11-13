"""Ground Link Packet Builder (OWLT-aware Flight Surgeon telemetry dispatch)."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone

from app.schemas import GroundTransmitRequest, GroundTransmitResponse
from app.services.mission_simulator import get_latest_metrics, get_mission_context
from app.services.risk_engine import evaluate_risk


def transmit_to_ground(
    conn: sqlite3.Connection, req: GroundTransmitRequest
) -> GroundTransmitResponse:
    """Assemble and store a compact Telemetry & Medical Packet with OWLT latency info."""
    created_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    mission = get_mission_context(conn)
    latest = get_latest_metrics(conn)
    evaluation = evaluate_risk(conn)

    abnormal_zones = [
        {
            "zone_id": z.zone_id,
            "label": z.label,
            "status": z.status,
            "summary": z.summary,
        }
        for z in evaluation.body_zones
        if z.status != "nominal"
    ]

    recent_rows = conn.execute(
        "SELECT mission_day, heart_rate, systolic_bp, diastolic_bp, blood_glucose_mg_dl, "
        "temperature_c, sleep_hours, mood_score, radiation_msv "
        "FROM health_metrics ORDER BY mission_day DESC, id DESC LIMIT ?;",
        (req.include_full_history_days,),
    ).fetchall()
    recent_history = [dict(r) for r in reversed(recent_rows)]

    latest_vision = conn.execute(
        "SELECT timestamp, mode, provider_used, severity, escalation_level, summary "
        "FROM vision_assessments ORDER BY id DESC LIMIT 1;"
    ).fetchone()

    payload = {
        "packet_version": "ASTRA-Med-1.0",
        "generated_at": created_at,
        "mission": mission.model_dump(),
        "owlt_round_trip_seconds": mission.owlt_seconds * 2,
        "escalation_level": evaluation.escalation_level,
        "overall_severity": evaluation.overall_severity,
        "readiness_score": evaluation.readiness_score,
        "flagged_metrics": evaluation.flagged_metrics,
        "abnormal_body_zones": abnormal_zones,
        "trend_alerts": [a.model_dump() for a in evaluation.trend_alerts],
        "latest_metrics": latest.model_dump(),
        "latest_vision_assessment": dict(latest_vision) if latest_vision else None,
        "recent_days_telemetry": recent_history,
        "crew_notes": req.notes,
        "recommended_actions_taken_or_pending": evaluation.action_steps,
    }

    zone_str = (
        ", ".join(f"{z['label']} ({z['status'].upper()})" for z in abnormal_zones)
        if abnormal_zones
        else "None (All zones nominal)"
    )
    text_summary = (
        f"[ASTRA-MED TELEMETRY PACKET] Day {mission.mission_day} | Env: {mission.environment} | "
        f"OWLT: {mission.owlt_label} | Escalation: {evaluation.escalation_level.upper()} | "
        f"Readiness: {evaluation.readiness_score}/100 | "
        f"Vitals: HR {latest.heart_rate:.0f} bpm, BP {latest.systolic_bp:.0f}/{latest.diastolic_bp:.0f} mmHg, "
        f"Glucose {latest.blood_glucose_mg_dl:.0f} mg/dL, Temp {latest.temperature_c:.1f} C, "
        f"Sleep {latest.sleep_hours:.1f} hrs, Mood {latest.mood_score}/10, Total Rad {latest.radiation_msv_total:.2f} mSv | "
        f"Active Zones: {zone_str}. Summary: {evaluation.what_happened_and_why}"
    )

    status = "Delivered (Awaiting Ground Reply)"
    cursor = conn.execute(
        """
        INSERT INTO ground_packets (created_at, environment, owlt_seconds, status, payload_json)
        VALUES (?, ?, ?, ?, ?);
        """,
        (created_at, mission.environment, mission.owlt_seconds, status, json.dumps(payload)),
    )

    round_trip_min = max(1, round((mission.owlt_seconds * 2) / 60))
    interim_guidance = [
        f"Estimated minimum round-trip signal delay before Flight Surgeon reply: ~{round_trip_min} min (OWLT: {mission.owlt_label}).",
        *evaluation.action_steps,
    ]

    return GroundTransmitResponse(
        packet_id=int(cursor.lastrowid),
        created_at=created_at,
        environment=mission.environment,
        owlt_seconds=mission.owlt_seconds,
        owlt_label=mission.owlt_label,
        status=status,
        status_timeline=[
            "Packet Queued",
            "Transmitting",
            "Delivered (Awaiting Ground Reply)",
        ],
        interim_guidance=interim_guidance,
        text_summary=text_summary,
        payload=payload,
    )
