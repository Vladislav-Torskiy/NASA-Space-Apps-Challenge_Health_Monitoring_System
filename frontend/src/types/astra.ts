export type EnvironmentId = 'spacecraft' | 'station' | 'rover' | 'base';

export type FaultId = 'solar_flare' | 'co2_drift' | 'sleep_deficit' | 'reset_baseline';

export type Severity = 'nominal' | 'caution' | 'critical';

export type EscalationLevel = 'self_care' | 'crew_attention' | 'flight_surgeon';

export type SystemLayerId =
  | 'all'
  | 'cardiovascular'
  | 'musculoskeletal'
  | 'immune_radiation'
  | 'neuro_behavioral';

export type VisionMode = 'ultrasound' | 'skin_eye' | 'device_ocr';

export interface HealthResponse {
  status: string;
  vision_provider: string;
  tesseract_available: boolean;
  mission_day: number;
}

export interface MissionState {
  environment: EnvironmentId;
  mission_day: number;
  owlt_seconds: number;
  owlt_label: string;
  active_fault: string | null;
}

export interface Badge {
  code: string;
  title: string;
  description: string;
  unlocked: boolean;
  unlocked_at: string | null;
}

export interface GamificationState {
  readiness_score: number;
  streak_days: number;
  badges: Badge[];
}

export interface BodyZoneStatus {
  zone_id: string;
  layer: Exclude<SystemLayerId, 'all'>;
  label: string;
  status: Severity;
  summary: string;
  space_hazard: string;
  self_exam_guide: string;
  organ_function: string;
  why_exam_needed: string;
}

export interface LatestMetrics {
  heart_rate: number;
  systolic_bp: number;
  diastolic_bp: number;
  blood_glucose_mg_dl: number;
  temperature_c: number;
  sleep_hours: number;
  mood_score: number;
  radiation_msv_total: number;
  radiation_msv_daily: number;
}

export interface RoutineTask {
  id: number;
  title: string;
  hazard_category: string;
  due_label: string;
  completed: boolean;
  points: number;
}

export interface DashboardResponse {
  mission: MissionState;
  gamification: GamificationState;
  body_zones: BodyZoneStatus[];
  latest_metrics: LatestMetrics;
  routine_tasks: RoutineTask[];
}

export interface MetricRecord {
  id: number;
  timestamp: string;
  mission_day: number;
  environment: EnvironmentId;
  heart_rate: number;
  systolic_bp: number;
  diastolic_bp: number;
  blood_glucose_mg_dl: number;
  temperature_c: number;
  sleep_hours: number;
  mood_score: number;
  radiation_msv: number;
  source: string;
  notes: string | null;
}

export interface ThresholdRange {
  label: string;
  unit: string;
  nominal_min: number;
  nominal_max: number;
  caution_min: number;
  caution_max: number;
}

export interface TrendAlert {
  code?: string;
  title?: string;
  severity: Severity;
  message: string;
  affected_zones?: string[];
}

export interface MetricsHistoryResponse {
  environment: EnvironmentId;
  days_requested: number;
  records: MetricRecord[];
  thresholds: Record<string, ThresholdRange>;
  trend_alerts: TrendAlert[];
}

export interface PostMetricsPayload {
  heart_rate?: number;
  systolic_bp?: number;
  diastolic_bp?: number;
  blood_glucose_mg_dl?: number;
  temperature_c?: number;
  sleep_hours?: number;
  mood_score?: number;
  radiation_msv_daily?: number;
  source?: string;
  notes?: string;
}

export interface RiskEvaluationResponse {
  environment: EnvironmentId;
  overall_severity: Severity;
  readiness_score: number;
  escalation_level: EscalationLevel;
  what_happened_and_why: string;
  space_hazard_link: string;
  action_steps: string[];
  flagged_metrics: Record<string, Severity>;
  trend_alerts: TrendAlert[];
  body_zones: BodyZoneStatus[];
  latest_vision_summary: string | null;
}

export interface PostMetricsResponse {
  record: MetricRecord;
  evaluation: RiskEvaluationResponse;
}

export interface RoiBox {
  x: number;
  y: number;
  w: number;
  h: number;
  label: string;
}

export interface ExtractedValue {
  metric: string;
  value: number;
  unit: string;
}

export interface VisionAnalyzeResponse {
  mode: VisionMode;
  provider_used: string;
  severity: Severity;
  confidence: number;
  extracted_value?: ExtractedValue | null;
  affected_body_zones: string[];
  roi_boxes: RoiBox[];
  annotated_image_base64?: string | null;
  space_hazard_link: string;
  explanation_simple: string;
  action_steps: string[];
  escalation_level: EscalationLevel;
}

export interface EnvironmentSwitchResponse {
  mission: MissionState;
  thresholds: Record<string, ThresholdRange>;
  evaluation: RiskEvaluationResponse;
}

export interface DemoFaultResponse {
  fault_applied: string;
  mission: MissionState;
  latest_metrics: LatestMetrics;
  evaluation: RiskEvaluationResponse;
}

export interface RoutineCompleteResponse {
  task: RoutineTask;
  gamification: GamificationState;
  newly_unlocked_badges: string[];
}

export interface GroundTransmitResponse {
  packet_id: number;
  created_at: string;
  environment: EnvironmentId;
  owlt_seconds: number;
  owlt_label: string;
  status: string;
  status_timeline: string[];
  interim_guidance: string[];
  text_summary: string;
  payload: Record<string, unknown>;
}
