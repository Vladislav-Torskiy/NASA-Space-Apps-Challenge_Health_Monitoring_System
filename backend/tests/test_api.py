"""End-to-end API contract tests for ASTRA-Med Core Backend (Role 2)."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    db_file = tmp_path / "test_astra_med.db"
    monkeypatch.setenv("SQLITE_DB_PATH", str(db_file))
    monkeypatch.setenv("GEMINI_API_KEY", "")

    from app.main import app

    with TestClient(app) as test_client:
        yield test_client


def test_health_and_dashboard_baseline(client: TestClient) -> None:
    health_resp = client.get("/api/health")
    assert health_resp.status_code == 200
    health = health_resp.json()
    assert health["status"] == "ok"
    assert health["mission_day"] == 24
    assert health["vision_provider"] in ("gemini_free_ready", "offline_opencv_ready")

    dash_resp = client.get("/api/dashboard")
    assert dash_resp.status_code == 200
    dash = dash_resp.json()
    assert dash["mission"]["environment"] == "spacecraft"
    assert dash["mission"]["owlt_seconds"] == 860
    assert dash["gamification"]["readiness_score"] == 84
    assert len(dash["body_zones"]) == 8
    assert all(z["status"] == "nominal" for z in dash["body_zones"])
    assert dash["latest_metrics"]["heart_rate"] == 68
    assert dash["latest_metrics"]["radiation_msv_total"] == pytest.approx(14.2, abs=0.05)
    assert len(dash["routine_tasks"]) == 4


def test_metrics_history_and_post_metric(client: TestClient) -> None:
    hist_resp = client.get("/api/metrics/history?days=30")
    assert hist_resp.status_code == 200
    hist = hist_resp.json()
    assert len(hist["records"]) == 24
    assert "heart_rate" in hist["thresholds"]
    assert hist["trend_alerts"] == []

    # Post an abnormal reading matching ARCHITECTURE.md Section 4.4
    post_resp = client.post(
        "/api/metrics",
        json={
            "heart_rate": 88,
            "systolic_bp": 134,
            "diastolic_bp": 86,
            "blood_glucose_mg_dl": 142,
            "temperature_c": 37.2,
            "sleep_hours": 5.0,
            "mood_score": 5,
            "radiation_msv_daily": 1.4,
            "notes": "Mild headache after EVA",
            "source": "manual",
        },
    )
    assert post_resp.status_code == 200
    data = post_resp.json()
    assert data["record"]["heart_rate"] == 88
    assert data["evaluation"]["overall_severity"] in ("caution", "critical")
    assert data["evaluation"]["escalation_level"] in ("crew_attention", "flight_surgeon")
    assert data["evaluation"]["readiness_score"] < 84


def test_environment_switcher(client: TestClient) -> None:
    for env, expected_owlt in [
        ("station", 1),
        ("rover", 240),
        ("base", 420),
        ("spacecraft", 860),
    ]:
        resp = client.post("/api/mission/environment", json={"environment": env})
        assert resp.status_code == 200
        body = resp.json()
        assert body["mission"]["environment"] == env
        assert body["mission"]["owlt_seconds"] == expected_owlt
        assert "heart_rate" in body["thresholds"]


def test_demo_fault_injection_and_reset(client: TestClient) -> None:
    # 1. Solar flare -> critical radiation + flight_surgeon escalation
    sf = client.post("/api/demo/fault", json={"fault": "solar_flare"})
    assert sf.status_code == 200
    sf_data = sf.json()
    assert sf_data["mission"]["active_fault"] == "solar_flare"
    assert sf_data["evaluation"]["escalation_level"] == "flight_surgeon"
    assert sf_data["evaluation"]["readiness_score"] <= 60
    zones = {z["zone_id"]: z["status"] for z in sf_data["evaluation"]["body_zones"]}
    assert zones["immune_system"] == "critical"

    # 2. CO2 drift -> caution lungs & brain
    co2 = client.post("/api/demo/fault", json={"fault": "co2_drift"})
    assert co2.status_code == 200
    co2_data = co2.json()
    assert co2_data["mission"]["active_fault"] == "co2_drift"
    assert co2_data["evaluation"]["escalation_level"] == "crew_attention"

    # 3. Sleep deficit -> multi-day circadian trend alert
    sd = client.post("/api/demo/fault", json={"fault": "sleep_deficit"})
    assert sd.status_code == 200
    sd_data = sd.json()
    assert sd_data["mission"]["active_fault"] == "sleep_deficit"
    assert any(a["code"] == "circadian_behavioral_drift" for a in sd_data["evaluation"]["trend_alerts"])

    # 4. Reset baseline -> back to clean Day 24 nominal
    rst = client.post("/api/demo/fault", json={"fault": "reset_baseline"})
    assert rst.status_code == 200
    rst_data = rst.json()
    assert rst_data["mission"]["active_fault"] is None
    assert rst_data["mission"]["mission_day"] == 24
    assert rst_data["evaluation"]["overall_severity"] == "nominal"
    assert rst_data["evaluation"]["readiness_score"] == 84


def test_routine_completion_and_ground_transmit(client: TestClient) -> None:
    # Complete task 1 -> unlocks hydration_glucose_ace & vitals_streak_7 (streak 6 -> 7)
    r_resp = client.post("/api/routine/1/complete")
    assert r_resp.status_code == 200
    r_data = r_resp.json()
    assert r_data["task"]["completed"] is True
    assert r_data["gamification"]["streak_days"] == 7
    assert "hydration_glucose_ace" in r_data["newly_unlocked_badges"]
    assert "vitals_streak_7" in r_data["newly_unlocked_badges"]
    assert r_data["gamification"]["readiness_score"] == 99

    # Non-existent task -> 404
    missing = client.post("/api/routine/999/complete")
    assert missing.status_code == 404

    # Ground transmit
    g_resp = client.post("/api/ground/transmit", json={"notes": "Routine check packet"})
    assert g_resp.status_code == 200
    g_data = g_resp.json()
    assert g_data["owlt_seconds"] == 860
    assert g_data["status"] == "Delivered (Awaiting Ground Reply)"
    assert len(g_data["status_timeline"]) == 3
    assert "ASTRA-MED TELEMETRY PACKET" in g_data["text_summary"]


def test_vision_modes_and_evaluate_risk(client: TestClient) -> None:
    import sys

    repo_root = Path(__file__).resolve().parent.parent.parent
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))

    from scripts.generate_demo_images import (
        generate_device_ocr,
        generate_skin_eye,
        generate_ultrasound,
    )

    samples_dir = Path(__file__).resolve().parent.parent.parent / "data" / "demo_samples"
    samples_dir.mkdir(parents=True, exist_ok=True)
    us_path = samples_dir / "sample_ultrasound.png"
    se_path = samples_dir / "sample_skin_eye.png"
    ocr_path = samples_dir / "sample_device_ocr.png"
    generate_ultrasound(us_path)
    generate_skin_eye(se_path)
    generate_device_ocr(ocr_path)

    # Ultrasound mode
    with us_path.open("rb") as fh:
        r_us = client.post(
            "/api/vision/analyze",
            files={"image": ("sample_ultrasound.png", fh, "image/png")},
            data={"mode": "ultrasound", "environment": "spacecraft"},
        )
    assert r_us.status_code == 200
    us_body = r_us.json()
    assert us_body["mode"] == "ultrasound"
    assert us_body["annotated_image_base64"].startswith("data:image/jpeg;base64,")
    assert len(us_body["roi_boxes"]) >= 1

    # Skin/Eye mode
    with se_path.open("rb") as fh:
        r_se = client.post(
            "/api/vision/analyze",
            files={"image": ("sample_skin_eye.png", fh, "image/png")},
            data={"mode": "skin_eye", "environment": "station", "context_notes": "Skin irritation"},
        )
    assert r_se.status_code == 200
    se_body = r_se.json()
    assert se_body["mode"] == "skin_eye"
    assert se_body["severity"] in ("caution", "critical")

    # Device OCR mode
    with ocr_path.open("rb") as fh:
        r_ocr = client.post(
            "/api/vision/analyze",
            files={"image": ("sample_device_ocr.png", fh, "image/png")},
            data={"mode": "device_ocr", "environment": "spacecraft"},
        )
    assert r_ocr.status_code == 200
    ocr_body = r_ocr.json()
    assert ocr_body["mode"] == "device_ocr"
    assert ocr_body["extracted_value"] is not None
    assert ocr_body["extracted_value"]["metric"] == "blood_glucose_mg_dl"

    # Evaluate risk endpoint
    eval_resp = client.post("/api/evaluate/risk", json={"include_latest_vision": True})
    assert eval_resp.status_code == 200
    eval_data = eval_resp.json()
    assert eval_data["latest_vision_summary"] is not None
