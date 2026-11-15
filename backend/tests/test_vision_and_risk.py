"""Unit and integration tests for Hybrid Vision pipeline, Zero-Crash Fallback, and OpenCV handlers (Role 3)."""

from __future__ import annotations

import json
from collections.abc import Generator
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient

from app.database import db_session
from app.services import vision_service
from app.services.risk_engine import compute_trends


@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Generator[TestClient, Any, Any]:
    db_file = tmp_path / "test_vision_risk.db"
    monkeypatch.setenv("SQLITE_DB_PATH", str(db_file))
    monkeypatch.setenv("GEMINI_API_KEY", "")

    from app.main import app

    with TestClient(app) as test_client:
        yield test_client


def _encode_png(img: np.ndarray) -> bytes:
    ok, buf = cv2.imencode(".png", img)
    assert ok
    return buf.tobytes()


def _make_neutral_skin_image() -> np.ndarray:
    """Create a warm neutral skin-tone frame with subtle texture so it is not flagged as blurred."""
    rng = np.random.default_rng(42)
    # BGR for RGB(218, 174, 152) -> (152, 174, 218)
    img = np.full((300, 400, 3), (152, 174, 218), dtype=np.int16)
    noise = rng.integers(-12, 13, size=img.shape, dtype=np.int16)
    return np.clip(img + noise, 0, 255).astype(np.uint8)


def _make_erythema_skin_image() -> np.ndarray:
    """Create a skin frame with a prominent red erythematous patch in the center."""
    img = _make_neutral_skin_image()
    # BGR for bright red RGB(224, 50, 50) -> (50, 50, 224)
    cv2.circle(img, (200, 150), 75, (50, 50, 224), thickness=-1)
    return img


def _make_clean_ultrasound_image() -> np.ndarray:
    """Create a dark ultrasound sector with mild background speckle and no vertical B-lines."""
    rng = np.random.default_rng(10)
    img = np.full((320, 420, 3), 24, dtype=np.int16)
    speckle = rng.integers(-10, 15, size=img.shape, dtype=np.int16)
    return np.clip(img + speckle, 0, 110).astype(np.uint8)


def _make_b_line_ultrasound_image() -> np.ndarray:
    """Create an ultrasound frame with bright vertical B-line artifacts in the central sector."""
    img = _make_clean_ultrasound_image()
    for x in range(140, 280, 12):
        cv2.line(img, (x, 70), (x, 270), (225, 225, 225), thickness=3)
    return img


def _make_synthetic_ocr_screen(text: str) -> np.ndarray:
    """Create a high-contrast synthetic medical device LCD screen displaying `text`."""
    img = np.full((180, 320, 3), (225, 235, 225), dtype=np.uint8)
    cv2.putText(
        img,
        text,
        (85, 110),
        cv2.FONT_HERSHEY_SIMPLEX,
        1.5,
        (15, 25, 20),
        3,
        cv2.LINE_AA,
    )
    return img


# ---------------------------------------------------------------------------
# 1. Zero-Crash Fallback Tests (Empty API Key, 429, Timeout, Malformed JSON)
# ---------------------------------------------------------------------------


def test_fallback_when_gemini_api_key_empty(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "")
    png_bytes = _encode_png(_make_b_line_ultrasound_image())

    resp = client.post(
        "/api/vision/analyze",
        files={"image": ("ultrasound.png", png_bytes, "image/png")},
        data={"mode": "ultrasound", "environment": "spacecraft"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["provider_used"] == "opencv_fallback"
    assert body["severity"] == "caution"


@pytest.mark.parametrize(
    "exc_to_raise",
    [
        RuntimeError("429 RESOURCE_EXHAUSTED: Quota exceeded for Gemini Free Tier"),
        TimeoutError("Request timed out after 7000ms"),
    ],
)
def test_fallback_on_gemini_429_and_timeout(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    exc_to_raise: Exception,
) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "test-non-empty-key")

    class _FakeModels:
        def generate_content(self, *args: Any, **kwargs: Any) -> Any:
            raise exc_to_raise

    class _FakeClient:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            self.models = _FakeModels()

    from google import genai

    monkeypatch.setattr(genai, "Client", _FakeClient)

    png_bytes = _encode_png(_make_erythema_skin_image())
    resp = client.post(
        "/api/vision/analyze",
        files={"image": ("skin.png", png_bytes, "image/png")},
        data={"mode": "skin_eye", "environment": "station", "context_notes": "rash on arm"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["provider_used"] == "opencv_fallback"
    assert body["severity"] in ("caution", "critical")


@pytest.mark.parametrize(
    "malformed_payload",
    [
        '["not", "a", "dict"]',
        json.dumps(
            {
                "severity": "invalid_severity",
                "confidence": 0.8,
                "affected_body_zones": ["lungs_airway"],
                "roi_boxes": [],
                "extracted_value": None,
                "space_hazard_link": "Hazard",
                "explanation_simple": "Test",
                "action_steps": ["Step 1"],
                "escalation_level": "self_care",
            }
        ),
        json.dumps(
            {
                "severity": "caution",
                "confidence": 0.8,
                "affected_body_zones": ["lungs_airway"],
                "roi_boxes": [],
                "extracted_value": None,
                "space_hazard_link": "Hazard",
                "explanation_simple": "Test",
                "action_steps": ["Step 1"],
                "escalation_level": "invalid_escalation",
            }
        ),
        json.dumps(
            {
                "severity": "caution",
                "confidence": 1.45,
                "affected_body_zones": ["lungs_airway"],
                "roi_boxes": [],
                "extracted_value": None,
                "space_hazard_link": "Hazard",
                "explanation_simple": "Test",
                "action_steps": ["Step 1"],
                "escalation_level": "self_care",
            }
        ),
        json.dumps(
            {
                "severity": "caution",
                "confidence": 0.8,
                "affected_body_zones": ["lungs_airway"],
                "roi_boxes": [{"x": 1.3, "y": 0.2, "w": 0.3, "h": 0.3, "label": "Out of bounds"}],
                "extracted_value": None,
                "space_hazard_link": "Hazard",
                "explanation_simple": "Test",
                "action_steps": ["Step 1"],
                "escalation_level": "self_care",
            }
        ),
        json.dumps(
            {
                "severity": "caution",
                "confidence": 0.8,
                "affected_body_zones": "lungs_airway_not_a_list",
                "roi_boxes": [],
                "extracted_value": None,
                "space_hazard_link": "Hazard",
                "explanation_simple": "Test",
                "action_steps": ["Step 1"],
                "escalation_level": "self_care",
            }
        ),
    ],
)
def test_fallback_on_malformed_gemini_json(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    malformed_payload: str,
) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "test-non-empty-key")

    class _FakeModels:
        def generate_content(self, *args: Any, **kwargs: Any) -> Any:
            return SimpleNamespace(text=malformed_payload)

    class _FakeClient:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            self.models = _FakeModels()

    from google import genai

    monkeypatch.setattr(genai, "Client", _FakeClient)

    png_bytes = _encode_png(_make_b_line_ultrasound_image())
    resp = client.post(
        "/api/vision/analyze",
        files={"image": ("ultrasound.png", png_bytes, "image/png")},
        data={"mode": "ultrasound", "environment": "spacecraft"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["provider_used"] == "opencv_fallback"
    assert body["mode"] == "ultrasound"


# ---------------------------------------------------------------------------
# 2. OpenCV Synthetic Image Tests (skin_eye, ultrasound, quality, device_ocr)
# ---------------------------------------------------------------------------


def test_skin_eye_red_vs_neutral_synthetic(client: TestClient) -> None:
    neutral_png = _encode_png(_make_neutral_skin_image())
    r_neutral = client.post(
        "/api/vision/analyze",
        files={"image": ("neutral.png", neutral_png, "image/png")},
        data={
            "mode": "skin_eye",
            "environment": "spacecraft",
            "context_notes": "routine skin check",
        },
    )
    assert r_neutral.status_code == 200
    b_neutral = r_neutral.json()
    assert b_neutral["severity"] == "nominal"
    assert b_neutral["escalation_level"] == "self_care"

    red_png = _encode_png(_make_erythema_skin_image())
    r_red = client.post(
        "/api/vision/analyze",
        files={"image": ("red.png", red_png, "image/png")},
        data={
            "mode": "skin_eye",
            "environment": "spacecraft",
            "context_notes": "redness on forearm",
        },
    )
    assert r_red.status_code == 200
    b_red = r_red.json()
    assert b_red["severity"] in ("caution", "critical")
    assert b_red["escalation_level"] in ("crew_attention", "flight_surgeon")
    assert len(b_red["roi_boxes"]) == 1
    assert b_red["roi_boxes"][0]["label"] == "Erythema / irritation ROI"


def test_ultrasound_b_lines_vs_clean_synthetic(client: TestClient) -> None:
    clean_png = _encode_png(_make_clean_ultrasound_image())
    r_clean = client.post(
        "/api/vision/analyze",
        files={"image": ("clean_us.png", clean_png, "image/png")},
        data={"mode": "ultrasound", "environment": "spacecraft"},
    )
    assert r_clean.status_code == 200
    b_clean = r_clean.json()
    assert b_clean["severity"] == "nominal"
    assert b_clean["escalation_level"] == "self_care"

    blines_png = _encode_png(_make_b_line_ultrasound_image())
    r_blines = client.post(
        "/api/vision/analyze",
        files={"image": ("blines_us.png", blines_png, "image/png")},
        data={"mode": "ultrasound", "environment": "spacecraft"},
    )
    assert r_blines.status_code == 200
    b_blines = r_blines.json()
    assert b_blines["severity"] == "caution"
    assert b_blines["escalation_level"] == "crew_attention"
    box = b_blines["roi_boxes"][0]
    assert box["label"] == "B-line cluster region"
    assert (box["x"], box["y"], box["w"], box["h"]) != (0.28, 0.24, 0.44, 0.52)


def test_low_quality_dark_and_blurry_frames(client: TestClient) -> None:
    # 1. Pitch-dark image on device_ocr -> 200 OK, quality warning, extracted_value is None
    dark_img = np.zeros((200, 300, 3), dtype=np.uint8)
    dark_png = _encode_png(dark_img)
    r_dark = client.post(
        "/api/vision/analyze",
        files={"image": ("dark.png", dark_png, "image/png")},
        data={"mode": "device_ocr", "environment": "spacecraft"},
    )
    assert r_dark.status_code == 200
    b_dark = r_dark.json()
    assert b_dark["extracted_value"] is None
    assert b_dark["confidence"] <= 0.42
    assert b_dark["explanation_simple"].startswith("Image quality warning:")
    assert any("Retake the image" in step for step in b_dark["action_steps"])

    # 2. Heavily blurred frame on ultrasound -> 200 OK, quality warning in explanation_simple
    blurry_img = np.full((240, 320, 3), 90, dtype=np.uint8)
    cv2.circle(blurry_img, (160, 120), 60, (110, 110, 110), thickness=-1)
    blurry_img = cv2.GaussianBlur(blurry_img, (51, 51), 25)
    blurry_png = _encode_png(blurry_img)
    r_blur = client.post(
        "/api/vision/analyze",
        files={"image": ("blur.png", blurry_png, "image/png")},
        data={"mode": "ultrasound", "environment": "spacecraft"},
    )
    assert r_blur.status_code == 200
    b_blur = r_blur.json()
    assert "heavily blurred or out of focus" in b_blur["explanation_simple"]
    assert b_blur["confidence"] <= 0.42


def test_device_ocr_synthetic_screen_and_medical_range_validation(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    screen_img = _make_synthetic_ocr_screen("138")
    screen_png = _encode_png(screen_img)

    # Valid reading on synthetic screen
    r_ok = client.post(
        "/api/vision/analyze",
        files={"image": ("screen.png", screen_png, "image/png")},
        data={"mode": "device_ocr", "environment": "spacecraft", "context_notes": "glucose"},
    )
    assert r_ok.status_code == 200
    b_ok = r_ok.json()
    assert b_ok["extracted_value"] is not None
    assert b_ok["extracted_value"]["metric"] == "blood_glucose_mg_dl"
    assert b_ok["extracted_value"]["value"] == 138.0
    assert b_ok["severity"] == "caution"

    # Out-of-range readings (e.g. 250 for temperature, 380 for heart_rate, 550 for glucose) -> rejected
    if vision_service.pytesseract is not None:
        for bad_text, notes in [("250", "temperature"), ("380", "heart rate"), ("550", "glucose")]:
            monkeypatch.setattr(
                vision_service.pytesseract,
                "image_to_string",
                lambda *_a, _t=bad_text, **_kw: _t,
            )
            r_bad = client.post(
                "/api/vision/analyze",
                files={"image": ("screen.png", screen_png, "image/png")},
                data={"mode": "device_ocr", "environment": "spacecraft", "context_notes": notes},
            )
            assert r_bad.status_code == 200
            b_bad = r_bad.json()
            assert b_bad["extracted_value"] is None
            assert b_bad["confidence"] == 0.25


# ---------------------------------------------------------------------------
# 3. Risk Engine & NASA HRP Rules Tests (Task 6)
# ---------------------------------------------------------------------------


def _make_daily_record(
    mission_day: int,
    *,
    heart_rate: float = 68.0,
    systolic_bp: float = 118.0,
    diastolic_bp: float = 76.0,
    blood_glucose_mg_dl: float = 94.0,
    temperature_c: float = 36.7,
    sleep_hours: float = 6.8,
    mood_score: int = 8,
    radiation_msv: float = 0.59,
) -> dict[str, Any]:
    return {
        "mission_day": mission_day,
        "heart_rate": heart_rate,
        "systolic_bp": systolic_bp,
        "diastolic_bp": diastolic_bp,
        "blood_glucose_mg_dl": blood_glucose_mg_dl,
        "temperature_c": temperature_c,
        "sleep_hours": sleep_hours,
        "mood_score": mood_score,
        "radiation_msv": radiation_msv,
    }


def _insert_metric_row(conn: Any, rec: dict[str, Any], *, environment: str = "spacecraft") -> None:
    conn.execute(
        """
        INSERT INTO health_metrics (
            timestamp, mission_day, environment, heart_rate, systolic_bp, diastolic_bp,
            blood_glucose_mg_dl, temperature_c, sleep_hours, mood_score, radiation_msv, source, notes
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
        """,
        (
            f"2026-11-{min(28, rec['mission_day']):02d}T12:00:00+00:00",
            rec["mission_day"],
            environment,
            rec["heart_rate"],
            rec["systolic_bp"],
            rec["diastolic_bp"],
            rec["blood_glucose_mg_dl"],
            rec["temperature_c"],
            rec["sleep_hours"],
            rec["mood_score"],
            rec["radiation_msv"],
            "test_seed",
            "synthetic risk test",
        ),
    )


def test_risk_trend_circadian_behavioral_drift(client: TestClient) -> None:
    # 5-day sleep decline + resting HR rise triggers circadian_behavioral_drift even without critical points
    sleep_seq = [6.8, 6.3, 5.9, 5.5, 5.1]
    hr_seq = [68.0, 71.0, 74.0, 77.0, 80.0]
    records = [
        _make_daily_record(day, sleep_hours=sleep_h, heart_rate=hr, mood_score=7)
        for day, sleep_h, hr in zip(range(1, 6), sleep_seq, hr_seq, strict=True)
    ]
    alerts = compute_trends(records)
    circadian = [a for a in alerts if a.code == "circadian_behavioral_drift"]
    assert len(circadian) == 1
    assert circadian[0].severity == "caution"
    assert circadian[0].slope_per_day < -0.25
    assert circadian[0].affected_zones == ["brain_cognition", "eyes_sans", "heart_vessels"]

    # Verify integration through SQLite + /api/evaluate/risk
    assert client.get("/api/health").status_code == 200
    with db_session() as conn:
        for offset, (sleep_h, hr) in enumerate(zip(sleep_seq, hr_seq, strict=True), start=1):
            _insert_metric_row(
                conn,
                _make_daily_record(24 + offset, sleep_hours=sleep_h, heart_rate=hr, mood_score=7),
            )
        conn.execute("UPDATE mission_state SET mission_day = 29 WHERE id = 1;")

    eval_resp = client.post("/api/evaluate/risk", json={"include_latest_vision": False})
    assert eval_resp.status_code == 200
    body = eval_resp.json()
    assert any(a["code"] == "circadian_behavioral_drift" for a in body["trend_alerts"])
    assert body["escalation_level"] == "crew_attention"
    zones = {z["zone_id"]: z["status"] for z in body["body_zones"]}
    assert zones["brain_cognition"] == "caution"
    assert zones["eyes_sans"] == "caution"
    assert zones["heart_vessels"] == "caution"


def test_risk_trend_metabolic_glucose_drift(client: TestClient) -> None:
    glucose_caution = [95.0, 100.0, 106.0, 112.0, 118.0, 124.0, 130.0]
    records_caution = [
        _make_daily_record(day, blood_glucose_mg_dl=g)
        for day, g in enumerate(glucose_caution, start=1)
    ]
    alerts_caution = compute_trends(records_caution)
    metabolic_caution = [a for a in alerts_caution if a.code == "metabolic_glucose_drift"]
    assert len(metabolic_caution) == 1
    assert metabolic_caution[0].severity == "caution"
    assert metabolic_caution[0].slope_per_day >= 3.5
    assert metabolic_caution[0].affected_zones == ["kidneys_fluid", "bones_spine"]

    # Exceeding 145 mg/dL escalates the trend alert to critical
    glucose_critical = [95.0, 102.0, 110.0, 118.0, 127.0, 138.0, 150.0]
    records_critical = [
        _make_daily_record(day, blood_glucose_mg_dl=g)
        for day, g in enumerate(glucose_critical, start=1)
    ]
    alerts_critical = compute_trends(records_critical)
    metabolic_critical = [a for a in alerts_critical if a.code == "metabolic_glucose_drift"]
    assert len(metabolic_critical) == 1
    assert metabolic_critical[0].severity == "critical"

    # End-to-end check via /api/evaluate/risk
    assert client.get("/api/health").status_code == 200
    with db_session() as conn:
        for offset, g in enumerate(glucose_caution, start=1):
            _insert_metric_row(
                conn,
                _make_daily_record(24 + offset, blood_glucose_mg_dl=g),
            )
        conn.execute("UPDATE mission_state SET mission_day = 31 WHERE id = 1;")

    eval_resp = client.post("/api/evaluate/risk", json={"include_latest_vision": False})
    assert eval_resp.status_code == 200
    body = eval_resp.json()
    assert any(a["code"] == "metabolic_glucose_drift" for a in body["trend_alerts"])
    zones = {z["zone_id"]: z["status"] for z in body["body_zones"]}
    assert zones["kidneys_fluid"] == "caution"
    assert zones["bones_spine"] == "caution"


def test_multiple_measurements_per_mission_day_do_not_break_trends(client: TestClient) -> None:
    # 6 records across only 2 distinct mission days must not trigger 5-day trend alerts
    same_day_records = [
        _make_daily_record(1, sleep_hours=7.5, heart_rate=65.0),
        _make_daily_record(1, sleep_hours=6.5, heart_rate=70.0),
        _make_daily_record(1, sleep_hours=5.5, heart_rate=75.0),
        _make_daily_record(2, sleep_hours=5.0, heart_rate=80.0),
        _make_daily_record(2, sleep_hours=4.5, heart_rate=85.0),
        _make_daily_record(2, sleep_hours=4.0, heart_rate=90.0),
    ]
    assert compute_trends(same_day_records) == []

    # Extra intra-day measurements on the final day must not change the daily slope_per_day
    base_5_days = [
        _make_daily_record(day, sleep_hours=s, heart_rate=hr, mood_score=7)
        for day, s, hr in zip(
            range(1, 6),
            [7.0, 6.6, 6.2, 5.8, 5.4],
            [68.0, 71.0, 74.0, 77.0, 80.0],
            strict=True,
        )
    ]
    with_intraday = [
        *base_5_days,
        _make_daily_record(5, sleep_hours=5.4, heart_rate=80.0, mood_score=7),
        _make_daily_record(5, sleep_hours=5.4, heart_rate=80.0, mood_score=7),
        _make_daily_record(5, sleep_hours=5.4, heart_rate=80.0, mood_score=7),
    ]
    base_alert = compute_trends(base_5_days)[0]
    intraday_alert = compute_trends(with_intraday)[0]
    assert base_alert.code == intraday_alert.code == "circadian_behavioral_drift"
    assert base_alert.slope_per_day == intraday_alert.slope_per_day == pytest.approx(-0.4, abs=1e-3)

    # Posting multiple nominal readings on Day 24 via API must produce zero trend alerts
    for _ in range(4):
        post_resp = client.post(
            "/api/metrics",
            json={
                "heart_rate": 68,
                "systolic_bp": 118,
                "diastolic_bp": 76,
                "blood_glucose_mg_dl": 94,
                "temperature_c": 36.7,
                "sleep_hours": 6.8,
                "mood_score": 8,
                "radiation_msv_daily": 0.59,
                "notes": "Intra-day repeat check",
                "source": "manual",
            },
        )
        assert post_resp.status_code == 200
        assert post_resp.json()["evaluation"]["trend_alerts"] == []


def test_evaluate_risk_with_over_60_records_uses_newest_record(client: TestClient) -> None:
    assert client.get("/api/health").status_code == 200
    with db_session() as conn:
        for day in range(25, 70):
            _insert_metric_row(conn, _make_daily_record(day))
        _insert_metric_row(
            conn,
            _make_daily_record(70, heart_rate=115.0, radiation_msv=3.2),
        )
        conn.execute("UPDATE mission_state SET mission_day = 70 WHERE id = 1;")
        total_rows = conn.execute("SELECT COUNT(*) AS cnt FROM health_metrics;").fetchone()["cnt"]
        assert total_rows == 70

    eval_resp = client.post("/api/evaluate/risk", json={"include_latest_vision": False})
    assert eval_resp.status_code == 200
    body = eval_resp.json()
    assert body["overall_severity"] == "critical"
    assert body["escalation_level"] == "flight_surgeon"
    assert body["flagged_metrics"]["heart_rate"] == "critical"
    assert body["flagged_metrics"]["radiation_msv_daily"] == "critical"


def test_environment_switch_rover_vs_spacecraft_changes_evaluation(client: TestClient) -> None:
    eva_metrics = {
        "heart_rate": 105,
        "systolic_bp": 135,
        "diastolic_bp": 84,
        "blood_glucose_mg_dl": 120,
        "temperature_c": 37.5,
        "sleep_hours": 6.5,
        "mood_score": 7,
        "radiation_msv_daily": 0.8,
        "notes": "EVA exertion telemetry",
        "source": "manual",
    }
    post_resp = client.post("/api/metrics", json=eva_metrics)
    assert post_resp.status_code == 200
    eval_spacecraft = post_resp.json()["evaluation"]
    assert eval_spacecraft["environment"] == "spacecraft"
    assert eval_spacecraft["overall_severity"] == "critical"
    assert eval_spacecraft["escalation_level"] == "flight_surgeon"
    assert eval_spacecraft["flagged_metrics"]["heart_rate"] == "critical"

    switch_resp = client.post("/api/mission/environment", json={"environment": "rover"})
    assert switch_resp.status_code == 200
    eval_rover = switch_resp.json()["evaluation"]
    assert eval_rover["environment"] == "rover"
    assert eval_rover["overall_severity"] == "nominal"
    assert eval_rover["escalation_level"] == "self_care"
    assert eval_rover["flagged_metrics"] == {}
    assert eval_rover["readiness_score"] > eval_spacecraft["readiness_score"]


def test_multifactor_temperature_and_radiation_synergy(client: TestClient) -> None:
    # Both temperature (37.5 C) and radiation (1.8 mSv/day) are only caution individually in spacecraft,
    # yet together they elevate immune_system to critical and skin to caution via NASA HRP/CSA synergy.
    post_resp = client.post(
        "/api/metrics",
        json={
            "heart_rate": 72,
            "systolic_bp": 120,
            "diastolic_bp": 78,
            "blood_glucose_mg_dl": 96,
            "temperature_c": 37.5,
            "sleep_hours": 6.8,
            "mood_score": 8,
            "radiation_msv_daily": 1.8,
            "notes": "Post-transit mild fever and elevated dosimeter reading",
            "source": "manual",
        },
    )
    assert post_resp.status_code == 200
    evaluation = post_resp.json()["evaluation"]
    assert evaluation["flagged_metrics"] == {
        "temperature_c": "caution",
        "radiation_msv_daily": "caution",
    }
    zones = {z["zone_id"]: z for z in evaluation["body_zones"]}
    assert zones["immune_system"]["status"] == "critical"
    assert zones["skin"]["status"] == "caution"
    assert "immune-radiation synergy" in zones["immune_system"]["summary"]
    assert evaluation["overall_severity"] == "critical"
    assert evaluation["escalation_level"] == "flight_surgeon"

    explanation = evaluation["what_happened_and_why"]
    assert "Detected spaceflight physiological deviation involving:" in explanation
    assert "Indicates elevated risk of compounded immune-radiation response" in explanation
    assert "definitely" not in explanation.lower()
    assert "diagnosis" not in explanation.lower()
    assert any("CSA radiation dosimeter" in step for step in evaluation["action_steps"])


def test_ultrasound_multi_organ_context_routing(client: TestClient) -> None:
    us_bytes = _encode_png(_make_b_line_ultrasound_image())

    cases = [
        ("cardiac echo", "heart_vessels", "Cardiac chamber / septal ROI"),
        ("kidney renal", "kidneys_fluid", "Renal pelvis / echogenic focus ROI"),
        ("ocular sans", "eyes_sans", "Optic nerve sheath (ONSD) ROI"),
    ]
    for notes, expected_zone, expected_label in cases:
        resp = client.post(
            "/api/vision/analyze",
            files={"image": ("scan.png", us_bytes, "image/png")},
            data={"mode": "ultrasound", "environment": "spacecraft", "context_notes": notes},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["provider_used"] == "opencv_fallback"
        assert body["affected_body_zones"] == [expected_zone]
        assert body["roi_boxes"][0]["label"] == expected_label

    # Filename fallback when context_notes is empty
    fname_resp = client.post(
        "/api/vision/analyze",
        files={"image": ("apical_heart_echo.png", us_bytes, "image/png")},
        data={"mode": "ultrasound", "environment": "spacecraft"},
    )
    assert fname_resp.status_code == 200
    assert fname_resp.json()["affected_body_zones"] == ["heart_vessels"]

    # Visual auto-detection of chambered cardiac echocardiogram without organ keywords
    cardiac_img = np.full((240, 240, 3), 10, dtype=np.uint8)
    cv2.rectangle(cardiac_img, (65, 25), (175, 65), (220, 220, 220), thickness=-1)
    cv2.line(cardiac_img, (65, 110), (175, 110), (225, 225, 225), thickness=8)
    cv2.line(cardiac_img, (120, 65), (120, 175), (210, 210, 210), thickness=6)
    auto_resp = client.post(
        "/api/vision/analyze",
        files={"image": ("scan.png", _encode_png(cardiac_img), "image/png")},
        data={"mode": "ultrasound", "environment": "spacecraft"},
    )
    assert auto_resp.status_code == 200
    assert auto_resp.json()["affected_body_zones"] == ["heart_vessels"]


def test_partial_metrics_post_from_device_ocr(client: TestClient) -> None:
    empty_resp = client.post(
        "/api/metrics",
        json={"source": "device_ocr", "notes": "No metrics provided"},
    )
    assert empty_resp.status_code == 400

    ocr_resp = client.post(
        "/api/metrics",
        json={
            "blood_glucose_mg_dl": 138,
            "source": "device_ocr",
            "notes": "Confirmed via Device OCR (138 mg/dL)",
        },
    )
    assert ocr_resp.status_code == 200
    data = ocr_resp.json()
    assert data["record"]["blood_glucose_mg_dl"] == 138
    assert data["record"]["heart_rate"] == 68
    assert data["record"]["source"] == "device_ocr"
    assert data["evaluation"]["flagged_metrics"]["blood_glucose_mg_dl"] == "caution"
