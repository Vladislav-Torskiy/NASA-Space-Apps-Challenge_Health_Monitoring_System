"""Pydantic v2 API contracts matching ARCHITECTURE.md Section 4."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

EnvironmentType = Literal["spacecraft", "station", "rover", "base"]
FaultType = Literal["solar_flare", "co2_drift", "sleep_deficit", "reset_baseline"]
SeverityStatus = Literal["nominal", "caution", "critical"]
EscalationLevel = Literal["self_care", "crew_attention", "flight_surgeon"]
VisionMode = Literal["ultrasound", "skin_eye", "device_ocr"]


class HealthCheckResponse(BaseModel):
    status: str
    vision_provider: str
    tesseract_available: bool
    mission_day: int


class MissionContext(BaseModel):
    environment: EnvironmentType
    mission_day: int
    owlt_seconds: int
    owlt_label: str
    active_fault: str | None = None


class BadgeItem(BaseModel):
    code: str
    title: str
    description: str | None = None
    unlocked: bool
    unlocked_at: str | None = None


class GamificationSummary(BaseModel):
    readiness_score: int
    streak_days: int
    badges: list[BadgeItem]


class BodyZoneStatus(BaseModel):
    zone_id: str
    layer: str
    label: str
    status: SeverityStatus
    summary: str
    space_hazard: str
    self_exam_guide: str
    organ_function: str | None = None
    why_exam_needed: str | None = None
    hrp_risk_name: str | None = None
    reference_title: str | None = None
    reference_url: str | None = None


class LatestMetrics(BaseModel):
    heart_rate: float
    systolic_bp: float
    diastolic_bp: float
    blood_glucose_mg_dl: float
    temperature_c: float
    sleep_hours: float
    mood_score: int
    radiation_msv_total: float
    radiation_msv_daily: float | None = None


class RoutineTaskItem(BaseModel):
    id: int
    title: str
    hazard_category: str
    due_label: str
    completed: bool
    points: int


class DashboardResponse(BaseModel):
    mission: MissionContext
    gamification: GamificationSummary
    body_zones: list[BodyZoneStatus]
    latest_metrics: LatestMetrics
    routine_tasks: list[RoutineTaskItem]


class MetricRecord(BaseModel):
    id: int
    timestamp: str
    mission_day: int
    environment: str
    heart_rate: float
    systolic_bp: float
    diastolic_bp: float
    blood_glucose_mg_dl: float
    temperature_c: float
    sleep_hours: float
    mood_score: int
    radiation_msv: float
    source: str
    notes: str


class ThresholdRange(BaseModel):
    label: str
    unit: str
    nominal_min: float
    nominal_max: float
    caution_min: float
    caution_max: float


class TrendAlert(BaseModel):
    code: str
    title: str
    severity: SeverityStatus
    metric: str
    slope_per_day: float
    affected_zones: list[str]
    message: str


class MetricsHistoryResponse(BaseModel):
    environment: EnvironmentType
    days_requested: int
    records: list[MetricRecord]
    thresholds: dict[str, ThresholdRange]
    trend_alerts: list[TrendAlert]


class MetricCreateRequest(BaseModel):
    heart_rate: float = Field(..., ge=25, le=240)
    systolic_bp: float = Field(..., ge=50, le=260)
    diastolic_bp: float = Field(..., ge=30, le=160)
    blood_glucose_mg_dl: float = Field(..., ge=20, le=600)
    temperature_c: float = Field(..., ge=32.0, le=43.0)
    sleep_hours: float = Field(..., ge=0.0, le=24.0)
    mood_score: int = Field(..., ge=1, le=10)
    radiation_msv_daily: float = Field(..., ge=0.0, le=100.0)
    notes: str = ""
    source: str = "manual"


class RiskEvaluationResponse(BaseModel):
    environment: EnvironmentType
    overall_severity: SeverityStatus
    readiness_score: int
    escalation_level: EscalationLevel
    what_happened_and_why: str
    space_hazard_link: str
    action_steps: list[str]
    flagged_metrics: dict[str, SeverityStatus]
    trend_alerts: list[TrendAlert]
    body_zones: list[BodyZoneStatus]
    latest_vision_summary: str | None = None
    official_references: list[dict[str, str]] = Field(default_factory=list)


class MetricCreateResponse(BaseModel):
    record: MetricRecord
    evaluation: RiskEvaluationResponse


class RiskEvaluateRequest(BaseModel):
    environment: EnvironmentType | None = None
    include_latest_vision: bool = True


class EnvironmentSwitchRequest(BaseModel):
    environment: EnvironmentType


class EnvironmentSwitchResponse(BaseModel):
    mission: MissionContext
    thresholds: dict[str, ThresholdRange]
    evaluation: RiskEvaluationResponse


class DemoFaultRequest(BaseModel):
    fault: FaultType


class DemoFaultResponse(BaseModel):
    fault_applied: str
    mission: MissionContext
    latest_metrics: LatestMetrics
    evaluation: RiskEvaluationResponse


class RoutineCompleteResponse(BaseModel):
    task: RoutineTaskItem
    gamification: GamificationSummary
    newly_unlocked_badges: list[str]


class GroundTransmitRequest(BaseModel):
    notes: str = ""
    include_full_history_days: int = Field(default=5, ge=1, le=30)


class GroundTransmitResponse(BaseModel):
    packet_id: int
    created_at: str
    environment: EnvironmentType
    owlt_seconds: int
    owlt_label: str
    status: str
    status_timeline: list[str]
    interim_guidance: list[str]
    text_summary: str
    payload: dict


class RoiBox(BaseModel):
    x: float
    y: float
    w: float
    h: float
    label: str


class ExtractedMetricValue(BaseModel):
    metric: str
    value: float
    unit: str


class VisionAnalyzeResponse(BaseModel):
    mode: VisionMode
    provider_used: str
    severity: SeverityStatus
    confidence: float
    extracted_value: ExtractedMetricValue | None = None
    affected_body_zones: list[str]
    roi_boxes: list[RoiBox]
    annotated_image_base64: str
    space_hazard_link: str
    explanation_simple: str
    action_steps: list[str]
    escalation_level: EscalationLevel
