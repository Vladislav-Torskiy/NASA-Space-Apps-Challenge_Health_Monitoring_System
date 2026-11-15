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

    min_lap_var = _MIN_LAPLACIAN_VAR_SKIN_EYE if mode == "skin_eye" else _MIN_LAPLACIAN_VAR_DEFAULT
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
    retake_step = "Retake the image in steady focus with balanced lighting and minimal glare."

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


_ULTRASOUND_ORGAN_PROFILES: list[tuple[tuple[str, ...], dict[str, Any]]] = [
    (
        ("heart", "cardiac", "echo", "ventricle", "atrium", "apical", "pericard"),
        {
            "zones": ["heart_vessels"],
            "hazard": "Gravity Fields (Cephalad Fluid Shift & Cardiac Remodeling)",
            "abnormal": {
                "confidence": 0.83,
                "label": "Cardiac chamber / septal ROI",
                "explanation": (
                    "Detected elevated myocardial/pericardial acoustic reflectance and chamber volume shift "
                    "consistent with microgravity cephalad fluid redistribution."
                ),
                "steps": [
                    "Record resting blood pressure and heart rate after 10 minutes in neutral posture.",
                    "Compare left ventricular chamber contour against baseline mission scan.",
                    "Transmit cardiac frame to Flight Surgeon if palpitations or chest pressure occur.",
                ],
            },
            "nominal": {
                "confidence": 0.86,
                "label": "Cardiac 4-chamber view nominal",
                "explanation": (
                    "Cardiac chamber geometry and myocardial wall reflectivity appear within spaceflight baseline "
                    "without pericardial fluid collection."
                ),
                "steps": [
                    "Archive baseline echocardiogram frame to mission log.",
                    "Continue scheduled aerobic and resistive exercise countermeasures.",
                ],
            },
        },
    ),
    (
        ("kidney", "renal", "bladder", "stone", "nephro", "hydronephrosis"),
        {
            "zones": ["kidneys_fluid"],
            "hazard": "Gravity Fields & Nutrition (Bone Calcium Mobilization / Renal Stone Risk)",
            "abnormal": {
                "confidence": 0.82,
                "label": "Renal pelvis / echogenic focus ROI",
                "explanation": (
                    "Detected localized hyperechoic focus or mild pelvicalyceal prominence "
                    "suggesting elevated renal stone or urinary stasis risk."
                ),
                "steps": [
                    "Increase oral water intake by 500 mL over the next 4 hours.",
                    "Perform contralateral kidney and bladder sweep to assess urinary retention.",
                    "Log urine output and notify Crew Medical Officer if flank discomfort develops.",
                ],
            },
            "nominal": {
                "confidence": 0.86,
                "label": "Renal parenchyma nominal",
                "explanation": (
                    "Renal cortical echogenicity and collecting system appear clear "
                    "without acoustic shadowing or hydronephrosis."
                ),
                "steps": [
                    "Maintain daily hydration target and scheduled ARED resistive exercise.",
                    "Store renal scan for routine mission comparison.",
                ],
            },
        },
    ),
    (
        ("eye", "ocular", "optic", "onsd", "sans", "retina"),
        {
            "zones": ["eyes_sans"],
            "hazard": "Gravity Fields (Spaceflight-Associated Neuro-ocular Syndrome — SANS)",
            "abnormal": {
                "confidence": 0.84,
                "label": "Optic nerve sheath (ONSD) ROI",
                "explanation": (
                    "Detected retrobulbar optic nerve sheath prominence or posterior globe flattening patterns "
                    "consistent with microgravity SANS fluid shift."
                ),
                "steps": [
                    "Perform visual acuity and Amsler grid self-assessment on both eyes.",
                    "Check cabin CO2 levels and log any headache or visual distortion.",
                    "Schedule Flight Surgeon tele-ophthalmology review with annotated ONSD frame.",
                ],
            },
            "nominal": {
                "confidence": 0.87,
                "label": "Ocular / ONSD profile nominal",
                "explanation": (
                    "Retrobulbar optic nerve sheath contour and posterior sclera appear symmetric "
                    "without acute SANS distension."
                ),
                "steps": [
                    "Save baseline ocular ultrasound measurement to mission medical log.",
                    "Continue routine visual checks and cabin CO2 monitoring.",
                ],
            },
        },
    ),
]

_DEFAULT_LUNG_ULTRASOUND_PROFILE: dict[str, Any] = {
    "zones": ["lungs_airway"],
    "hazard": "Hostile Closed Environments / Microgravity fluid shift",
    "abnormal": {
        "confidence": 0.82,
        "label": "B-line cluster region",
        "explanation": (
            "Detected localized vertical ultrasound artifacts (B-line pattern) "
            "suggesting mild pulmonary fluid shift or localized congestion."
        ),
        "steps": [
            "Repeat scan on both lung fields in 4 hours to verify persistence.",
            "Review cabin CO2 and daily fluid intake logs.",
            "Ask crew medical officer to inspect breathing rate and auscultation.",
        ],
    },
    "nominal": {
        "confidence": 0.86,
        "label": "Pleural field nominal",
        "explanation": (
            "Ultrasound acoustic profile appears uniform without prominent vertical "
            "B-line clusters or fluid accumulation."
        ),
        "steps": [
            "Store baseline ultrasound frame for mission comparison.",
            "Continue routine hydration and resistive exercise countermeasures.",
        ],
    },
}


def _resolve_ultrasound_organ_profile(
    context_notes: str,
    gray: np.ndarray | None = None,
) -> dict[str, Any]:
    """Select organ-specific ultrasound profile from context hints or chamber structure."""
    notes_lower = context_notes.lower()
    if "lung" in notes_lower or "pleura" in notes_lower:
        return _DEFAULT_LUNG_ULTRASOUND_PROFILE
    for keywords, profile in _ULTRASOUND_ORGAN_PROFILES:
        if any(k in notes_lower for k in keywords):
            return profile

    # Auto-detect chambered echocardiogram frames when no explicit organ hint was given
    if gray is not None and gray.shape[0] >= 20 and gray.shape[1] >= 20:
        h, w = gray.shape
        roi_raw = gray[int(h * 0.2) : int(h * 0.85), int(w * 0.2) : int(w * 0.8)]
        top_band = gray[int(h * 0.04) : int(h * 0.35), int(w * 0.25) : int(w * 0.75)]
        dark_chamber_fraction = float((roi_raw < 40).mean())
        bright_wall_fraction = float((roi_raw > 185).mean())
        top_bright_fraction = float((top_band > 185).mean())
        gx = float(np.abs(np.diff(roi_raw.astype(np.float32), axis=1)).mean())
        gy = float(np.abs(np.diff(roi_raw.astype(np.float32), axis=0)).mean())
        if (
            dark_chamber_fraction > 0.30
            and (bright_wall_fraction > 0.05 or top_bright_fraction > 0.12)
            and gy >= gx * 0.80
        ):
            return _ULTRASOUND_ORGAN_PROFILES[0][1]

    return _DEFAULT_LUNG_ULTRASOUND_PROFILE


def _analyze_ultrasound_opencv(img: np.ndarray, context_notes: str = "") -> dict[str, Any]:
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

    profile = _resolve_ultrasound_organ_profile(context_notes, gray)
    is_abnormal = bool(bright_fraction > 0.14 or col_peaks >= 12)

    if is_abnormal:
        severity: SeverityStatus = "caution"
        escalation: EscalationLevel = "crew_attention"
        cfg = profile["abnormal"]
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
            boxes = [RoiBox(x=bx, y=by, w=bw, h=bh, label=cfg["label"])]
        else:
            boxes = [RoiBox(x=0.28, y=0.24, w=0.44, h=0.52, label=cfg["label"])]
    else:
        severity = "nominal"
        escalation = "self_care"
        cfg = profile["nominal"]
        boxes = [RoiBox(x=0.25, y=0.22, w=0.50, h=0.55, label=cfg["label"])]

    return {
        "severity": severity,
        "confidence": cfg["confidence"],
        "extracted_value": None,
        "affected_body_zones": list(profile["zones"]),
        "roi_boxes": boxes,
        "space_hazard_link": profile["hazard"],
        "explanation_simple": cfg["explanation"],
        "action_steps": list(cfg["steps"]),
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


def _detect_lcd_crop(gray: np.ndarray) -> tuple[np.ndarray, RoiBox]:
    """Locate a high-contrast rectangular LCD display region if present."""
    h, w = gray.shape
    roi_box = RoiBox(x=0.10, y=0.14, w=0.80, h=0.66, label="LCD display region")

    blurred = cv2.GaussianBlur(gray, (5, 5), 0)
    _, otsu_mask = cv2.threshold(blurred, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    contours, _ = cv2.findContours(otsu_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if contours:
        largest = max(contours, key=cv2.contourArea)
        if cv2.contourArea(largest) > (h * w * 0.15):
            x, y, bw, bh = cv2.boundingRect(largest)
            # Trim 4% inner margin to drop LCD casing borders that confuse OCR
            pad_x = max(2, int(bw * 0.04))
            pad_y = max(2, int(bh * 0.04))
            x1 = min(w - 1, x + pad_x)
            y1 = min(h - 1, y + pad_y)
            x2 = max(x1 + 1, x + bw - pad_x)
            y2 = max(y1 + 1, y + bh - pad_y)
            roi_box = RoiBox(
                x=round(x / w, 3),
                y=round(y / h, 3),
                w=round(bw / w, 3),
                h=round(bh / h, 3),
                label="Detected device display",
            )
            return gray[y1:y2, x1:x2], roi_box

    return gray, roi_box


def _finalize_binary_for_tesseract(binary: np.ndarray) -> np.ndarray:
    """Ensure dark text on white background with generous padding for Tesseract."""
    normalized = cv2.bitwise_not(binary) if float(binary.mean()) < 127.0 else binary
    return cv2.copyMakeBorder(normalized, 24, 24, 24, 24, cv2.BORDER_CONSTANT, value=255)


def _build_ocr_candidates(crop: np.ndarray) -> list[np.ndarray]:
    """Build clean upscaled binary image variants (OTSU + adaptive) for OCR."""
    scale = 4 if min(crop.shape[:2]) < 220 else 2
    upscaled = cv2.resize(crop, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    contrasted = clahe.apply(upscaled)

    # Variant 1: OTSU preserves crisp strokes on small/synthetic LCD text without blurring
    _, bin_otsu = cv2.threshold(contrasted, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

    # Variant 2: Adaptive threshold handles uneven cabin lighting/glare on real photos
    light_blur = cv2.GaussianBlur(contrasted, (3, 3), 0)
    bin_adaptive = cv2.adaptiveThreshold(
        light_blur,
        255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY,
        blockSize=31,
        C=10,
    )

    return [
        _finalize_binary_for_tesseract(bin_otsu),
        _finalize_binary_for_tesseract(bin_adaptive),
    ]


def _parse_ocr_number(raw_text: str, requested_metric: str | None) -> tuple[float, str, str] | None:
    """Extract the first reading matching physiological OCR bounds."""
    numbers = re.findall(r"\d+(?:\.\d+)?", raw_text)
    if not numbers:
        return None

    inferred_metric = requested_metric or _infer_requested_ocr_metric(raw_text)
    for token in numbers:
        num = float(token)
        if inferred_metric is not None:
            min_v, max_v, unit = _OCR_METRIC_RANGES[inferred_metric]
            if min_v <= num <= max_v:
                rounded = round(num, 1) if inferred_metric == "temperature_c" else round(num, 0)
                return rounded, inferred_metric, unit
        else:
            temp_min, temp_max, temp_unit = _OCR_METRIC_RANGES["temperature_c"]
            gluc_min, gluc_max, gluc_unit = _OCR_METRIC_RANGES["blood_glucose_mg_dl"]
            if temp_min <= num <= temp_max:
                return round(num, 1), "temperature_c", temp_unit
            if gluc_min <= num <= gluc_max:
                return round(num, 0), "blood_glucose_mg_dl", gluc_unit
    return None


def _extract_ocr_digits_fallback(
    img: np.ndarray, context_notes: str
) -> tuple[float | None, str, str, RoiBox]:
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    crop, roi_box = _detect_lcd_crop(gray)
    candidates = _build_ocr_candidates(crop)
    requested_metric = _infer_requested_ocr_metric(context_notes)

    if is_tesseract_available() and pytesseract is not None:
        # Try sparse/block passes without digit-forcing first so labels like 'GLUCOSE' stay words
        configs = (
            "--psm 11",
            "--psm 6",
            "--psm 6 -c tessedit_char_whitelist=0123456789.",
        )
        for candidate in candidates:
            for cfg in configs:
                try:
                    raw_text = pytesseract.image_to_string(candidate, lang="eng", config=cfg)
                except Exception:
                    continue
                parsed = _parse_ocr_number(raw_text, requested_metric)
                if parsed is not None:
                    val, metric_name, unit = parsed
                    return val, metric_name, unit, roi_box

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
    img: np.ndarray, context_notes: str, env: EnvironmentType = "spacecraft"
) -> dict[str, Any]:

    val, metric_name, unit, roi_box = _extract_ocr_digits_fallback(img, context_notes)
    severity, escalation, affected_zones = evaluate_metric(
        environment=env, metric_name=metric_name, val=val
    )

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

    confidence = 0.25 if val is None else (0.88 if is_tesseract_available() else 0.79)

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

        client = genai.Client(
            api_key=api_key, http_options=types.HttpOptions(timeout=int(timeout * 1000))
        )
        prompt = (
            "You are ASTRA-Med, an autonomous spacecraft medical decision-support assistant grounded in NASA HRP 5 Hazards. "
            f"Analyze this image in mode='{mode}' for environment='{environment}'. "
            f"Context notes: '{context_notes}'. "
            "Act strictly as Decision Support: never state definitive clinical diagnoses; use non-diagnostic phrasing such as "
            "'Detected patterns consistent with...' or 'Indicates elevated risk...'. "
            "Return strictly a single valid JSON object (not a JSON array) with keys: "
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
        contents = [
            types.Part.from_bytes(data=prepared_bytes, mime_type=mime_type),
            prompt,
        ]
        gen_config = types.GenerateContentConfig(
            response_mime_type="application/json",
            temperature=0.2,
        )
        candidate_models = [settings.gemini_model]
        for fallback_model in ("gemini-3.5-flash", "gemini-3.8-flash", "gemini-3.5-flash-lite"):
            if fallback_model not in candidate_models:
                candidate_models.append(fallback_model)

        response = None
        for model_name in candidate_models:
            try:
                response = client.models.generate_content(
                    model=model_name,
                    contents=contents,
                    config=gen_config,
                )
                break
            except Exception as model_exc:
                err_msg = str(model_exc)
                retryable = any(
                    marker in err_msg
                    for marker in (
                        "404",
                        "NOT_FOUND",
                        "503",
                        "UNAVAILABLE",
                        "504",
                        "DEADLINE_EXCEEDED",
                    )
                )
                if retryable and model_name != candidate_models[-1]:
                    continue
                raise

        if response is None or not response.text:
            return None
        parsed = json.loads(response.text)
        if isinstance(parsed, list) and len(parsed) == 1 and isinstance(parsed[0], dict):
            parsed = parsed[0]
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
            if not (
                0.0 <= box.x <= 1.0
                and 0.0 <= box.y <= 1.0
                and 0.0 < box.w <= 1.0
                and 0.0 < box.h <= 1.0
            ):
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
            analysis = _analyze_ultrasound_opencv(img, context_notes)
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
