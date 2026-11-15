"""Hybrid AI / Computer Vision diagnostic service (Gemini Free Tier + OpenCV/Tesseract fallback)."""

from __future__ import annotations

import base64
import io
import json
import math
import re
import shutil
import sqlite3
import typing
from datetime import UTC, datetime
from typing import Any

import cv2
import numpy as np
from PIL import Image

from app.config import settings
from app.schemas import (
    EnvironmentType,
    EscalationLevel,
    ExtractedMetricValue,
    RoiBox,
    SeverityStatus,
    VisionAnalyzeResponse,
    VisionMode,
)
from app.services.risk_engine import (
    METRIC_TO_ZONES,
    _classify_metric,
    get_thresholds_for_env,
)
from app.services.routine_service import unlock_badge_if_needed

try:
    import pytesseract
except Exception:  # pragma: no cover
    pytesseract = None


def is_tesseract_available() -> bool:
    """Check whether the system tesseract binary is installed and callable."""
    return shutil.which("tesseract") is not None and pytesseract is not None


def get_vision_provider_status() -> str:
    """Report active vision provider readiness for /api/health."""
    if settings.gemini_api_key:
        return "gemini_free_ready"
    return "offline_opencv_ready"


def _decode_image(image_bytes: bytes) -> np.ndarray:
    arr = np.frombuffer(image_bytes, dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError("Uploaded file is not a valid readable image (png/jpg/webp).")
    return img


_MIN_BRIGHTNESS_MEAN = 15.0
_MAX_BRIGHTNESS_MEAN = 240.0
_MIN_LAPLACIAN_VAR_DEFAULT = 15.0
_MIN_LAPLACIAN_VAR_SKIN_EYE = 0.3
_LOW_QUALITY_MAX_CONFIDENCE = 0.42


def _check_image_quality(img: np.ndarray, mode: VisionMode) -> list[str]:
    """Check grayscale brightness and Laplacian sharpness; return list of human-readable issues."""
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    mean_brightness = float(gray.mean())
    laplacian_var = float(cv2.Laplacian(gray, cv2.CV_64F).var())

    issues: list[str] = []
    if mean_brightness < _MIN_BRIGHTNESS_MEAN:
        issues.append("too dark (underexposed)")
    elif mean_brightness > _MAX_BRIGHTNESS_MEAN:
        issues.append("overexposed (excessive brightness or glare)")

    min_lap_var = (
        _MIN_LAPLACIAN_VAR_SKIN_EYE
        if mode == "skin_eye"
        else _MIN_LAPLACIAN_VAR_DEFAULT
    )
    if laplacian_var < min_lap_var:
        issues.append("heavily blurred or out of focus")

    return issues


def _apply_quality_warnings(
    analysis: dict[str, Any],
    mode: VisionMode,
    quality_issues: list[str],
) -> dict[str, Any]:
    """Attach non-crashing quality warnings and suppress fake OCR digits on degraded frames."""
    if not quality_issues:
        return analysis

    updated = dict(analysis)
    issues_text = ", ".join(quality_issues)
    warning_prefix = f"Image quality warning: frame appears {issues_text}. "
    retake_step = (
        "Retake the image in steady focus with balanced lighting and minimal glare."
    )

    if mode == "device_ocr":
        updated["extracted_value"] = None
        updated["severity"] = "nominal"
        updated["escalation_level"] = "self_care"
        updated["explanation_simple"] = (
            f"{warning_prefix}Could not reliably read a numeric value from the medical device display. "
            "Please retake the photo closer to the screen with better lighting and sharp focus."
        )
    else:
        existing_explanation = str(updated.get("explanation_simple", "")).strip()
        if not existing_explanation.startswith("Image quality warning:"):
            updated["explanation_simple"] = f"{warning_prefix}{existing_explanation}".strip()

    existing_steps = list(updated.get("action_steps", []))
    if retake_step not in existing_steps:
        updated["action_steps"] = [retake_step, *existing_steps]

    updated["confidence"] = min(
        float(updated.get("confidence", _LOW_QUALITY_MAX_CONFIDENCE)),
        _LOW_QUALITY_MAX_CONFIDENCE,
    )
    return updated


def _encode_annotated_jpeg(img: np.ndarray, boxes: list[RoiBox], severity: SeverityStatus) -> str:
    annotated = img.copy()
    h, w = annotated.shape[:2]
    color_bgr = (
        (68, 68, 239)
        if severity == "critical"
        else (11, 158, 245)
        if severity == "caution"
        else (94, 197, 34)
    )
    for box in boxes:
        x1 = max(0, int(box.x * w))
        y1 = max(0, int(box.y * h))
        x2 = min(w - 1, int((box.x + box.w) * w))
        y2 = min(h - 1, int((box.y + box.h) * h))
        cv2.rectangle(annotated, (x1, y1), (x2, y2), color_bgr, 3)
        label_y = max(20, y1 - 8)
        cv2.putText(
            annotated,
            box.label[:38],
            (x1, label_y),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.55,
            color_bgr,
            2,
            cv2.LINE_AA,
        )

    ok, buf = cv2.imencode(".jpg", annotated, [int(cv2.IMWRITE_JPEG_QUALITY), 88])
    if not ok:
        raise RuntimeError("Failed to encode annotated image.")
    b64 = base64.b64encode(buf.tobytes()).decode("ascii")
    return f"data:image/jpeg;base64,{b64}"


def _analyze_ultrasound_opencv(img: np.ndarray) -> dict[str, Any]:
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    clahe = cv2.createCLAHE(clipLimit=2.2, tileGridSize=(8, 8))
    enhanced = clahe.apply(gray)
    h, w = enhanced.shape

    # Detect vertical B-line / bright streak density via vertical gradient & column energy
    sobel_x = np.abs(cv2.Sobel(enhanced, cv2.CV_64F, 1, 0, ksize=3))
    bright_mask = (enhanced > 140).astype(np.float32)
    vertical_energy = (sobel_x * bright_mask).mean(axis=0)

    # Focus on central sector (20%..80% width, 20%..85% height)
    c_start, c_end = int(w * 0.2), int(w * 0.8)
    r_start, r_end = int(h * 0.2), int(h * 0.85)
    roi_slice = enhanced[r_start:r_end, c_start:c_end]
    bright_fraction = float((roi_slice > 145).mean())
    col_peaks = int((vertical_energy[c_start:c_end] > vertical_energy.mean() * 1.45).sum())

    if bright_fraction > 0.14 or col_peaks >= 12:
        severity: SeverityStatus = "caution"
        escalation: EscalationLevel = "crew_attention"
        confidence = 0.82
        sector_energy = vertical_energy[c_start:c_end]
        peak_cols = np.where(sector_energy > vertical_energy.mean() * 1.45)[0]
        if len(peak_cols) == 0:
            peak_cols = np.where((roi_slice > 145).any(axis=0))[0]
        bright_rows = np.where((roi_slice > 145).any(axis=1))[0]

        if len(peak_cols) > 0 and len(bright_rows) > 0:
            pad_x, pad_y = int(w * 0.04), int(h * 0.04)
            x1 = max(0, c_start + int(peak_cols.min()) - pad_x)
            x2 = min(w, c_start + int(peak_cols.max()) + pad_x)
            y1 = max(0, r_start + int(bright_rows.min()) - pad_y)
            y2 = min(h, r_start + int(bright_rows.max()) + pad_y)
            bx = round(x1 / w, 3)
            by = round(y1 / h, 3)
            bw = round(min(1.0 - bx, max(0.12, (x2 - x1) / w)), 3)
            bh = round(min(1.0 - by, max(0.15, (y2 - y1) / h)), 3)
            boxes = [RoiBox(x=bx, y=by, w=bw, h=bh, label="B-line cluster region")]
        else:
            boxes = [RoiBox(x=0.28, y=0.24, w=0.44, h=0.52, label="B-line cluster region")]
        explanation = "Detected localized vertical ultrasound artifacts (B-line pattern) suggesting mild pulmonary fluid shift or localized congestion."
        steps = [
            "Repeat scan on both lung fields in 4 hours to verify persistence.",
            "Review cabin CO2 and daily fluid intake logs.",
            "Ask crew medical officer to inspect breathing rate and auscultation.",
        ]
    else:
        severity = "nominal"
        escalation = "self_care"
        confidence = 0.86
        boxes = [RoiBox(x=0.25, y=0.22, w=0.50, h=0.55, label="Pleural field nominal")]
        explanation = "Ultrasound acoustic profile appears uniform without prominent vertical B-line clusters or fluid accumulation."
        steps = [
            "Store baseline ultrasound frame for mission comparison.",
            "Continue routine hydration and resistive exercise countermeasures.",
        ]

    return {
        "severity": severity,
        "confidence": confidence,
        "extracted_value": None,
        "affected_body_zones": ["lungs_airway"],
        "roi_boxes": boxes,
        "space_hazard_link": "Hostile Closed Environments / Microgravity fluid shift",
        "explanation_simple": explanation,
        "action_steps": steps,
        "escalation_level": escalation,
    }


def _analyze_skin_eye_opencv(img: np.ndarray, context_notes: str) -> dict[str, Any]:
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    h, w = img.shape[:2]

    # Red hue wraps around 0 and 180 in OpenCV HSV; S>=95 avoids warm normal skin tones
    mask1 = cv2.inRange(hsv, np.array([0, 95, 60]), np.array([10, 255, 255]))
    mask2 = cv2.inRange(hsv, np.array([165, 95, 60]), np.array([180, 255, 255]))
    red_mask = cv2.bitwise_or(mask1, mask2)

    morph_kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    red_mask = cv2.morphologyEx(red_mask, cv2.MORPH_OPEN, morph_kernel)
    red_mask = cv2.morphologyEx(red_mask, cv2.MORPH_CLOSE, morph_kernel)

    erythema_ratio = float((red_mask > 0).mean())
    contours, _ = cv2.findContours(red_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    boxes: list[RoiBox] = []
    if contours:
        largest = max(contours, key=cv2.contourArea)
        area = cv2.contourArea(largest)
        if area > (h * w * 0.01):
            x, y, bw, bh = cv2.boundingRect(largest)
            boxes.append(
                RoiBox(
                    x=round(x / w, 3),
                    y=round(y / h, 3),
                    w=round(bw / w, 3),
                    h=round(bh / h, 3),
                    label="Erythema / irritation ROI",
                )
            )

    notes_lower = context_notes.lower()
    is_eye_focus = any(k in notes_lower for k in ("eye", "sans", "vision", "blur", "ocular"))
    zones = ["eyes_sans", "skin"] if is_eye_focus else ["skin", "eyes_sans"]

    if erythema_ratio >= 0.20:
        severity: SeverityStatus = "critical"
        escalation: EscalationLevel = "flight_surgeon"
        explanation = (
            f"Pronounced redness/erythema detected ({erythema_ratio * 100:.1f}% frame coverage). "
            "Could reflect severe closed-cabin dermatitis, infection, or ocular irritation."
        )
        steps = [
            "Avoid scratching or rubbing the area; cleanse gently with sterile saline wipe.",
            "Check cabin humidity and recent radiation dosimeter logs.",
            "Transmit annotated image to Flight Surgeon for teledermatology/SANS review.",
        ]
    elif erythema_ratio >= 0.05:
        severity = "caution"
        escalation = "crew_attention"
        explanation = (
            f"Moderate localized redness detected ({erythema_ratio * 100:.1f}% coverage). "
            "Commonly linked to dry closed-loop cabin air, microbiome shifts, or mild ocular strain."
        )
        steps = [
            "Apply spacecraft-approved fragrance-free barrier moisturizer or preservative-free artificial tears if ocular.",
            "Check cabin relative humidity (target 40-50%) and air filter cleanliness.",
            "Re-capture comparison photo in 12 hours and run Amsler grid check if eyes feel strained.",
        ]
    else:
        severity = "nominal"
        escalation = "self_care"
        if not boxes:
            boxes = [RoiBox(x=0.25, y=0.25, w=0.50, h=0.50, label="Inspection region nominal")]
        explanation = "No significant erythema or acute inflammation flare detected in the inspected skin/ocular frame."
        steps = [
            "Maintain routine skin hydration and eye comfort protocol.",
            "Log any itching or blurred vision symptoms manually if they appear later.",
        ]

    return {
        "severity": severity,
        "confidence": 0.81 if boxes else 0.76,
        "extracted_value": None,
        "affected_body_zones": zones,
        "roi_boxes": boxes,
        "space_hazard_link": "Hostile Closed Environments & Space Radiation / SANS",
        "explanation_simple": explanation,
        "action_steps": steps,
        "escalation_level": escalation,
    }


_OCR_METRIC_RANGES: dict[str, tuple[float, float, str]] = {
    "blood_glucose_mg_dl": (40.0, 400.0, "mg/dL"),
    "temperature_c": (34.0, 42.0, "°C"),
    "heart_rate": (60.0, 220.0, "bpm"),
    "systolic_bp": (60.0, 220.0, "mmHg"),
}


def _infer_requested_ocr_metric(context_notes: str) -> str | None:
    """Return explicit metric name from context_notes if hinted, otherwise None."""
    notes_lower = context_notes.lower()
    if "temp" in notes_lower or "celsius" in notes_lower:
        return "temperature_c"
    if any(k in notes_lower for k in ("hr", "pulse", "heart", "bpm")):
        return "heart_rate"
    if any(k in notes_lower for k in ("bp", "systolic", "pressure", "mmhg")):
        return "systolic_bp"
    if any(k in notes_lower for k in ("gluc", "sugar", "mg/dl")):
        return "blood_glucose_mg_dl"
    return None


def _extract_ocr_digits_fallback(
    img: np.ndarray, context_notes: str
) -> tuple[float | None, str, str, RoiBox]:
    upscaled = cv2.resize(img, None, fx=3, fy=3, interpolation=cv2.INTER_CUBIC)
    gray = cv2.cvtColor(upscaled, cv2.COLOR_BGR2GRAY)
    h, w = gray.shape
    roi_box = RoiBox(x=0.10, y=0.14, w=0.80, h=0.66, label="LCD display region")

    # Using clahe method because astronauts photo 
    # not always have perfect lighting
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    contrasted = clahe.apply(gray)

    # Make image more smoothed after contrast
    blurred = cv2.GaussianBlur(contrasted, (5, 5), 0)
    blurred = cv2.medianBlur(blurred, 3) 

    # Find bright/high-contrast rectangular LCD display if present
    # Using adaptive binarisation istead of UTSU because it will be real photos, 
    # OTSU is more effective for screenshots
    thresh = cv2.adaptiveThreshold(
        blurred,
        255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY,
        blockSize=31,  
        C=10           
    )
    contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    
    crop = thresh

    if contours:
        largest = max(contours, key=cv2.contourArea)
        if cv2.contourArea(largest) > (h * w * 0.15):
            x, y, bw, bh = cv2.boundingRect(largest)
            crop = gray[y : y + bh, x : x + bw]
            roi_box = RoiBox(
                x=round(x / w, 3),
                y=round(y / h, 3),
                w=round(bw / w, 3),
                h=round(bh / h, 3),
                label="Detected device display",
            )

    kernel = np.ones((2, 2), np.uint8)
    thick_text = cv2.erode(crop, kernel, iterations=1)

    inv = cv2.bitwise_not(thick_text)
    inv = cv2.morphologyEx(inv, cv2.MORPH_OPEN, kernel)
    inv = cv2.morphologyEx(inv, cv2.MORPH_CLOSE, kernel)

    clean = cv2.bitwise_not(inv)
    final = cv2.copyMakeBorder(clean, 20, 20, 20, 20, cv2.BORDER_CONSTANT, value=255)

    raw_text = ""
    if is_tesseract_available() and pytesseract is not None:
        try:
            raw_text = pytesseract.image_to_string(
                final, lang="eng", config="--psm 6 -c tessedit_char_whitelist=0123456789."
            )
        except Exception:
            raw_text = ""

    numbers = re.findall(r"\d+(?:\.\d+)?", raw_text)
    requested_metric = _infer_requested_ocr_metric(context_notes)

    for token in numbers:
        num = float(token)
        if requested_metric is not None:
            min_v, max_v, unit = _OCR_METRIC_RANGES[requested_metric]
            if min_v <= num <= max_v:
                rounded = round(num, 1) if requested_metric == "temperature_c" else round(num, 0)
                return rounded, requested_metric, unit, roi_box
        else:
            temp_min, temp_max, temp_unit = _OCR_METRIC_RANGES["temperature_c"]
            gluc_min, gluc_max, gluc_unit = _OCR_METRIC_RANGES["blood_glucose_mg_dl"]
            if temp_min <= num <= temp_max:
                return round(num, 1), "temperature_c", temp_unit, roi_box
            if gluc_min <= num <= gluc_max:
                return round(num, 0), "blood_glucose_mg_dl", gluc_unit, roi_box

    return None, "", "", roi_box


_SEVERITY_TO_ESCALATION: dict[SeverityStatus, EscalationLevel] = {
    "nominal": "self_care",
    "caution": "crew_attention",
    "critical": "flight_surgeon",
}


def evaluate_metric(
    environment: EnvironmentType,
    metric_name: str,
    val: float | None,
) -> tuple[SeverityStatus, EscalationLevel, list[str]]:
    default_zones = ["kidneys_fluid", "bones_spine"]
    if val is None or not isinstance(val, (int, float)) or not math.isfinite(val):
        return "nominal", "self_care", default_zones
    thresholds = get_thresholds_for_env(environment)
    threshold = thresholds.get(metric_name)
    if threshold is None:
        return "nominal", "self_care", default_zones
    severity = _classify_metric(val, threshold)
    escalation = _SEVERITY_TO_ESCALATION[severity]
    affected_zones = METRIC_TO_ZONES.get(metric_name, default_zones)
    return severity, escalation, affected_zones

def _analyze_device_ocr_opencv(
        img: np.ndarray, 
        context_notes: str, 
        env: EnvironmentType = "spacecraft"
    ) -> dict[str, Any]:

    val, metric_name, unit, roi_box = _extract_ocr_digits_fallback(img, context_notes)
    severity, escalation, affected_zones = evaluate_metric(environment=env, metric_name=metric_name, val=val)

    if val is None:
        extracted = None
        explanation_simple = (
            "Could not clearly read a numeric value from the medical device display. "
            "Please retake the photo closer to the screen with better lighting and no glare."
        )
        action_steps = [
            "Center the device LCD screen in the frame and avoid reflections.",
            "Retake the photo in sharper focus or enter the reading manually.",
        ]
    else:
        extracted = ExtractedMetricValue(metric=metric_name, value=val, unit=unit)
        explanation_simple = (
            f"Extracted reading {val:g} {unit} ({metric_name}) from medical device display. "
            "Review the number and click Confirm & Log to record it in your mission timeline."
        )
        action_steps = [
            "Verify the recognized reading matches your handheld meter screen.",
            "Click 'Confirm & Log' to commit the measurement and update trend risks.",
        ]

    confidence = (
        0.25
        if val is None
        else (0.88 if is_tesseract_available() else 0.79)
    )

    return {
        "severity": severity,
        "confidence": confidence,
        "extracted_value": extracted,
        "affected_body_zones": affected_zones,
        "roi_boxes": [roi_box],
        "space_hazard_link": "Distance from Earth (Autonomous Device Telemetry Capture)",
        "explanation_simple": explanation_simple,
        "action_steps": action_steps,
        "escalation_level": escalation,
    }


_SUPPORTED_GEMINI_MIME_TYPES = frozenset(
    {"image/jpeg", "image/png", "image/webp", "image/heic", "image/heif"}
)


def _prepare_gemini_image(image_bytes: bytes) -> tuple[bytes, str]:
    """Return Gemini-compatible image bytes and MIME type, re-encoding unsupported formats to JPEG."""
    with Image.open(io.BytesIO(image_bytes)) as img:
        mime_type = Image.MIME.get(img.format or "")
        if mime_type in _SUPPORTED_GEMINI_MIME_TYPES:
            return image_bytes, mime_type
        rgb_img = img.convert("RGB") if img.mode != "RGB" else img
        buf = io.BytesIO()
        rgb_img.save(buf, format="JPEG", quality=92)
        return buf.getvalue(), "image/jpeg"


def _validate_str_list(value: Any, field_name: str) -> list[str]:
    """Validate that a parsed JSON field is a list of non-empty strings."""
    if not isinstance(value, list) or not all(
        isinstance(item, str) and bool(item.strip()) for item in value
    ):
        raise ValueError(f"{field_name} must be a list of non-empty strings")
    return value


def _try_gemini_vision(
    image_bytes: bytes,
    mode: VisionMode,
    environment: EnvironmentType,
    context_notes: str,
) -> dict[str, Any] | None:
    """Call Gemini Free Tier with strict JSON output; return None cleanly on any error/timeout."""
    api_key = settings.gemini_api_key
    timeout = settings.vision_timeout_seconds
    if not api_key:
        return None
    try:
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=api_key, http_options=types.HttpOptions(timeout=int(timeout * 1000)))
        prompt = (
            "You are ASTRA-Med, an autonomous spacecraft medical decision-support assistant grounded in NASA HRP 5 Hazards. "
            f"Analyze this image in mode='{mode}' for environment='{environment}'. "
            f"Context notes: '{context_notes}'. "
            "Act strictly as Decision Support: never state definitive clinical diagnoses; use non-diagnostic phrasing such as "
            "'Detected patterns consistent with...' or 'Indicates elevated risk...'. "
            "Return strictly valid JSON with keys: "
            "severity ('nominal'|'caution'|'critical'), confidence (0..1 float), "
            "affected_body_zones (non-empty array chosen ONLY from allowed zone_ids: "
            "'heart_vessels', 'lungs_airway', 'bones_spine', 'kidneys_fluid', "
            "'skin', 'immune_system', 'brain_cognition', 'eyes_sans'), "
            "roi_boxes (array of {x,y,w,h,label} normalized 0..1), "
            "extracted_value (null, or for mode='device_ocr' an object {metric, value, unit} where metric is ONLY one of: "
            "'blood_glucose_mg_dl' with unit 'mg/dL', 'temperature_c' with unit '°C', "
            "'heart_rate' with unit 'bpm', 'systolic_bp' with unit 'mmHg'), "
            "space_hazard_link (string), explanation_simple (string), "
            "action_steps (array of 2-3 short strings), "
            "escalation_level ('self_care'|'crew_attention'|'flight_surgeon')."
        )

        prepared_bytes, mime_type = _prepare_gemini_image(image_bytes)
        response = client.models.generate_content(
            model=settings.gemini_model,
            contents=[
                types.Part.from_bytes(data=prepared_bytes, mime_type=mime_type),
                prompt,
            ],
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                temperature=0.2,
            ),
        )
        if not response.text:
            return None
        parsed = json.loads(response.text)
        if not isinstance(parsed, dict): 
            raise ValueError("Parsed json is not dict")

        roi_boxes = [RoiBox(**b) for b in parsed.get("roi_boxes", [])]
        ext = parsed.get("extracted_value")
        extracted_obj = (
            ExtractedMetricValue(**ext) if isinstance(ext, dict) and "value" in ext else None
        )

        allowed_severity = typing.get_args(SeverityStatus)
        severity = parsed.get("severity", "caution")
        if severity not in allowed_severity:
            raise ValueError("Incorrect severity")

        allowed_escalation = typing.get_args(EscalationLevel)
        escalation = parsed.get("escalation_level", "self_care")
        if escalation not in allowed_escalation:
            raise ValueError("Incorrect escalation")

        confidence = float(parsed.get("confidence", 0.85))
        if not 0 <= confidence <= 1:
            raise ValueError("Confidence out of range 0..1")

        for box in roi_boxes:
            if not (0.0 <= box.x <= 1.0 and 0.0 <= box.y <= 1.0 and 0.0 < box.w <= 1.0 and 0.0 < box.h <= 1.0):
                raise ValueError("ROI box coordinates out of [0..1] range")

        affected_body_zones = _validate_str_list(
            parsed.get("affected_body_zones", ["lungs_airway"]),
            "affected_body_zones",
        )
        action_steps = _validate_str_list(
            parsed.get("action_steps", ["Monitor and repeat check."]),
            "action_steps",
        )

        space_hazard_link = parsed.get("space_hazard_link", "NASA HRP Spaceflight Hazard")
        explanation_simple = parsed.get("explanation_simple", "Vision assessment complete.")
        if not isinstance(space_hazard_link, str) or not isinstance(explanation_simple, str):
            raise ValueError("space_hazard_link and explanation_simple must be strings")

        return {
            "severity": severity,
            "confidence": confidence,
            "extracted_value": extracted_obj,
            "affected_body_zones": affected_body_zones,
            "roi_boxes": roi_boxes,
            "space_hazard_link": space_hazard_link,
            "explanation_simple": explanation_simple,
            "action_steps": action_steps,
            "escalation_level": escalation,
        }
    except Exception:
        return None


def analyze_vision_image(
    conn: sqlite3.Connection,
    image_bytes: bytes,
    mode: VisionMode,
    environment: EnvironmentType,
    context_notes: str = "",
) -> VisionAnalyzeResponse:
    """Run hybrid Vision API + OpenCV/Tesseract pipeline, annotate image, and persist result."""
    img = _decode_image(image_bytes)
    quality_issues = _check_image_quality(img, mode)

    # 1. Try cloud Vision API if configured; fall back deterministically on offline/error/timeout
    cloud_result = _try_gemini_vision(image_bytes, mode, environment, context_notes)
    if cloud_result is not None:
        provider_used = "gemini_free"
        analysis = cloud_result
    else:
        provider_used = "opencv_fallback"
        if mode == "ultrasound":
            analysis = _analyze_ultrasound_opencv(img)
        elif mode == "skin_eye":
            analysis = _analyze_skin_eye_opencv(img, context_notes)
        elif mode == "device_ocr":
            analysis = _analyze_device_ocr_opencv(img, context_notes, environment)
        else:
            raise ValueError(f"Unsupported vision mode: {mode}")

    analysis = _apply_quality_warnings(analysis, mode, quality_issues)
    annotated_b64 = _encode_annotated_jpeg(img, analysis["roi_boxes"], analysis["severity"])

    extracted_dict = (
        analysis["extracted_value"].model_dump()
        if analysis["extracted_value"] is not None
        else None
    )
    conn.execute(
        """
        INSERT INTO vision_assessments (
            timestamp, mode, provider_used, severity, extracted_json,
            affected_zones_json, escalation_level, summary
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?);
        """,
        (
            datetime.now(UTC).replace(microsecond=0).isoformat(),
            mode,
            provider_used,
            analysis["severity"],
            json.dumps(extracted_dict) if extracted_dict else None,
            json.dumps(analysis["affected_body_zones"]),
            analysis["escalation_level"],
            analysis["explanation_simple"],
        ),
    )

    # Unlock 'autonomous_medic' badge when user runs a CV self-exam
    unlock_badge_if_needed(conn, "autonomous_medic")

    return VisionAnalyzeResponse(
        mode=mode,
        provider_used=provider_used,
        severity=analysis["severity"],
        confidence=round(float(analysis["confidence"]), 2),
        extracted_value=analysis["extracted_value"],
        affected_body_zones=analysis["affected_body_zones"],
        roi_boxes=analysis["roi_boxes"],
        annotated_image_base64=annotated_b64,
        space_hazard_link=analysis["space_hazard_link"],
        explanation_simple=analysis["explanation_simple"],
        action_steps=analysis["action_steps"],
        escalation_level=analysis["escalation_level"],
    )
