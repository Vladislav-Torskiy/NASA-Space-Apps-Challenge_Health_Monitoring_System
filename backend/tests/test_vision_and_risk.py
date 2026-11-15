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

from app.services import vision_service


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
        "[\"not\", \"a\", \"dict\"]",
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
        data={"mode": "skin_eye", "environment": "spacecraft", "context_notes": "routine skin check"},
    )
    assert r_neutral.status_code == 200
    b_neutral = r_neutral.json()
    assert b_neutral["severity"] == "nominal"
    assert b_neutral["escalation_level"] == "self_care"

    red_png = _encode_png(_make_erythema_skin_image())
    r_red = client.post(
        "/api/vision/analyze",
        files={"image": ("red.png", red_png, "image/png")},
        data={"mode": "skin_eye", "environment": "spacecraft", "context_notes": "redness on forearm"},
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
