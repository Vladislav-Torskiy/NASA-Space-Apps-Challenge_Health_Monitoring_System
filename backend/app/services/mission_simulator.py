"""Mission environment switching and live demo fault injection simulator."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

from app.config import load_nasa_rules, settings
from app.schemas import (
    DemoFaultResponse,
    EnvironmentSwitchResponse,
    EnvironmentType,
    FaultType,
    LatestMetrics,
    MissionContext,
)
from app.services.risk_engine import evaluate_risk, get_thresholds_for_env
from app.services.seed_service import reset_to_baseline


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def get_mission_context(conn: sqlite3.Connection) -> MissionContext:
    """Read active mission context and compute OWLT label."""
    rules = load_nasa_rules(str(settings.data_dir))
    row = conn.execute("SELECT * FROM mission_state WHERE id = 1;").fetchone()
    if row is None:
        raise RuntimeError("mission_state row missing")
    env = row["current_environment"]
    env_cfg = rules["environments"][env]
    return MissionContext(
        environment=env,
        mission_day=int(row["mission_day"]),
        owlt_seconds=int(env_cfg["owlt_seconds"]),
        owlt_label=env_cfg["owlt_label"],
        active_fault=row["active_fault"],
    )


def get_latest_metrics(conn: sqlite3.Connection) -> LatestMetrics:
    """Return latest biometric reading and cumulative radiation dose."""
    latest = conn.execute(
        "SELECT * FROM health_metrics ORDER BY mission_day DESC, id DESC LIMIT 1;"
    ).fetchone()
    rad_row = conn.execute(
        "SELECT COALESCE(SUM(radiation_msv), 0.0) AS total_rad FROM health_metrics;"
    ).fetchone()
    if latest is None:
        raise RuntimeError("No health metrics found")
    return LatestMetrics(
        heart_rate=float(latest["heart_rate"]),
        systolic_bp=float(latest["systolic_bp"]),
        diastolic_bp=float(latest["diastolic_bp"]),
        blood_glucose_mg_dl=float(latest["blood_glucose_mg_dl"]),
        temperature_c=float(latest["temperature_c"]),
        sleep_hours=float(latest["sleep_hours"]),
        mood_score=int(latest["mood_score"]),
        radiation_msv_total=round(float(rad_row["total_rad"]), 2),
        radiation_msv_daily=float(latest["radiation_msv"]),
    )


def switch_environment(
    conn: sqlite3.Connection, environment: EnvironmentType
) -> EnvironmentSwitchResponse:
    """Switch mission environment, update OWLT and recalculate risk thresholds."""
    conn.execute(
        "UPDATE mission_state SET current_environment = ?, updated_at = ? WHERE id = 1;",
        (environment, _utc_now_iso()),
    )
    evaluation = evaluate_risk(conn, environment_override=environment)
    return EnvironmentSwitchResponse(
        mission=get_mission_context(conn),
        thresholds=get_thresholds_for_env(environment),
        evaluation=evaluation,
    )


def inject_demo_fault(conn: sqlite3.Connection, fault: FaultType) -> DemoFaultResponse:
    """Apply or reset a realistic NASA HRP crisis scenario for live demonstrations."""
    if fault == "reset_baseline":
        reset_to_baseline(conn)
        evaluation = evaluate_risk(conn)
        return DemoFaultResponse(
            fault_applied="reset_baseline",
            mission=get_mission_context(conn),
            latest_metrics=get_latest_metrics(conn),
            evaluation=evaluation,
        )

    # Start from a clean baseline before applying the selected crisis so switching faults is clean
    reset_to_baseline(conn)
    state_row = conn.execute("SELECT * FROM mission_state WHERE id = 1;").fetchone()
    env = state_row["current_environment"]
    current_day = int(state_row["mission_day"])
    now = datetime.now(timezone.utc).replace(microsecond=0)

    if fault == "solar_flare":
        new_day = current_day + 1
        conn.execute(
            """
            INSERT INTO health_metrics (
                timestamp, mission_day, environment, heart_rate, systolic_bp, diastolic_bp,
                blood_glucose_mg_dl, temperature_c, sleep_hours, mood_score, radiation_msv, source, notes
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                now.isoformat(),
                new_day,
                env,
                78.0,
                126.0,
                82.0,
                104.0,
                37.3,
                6.4,
                6,
                4.8,
                "fault_simulation",
                "Solar Particle Event (SPE) dosimeter spike",
            ),
        )
        conn.execute(
            "UPDATE mission_state SET mission_day = ?, active_fault = ?, updated_at = ? WHERE id = 1;",
            (new_day, "solar_flare", now.isoformat()),
        )

    elif fault == "co2_drift":
        new_day = current_day + 1
        conn.execute(
            """
            INSERT INTO health_metrics (
                timestamp, mission_day, environment, heart_rate, systolic_bp, diastolic_bp,
                blood_glucose_mg_dl, temperature_c, sleep_hours, mood_score, radiation_msv, source, notes
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                now.isoformat(),
                new_day,
                env,
                96.0,
                136.0,
                88.0,
                112.0,
                37.1,
                5.9,
                6,
                0.62,
                "fault_simulation",
                "CO2 scrubber drift: mild headache and tachycardia",
            ),
        )
        conn.execute(
            "UPDATE mission_state SET mission_day = ?, active_fault = ?, updated_at = ? WHERE id = 1;",
            (new_day, "co2_drift", now.isoformat()),
        )

    elif fault == "sleep_deficit":
        # Inject a 5-day circadian deterioration trajectory (days 25..29)
        trajectory = [
            (6.0, 72.0, 7, "Day 1 circadian shift: delayed light cycle"),
            (5.5, 76.0, 6, "Day 2 circadian shift: fragmented sleep"),
            (5.1, 80.0, 5, "Day 3 circadian shift: fatigue reported"),
            (4.7, 84.0, 5, "Day 4 circadian shift: rising resting HR"),
            (4.2, 89.0, 4, "Day 5 circadian sleep deficit alert"),
        ]
        for idx, (sleep_h, hr, mood, note) in enumerate(trajectory, start=1):
            day = current_day + idx
            ts = (now - timedelta(days=(5 - idx))).isoformat()
            conn.execute(
                """
                INSERT INTO health_metrics (
                    timestamp, mission_day, environment, heart_rate, systolic_bp, diastolic_bp,
                    blood_glucose_mg_dl, temperature_c, sleep_hours, mood_score, radiation_msv, source, notes
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    ts,
                    day,
                    env,
                    hr,
                    128.0 + idx,
                    82.0,
                    108.0 + idx * 2,
                    36.8,
                    sleep_h,
                    mood,
                    0.60,
                    "fault_simulation",
                    note,
                ),
            )
        final_day = current_day + 5
        conn.execute(
            "UPDATE mission_state SET mission_day = ?, active_fault = ?, updated_at = ? WHERE id = 1;",
            (final_day, "sleep_deficit", now.isoformat()),
        )

    evaluation = evaluate_risk(conn)
    return DemoFaultResponse(
        fault_applied=fault,
        mission=get_mission_context(conn),
        latest_metrics=get_latest_metrics(conn),
        evaluation=evaluation,
    )
