"""NASA HRP space-adjusted risk, trend slope, and body-zone evaluation engine."""

from __future__ import annotations

import json
import sqlite3
from typing import Any

import numpy as np

from app.config import load_nasa_rules, settings
from app.schemas import (
    BodyZoneStatus,
    EnvironmentType,
    EscalationLevel,
    RiskEvaluationResponse,
    SeverityStatus,
    ThresholdRange,
    TrendAlert,
)

SEVERITY_RANK: dict[SeverityStatus, int] = {
    "nominal": 0,
    "caution": 1,
    "critical": 2,
}

METRIC_TO_ZONES: dict[str, list[str]] = {
    "heart_rate": ["heart_vessels", "lungs_airway"],
    "systolic_bp": ["heart_vessels", "eyes_sans"],
    "diastolic_bp": ["heart_vessels"],
    "blood_glucose_mg_dl": ["kidneys_fluid", "bones_spine"],
    "temperature_c": ["immune_system", "lungs_airway", "skin"],
    "sleep_hours": ["brain_cognition", "eyes_sans"],
    "mood_score": ["brain_cognition"],
    "radiation_msv_daily": ["immune_system", "skin"],
}

FAULT_CONTEXT: dict[str, dict[str, Any]] = {
    "solar_flare": {
        "hazard": "Space Radiation (Solar Particle Event — SPE)",
        "summary": "Solar Particle Event detected: daily radiation dose spiked above flight storm shelter threshold.",
        "zones": {"immune_system": "critical", "skin": "caution"},
        "steps": [
            "Move immediately to the spacecraft/habitat radiation storm shelter.",
            "Confirm personal CSA dosimeter and spacecraft particle flux sensors.",
            "Monitor body temperature and skin integrity over the next 24 hours and transmit telemetry to Flight Surgeon.",
        ],
    },
    "co2_drift": {
        "hazard": "Hostile Closed Environments (Cabin CO2 Scrubber Drift)",
        "summary": "Elevated cabin CO2 load suspected: compensatory heart rate and systolic pressure climb detected.",
        "zones": {"lungs_airway": "caution", "brain_cognition": "caution", "heart_vessels": "caution"},
        "steps": [
            "Inspect CO2 scrubber cartridge / CDRA airflow immediately.",
            "Repeat blood pressure and heart rate check after 10 minutes of paced breathing in a ventilated module.",
            "Perform a 4-zone chest ultrasound sweep if shortness of breath or headache persists.",
        ],
    },
    "sleep_deficit": {
        "hazard": "Isolation & Confinement (Circadian Misalignment)",
        "summary": "Multi-day circadian sleep deficit detected alongside rising resting heart rate and declining mood.",
        "zones": {"brain_cognition": "critical", "eyes_sans": "caution", "heart_vessels": "caution"},
        "steps": [
            "Initiate circadian light-therapy reset (480nm blue-enriched wake block, dark shield before rest).",
            "Avoid caffeine within 8 hours of scheduled sleep block and defer high-risk EVA tasks.",
            "Complete an ocular self-check for eye strain/SANS symptoms and notify crew partner.",
        ],
    },
}


def _max_severity(a: SeverityStatus, b: SeverityStatus) -> SeverityStatus:
    return a if SEVERITY_RANK[a] >= SEVERITY_RANK[b] else b


def get_thresholds_for_env(environment: str) -> dict[str, ThresholdRange]:
    """Return space-adjusted ThresholdRange objects for the active environment."""
    rules = load_nasa_rules(str(settings.data_dir))
    env_thresholds = rules["thresholds"][environment]
    return {metric: ThresholdRange(**cfg) for metric, cfg in env_thresholds.items()}


def _classify_metric(value: float, threshold: ThresholdRange) -> SeverityStatus:
    if threshold.nominal_min <= value <= threshold.nominal_max:
        return "nominal"
    if threshold.caution_min <= value <= threshold.caution_max:
        return "caution"
    return "critical"


def _linear_slope(values: list[float]) -> float:
    if len(values) < 3:
        return 0.0
    x = np.arange(len(values), dtype=float)
    y = np.array(values, dtype=float)
    slope, _ = np.polyfit(x, y, 1)
    return float(slope)


def compute_trends(records: list[dict[str, Any]]) -> list[TrendAlert]:
    """Analyze 5-to-14 day sliding telemetry trends for multi-factor deterioration."""
    if len(records) < 4:
        return []

    by_day: dict[int, dict[str, Any]] = {}
    for r in records:
        by_day[int(r["mission_day"])] = r
    daily_records = [by_day[day] for day in sorted(by_day)]

    recent_5 = daily_records[-5:]
    recent_14 = daily_records[-14:]
    alerts: list[TrendAlert] = []

    sleep_slope = _linear_slope([float(r["sleep_hours"]) for r in recent_5])
    hr_slope = _linear_slope([float(r["heart_rate"]) for r in recent_5])
    mood_slope = _linear_slope([float(r["mood_score"]) for r in recent_5])
    glucose_slope = _linear_slope([float(r["blood_glucose_mg_dl"]) for r in recent_14[-7:]])

    latest = records[-1]
    latest_sleep = float(latest["sleep_hours"])
    latest_mood = int(latest["mood_score"])
    latest_glucose = float(latest["blood_glucose_mg_dl"])

    if (sleep_slope <= -0.25 and hr_slope >= 1.5) or (sleep_slope <= -0.35 and latest_sleep < 6.0):
        sev: SeverityStatus = "critical" if latest_sleep < 4.8 and latest_mood <= 4 else "caution"
        alerts.append(
            TrendAlert(
                code="circadian_behavioral_drift",
                title="Behavioral / Circadian Drift",
                severity=sev,
                metric="sleep_hours",
                slope_per_day=round(sleep_slope, 3),
                affected_zones=["brain_cognition", "eyes_sans", "heart_vessels"],
                message=(
                    f"5-day sleep trend declining ({sleep_slope:+.2f} hrs/day) with resting HR rising "
                    f"({hr_slope:+.2f} bpm/day). Risk of circadian misalignment and cognitive fatigue."
                ),
            )
        )

    if mood_slope <= -0.45 and latest_mood <= 6:
        sev = "critical" if latest_mood <= 3 else "caution"
        alerts.append(
            TrendAlert(
                code="isolation_behavioral_fatigue",
                title="Isolation & Mood Decline",
                severity=sev,
                metric="mood_score",
                slope_per_day=round(mood_slope, 3),
                affected_zones=["brain_cognition"],
                message=(
                    f"Behavioral mood score shows steady 5-day decline ({mood_slope:+.2f} pts/day; current {latest_mood}/10)."
                ),
            )
        )

    if glucose_slope >= 3.5 and latest_glucose >= 115.0:
        sev = "critical" if latest_glucose > 145.0 else "caution"
        alerts.append(
            TrendAlert(
                code="metabolic_glucose_drift",
                title="Metabolic Glucose Drift",
                severity=sev,
                metric="blood_glucose_mg_dl",
                slope_per_day=round(glucose_slope, 3),
                affected_zones=["kidneys_fluid", "bones_spine"],
                message=(
                    f"Upward blood glucose trend ({glucose_slope:+.2f} mg/dL per day; current {latest_glucose:.0f} mg/dL). "
                    "Monitor nutrition, fluid intake, and resistance exercise."
                ),
            )
        )

    return alerts


def evaluate_risk(
    conn: sqlite3.Connection,
    environment_override: EnvironmentType | None = None,
    include_latest_vision: bool = True,
) -> RiskEvaluationResponse:
    """Compute holistic risk evaluation across static thresholds, trends, fault state, and CV."""
    rules = load_nasa_rules(str(settings.data_dir))
    state_row = conn.execute("SELECT * FROM mission_state WHERE id = 1;").fetchone()
    if state_row is None:
        raise RuntimeError("Database is not initialized with mission_state.")

    env: EnvironmentType = environment_override or state_row["current_environment"]
    active_fault: str | None = state_row["active_fault"]
    thresholds = get_thresholds_for_env(env)

    rows = conn.execute(
        """
        SELECT * FROM (
            SELECT * FROM health_metrics
            ORDER BY mission_day DESC, id DESC
            LIMIT 60
        ) sub
        ORDER BY mission_day ASC, id ASC;
        """,)
    records = [dict(r) for r in rows]
    latest = records[-1] if records else None

    metric_severities: dict[str, SeverityStatus] = {}
    metric_values: dict[str, float] = {}
    caution_metrics: list[str] = []
    critical_metrics: list[str] = []

    if latest is not None:
        metric_values = {
            "heart_rate": float(latest["heart_rate"]),
            "systolic_bp": float(latest["systolic_bp"]),
            "diastolic_bp": float(latest["diastolic_bp"]),
            "blood_glucose_mg_dl": float(latest["blood_glucose_mg_dl"]),
            "temperature_c": float(latest["temperature_c"]),
            "sleep_hours": float(latest["sleep_hours"]),
            "mood_score": float(latest["mood_score"]),
            "radiation_msv_daily": float(latest["radiation_msv"]),
        }
        for key, val in metric_values.items():
            sev = _classify_metric(val, thresholds[key])
            metric_severities[key] = sev
            if sev == "caution":
                caution_metrics.append(key)
            elif sev == "critical":
                critical_metrics.append(key)

    trend_alerts = compute_trends(records)

    # Prepare 8 body zones
    zone_map: dict[str, dict[str, Any]] = {}
    for z in rules["body_zones"]:
        zone_map[z["zone_id"]] = {
            "zone_id": z["zone_id"],
            "layer": z["layer"],
            "label": z["label"],
            "status": "nominal",
            "summary": z["default_summary"],
            "space_hazard": z["space_hazard"],
            "self_exam_guide": z["self_exam_guide"],
            "organ_function": z.get("organ_function"),
            "why_exam_needed": z.get("why_exam_needed"),
            "hrp_risk_name": z.get("hrp_risk_name"),
            "reference_title": z.get("reference_title"),
            "reference_url": z.get("reference_url"),
            "_reasons": [],
        }

    # Propagate metric deviations to body zones
    for metric_key, sev in metric_severities.items():
        if sev == "nominal":
            continue
        label = thresholds[metric_key].label
        unit = thresholds[metric_key].unit
        val = metric_values[metric_key]
        for z_id in METRIC_TO_ZONES.get(metric_key, []):
            if z_id in zone_map:
                zone_map[z_id]["status"] = _max_severity(zone_map[z_id]["status"], sev)
                zone_map[z_id]["_reasons"].append(f"{label} {sev} ({val} {unit})")

    # Propagate trend alerts to body zones
    for alert in trend_alerts:
        for z_id in alert.affected_zones:
            if z_id in zone_map:
                zone_map[z_id]["status"] = _max_severity(zone_map[z_id]["status"], alert.severity)
                zone_map[z_id]["_reasons"].append(alert.title)

    # Propagate active demo fault context
    if active_fault and active_fault in FAULT_CONTEXT:
        fc = FAULT_CONTEXT[active_fault]
        for z_id, f_sev in fc["zones"].items():
            if z_id in zone_map:
                zone_map[z_id]["status"] = _max_severity(zone_map[z_id]["status"], f_sev)
                zone_map[z_id]["_reasons"].append(fc["hazard"])

    # Propagate latest vision assessment if enabled
    latest_vision_row = None
    latest_vision_summary = None
    vision_sev: SeverityStatus = "nominal"
    if include_latest_vision:
        latest_vision_row = conn.execute(
            "SELECT * FROM vision_assessments ORDER BY id DESC LIMIT 1;"
        ).fetchone()
        if latest_vision_row is not None:
            latest_vision_summary = latest_vision_row["summary"]
            v_sev = latest_vision_row["severity"]
            if v_sev in ("nominal", "caution", "critical"):
                vision_sev = v_sev
            try:
                affected = json.loads(latest_vision_row["affected_zones_json"])
            except Exception:
                affected = []
            if vision_sev != "nominal":
                for z_id in affected:
                    if z_id in zone_map:
                        zone_map[z_id]["status"] = _max_severity(zone_map[z_id]["status"], vision_sev)
                        zone_map[z_id]["_reasons"].append(
                            f"Vision ({latest_vision_row['mode']}): {vision_sev}"
                        )

    body_zones: list[BodyZoneStatus] = []
    for z in rules["body_zones"]:
        item = zone_map[z["zone_id"]]
        if item["_reasons"]:
            unique_reasons = list(dict.fromkeys(item["_reasons"]))
            item["summary"] = "; ".join(unique_reasons) + "."
        body_zones.append(
            BodyZoneStatus(
                zone_id=item["zone_id"],
                layer=item["layer"],
                label=item["label"],
                status=item["status"],
                summary=item["summary"],
                space_hazard=item["space_hazard"],
                self_exam_guide=item["self_exam_guide"],
                organ_function=item["organ_function"],
                why_exam_needed=item["why_exam_needed"],
                hrp_risk_name=item["hrp_risk_name"],
                reference_title=item["reference_title"],
                reference_url=item["reference_url"],
            )
        )

    # Determine overall severity & 3-tier escalation per ARCHITECTURE.md Section 5
    overall_severity: SeverityStatus = "nominal"
    for z in body_zones:
        overall_severity = _max_severity(overall_severity, z.status)

    has_critical_vision = vision_sev == "critical"
    has_caution_vision = vision_sev == "caution"

    if (
        critical_metrics
        or active_fault == "solar_flare"
        or has_critical_vision
        or any(a.severity == "critical" for a in trend_alerts)
        or overall_severity == "critical"
    ):
        escalation_level: EscalationLevel = "flight_surgeon"
    elif (
        len(caution_metrics) >= 2
        or has_caution_vision
        or len(trend_alerts) >= 1
        or active_fault in ("co2_drift", "sleep_deficit")
        or sum(1 for z in body_zones if z.status == "caution") >= 2
    ):
        escalation_level = "crew_attention"
    else:
        escalation_level = "self_care"

    # Compute Readiness Score dynamically from baseline 84 + completed routine bonus - risk penalties
    completed_points_row = conn.execute(
        "SELECT COALESCE(SUM(points), 0) AS pts FROM routine_tasks WHERE completed = 1;"
    ).fetchone()
    completed_bonus = int(completed_points_row["pts"]) if completed_points_row else 0

    penalty = (
        len(caution_metrics) * 5
        + len(critical_metrics) * 14
        + len(trend_alerts) * 6
        + (12 if vision_sev == "caution" else (22 if vision_sev == "critical" else 0))
    )
    if active_fault == "solar_flare":
        penalty = max(penalty, 26)
    elif active_fault == "co2_drift":
        penalty = max(penalty, 13)
    elif active_fault == "sleep_deficit":
        penalty = max(penalty, 20)

    readiness_score = max(5, min(100, 84 + completed_bonus - penalty))
    conn.execute(
        "UPDATE mission_state SET readiness_score = ? WHERE id = 1;",
        (readiness_score,),
    )

    # Build human-friendly explanation & action steps
    if active_fault and active_fault in FAULT_CONTEXT:
        fc = FAULT_CONTEXT[active_fault]
        what_happened = fc["summary"]
        space_hazard_link = fc["hazard"]
        action_steps = list(fc["steps"])
    elif overall_severity == "nominal" and not trend_alerts:
        env_label = rules["environments"][env]["label"]
        what_happened = (
            f"All vital signs and multi-day trends remain within space-adjusted baselines for {env_label}."
        )
        space_hazard_link = "Nominal Spaceflight Operations (NASA HRP 5 Hazards monitored)"
        action_steps = [
            "Continue scheduled ARED resistive exercise and hydration routine.",
            "Log morning glucose and evening sleep/mood check-in to maintain streak.",
        ]
    else:
        issues = [thresholds[m].label for m in critical_metrics + caution_metrics]
        trend_titles = [a.title for a in trend_alerts]
        combined = ", ".join(dict.fromkeys(issues + trend_titles)) or "Vision/telemetry anomaly"
        what_happened = (
            f"Detected spaceflight physiological deviation involving: {combined}."
        )
        space_hazard_link = "NASA HRP Combined Hazards (Fluid Shift / Closed Environment / Radiation)"
        action_steps = [
            "Re-measure flagged vital signs after 10 minutes at rest to confirm persistence.",
            "Verify cabin atmosphere (CO2/humidity) and CSA radiation dosimeter status.",
        ]
        if escalation_level == "crew_attention":
            action_steps.append("Notify crew partner to perform guided cross-check or assist with ultrasound.")
        elif escalation_level == "flight_surgeon":
            action_steps.append("Use Transmit to Ground to package telemetry for Flight Surgeon review.")

    return RiskEvaluationResponse(
        environment=env,
        overall_severity=overall_severity,
        readiness_score=readiness_score,
        escalation_level=escalation_level,
        what_happened_and_why=what_happened,
        space_hazard_link=space_hazard_link,
        action_steps=action_steps,
        flagged_metrics={
            k: v for k, v in metric_severities.items() if v != "nominal"
        },
        trend_alerts=trend_alerts,
        body_zones=body_zones,
        latest_vision_summary=latest_vision_summary,
        official_references=rules.get("official_resources", []),
    )
