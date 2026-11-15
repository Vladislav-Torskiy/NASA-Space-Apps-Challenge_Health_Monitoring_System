import type {
  DashboardResponse,
  DemoFaultResponse,
  EnvironmentId,
  EnvironmentSwitchResponse,
  FaultId,
  GroundTransmitResponse,
  HealthResponse,
  MetricsHistoryResponse,
  PostMetricsPayload,
  PostMetricsResponse,
  RiskEvaluationResponse,
  RoutineCompleteResponse,
  VisionAnalyzeResponse,
  VisionMode,
} from '../types/astra';

const API_BASE = (import.meta.env.VITE_API_BASE_URL as string | undefined) || 'http://localhost:8000';

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, init);
  if (!response.ok) {
    let detail = `HTTP ${response.status}`;
    try {
      const data = await response.json();
      if (data?.detail) {
        detail = typeof data.detail === 'string' ? data.detail : JSON.stringify(data.detail);
      }
    } catch {
      // ignore non-json error body
    }
    throw new Error(detail);
  }
  return response.json() as Promise<T>;
}

export const api = {
  getHealth: () => request<HealthResponse>('/api/health'),

  getDashboard: () => request<DashboardResponse>('/api/dashboard'),

  getMetricsHistory: (days = 30) =>
    request<MetricsHistoryResponse>(`/api/metrics/history?days=${days}`),

  postMetrics: (payload: PostMetricsPayload) =>
    request<PostMetricsResponse>('/api/metrics', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    }),

  evaluateRisk: (environment?: EnvironmentId) =>
    request<RiskEvaluationResponse>('/api/evaluate/risk', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(environment ? { environment, include_latest_vision: true } : {}),
    }),

  analyzeVision: (
    image: File | Blob,
    mode: VisionMode,
    environment: EnvironmentId,
    contextNotes?: string,
  ) => {
    const form = new FormData();
    form.append('image', image, image instanceof File ? image.name : 'capture.jpg');
    form.append('mode', mode);
    form.append('environment', environment);
    if (contextNotes?.trim()) {
      form.append('context_notes', contextNotes.trim());
    }
    return request<VisionAnalyzeResponse>('/api/vision/analyze', {
      method: 'POST',
      body: form,
    });
  },

  switchEnvironment: (environment: EnvironmentId) =>
    request<EnvironmentSwitchResponse>('/api/mission/environment', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ environment }),
    }),

  injectFault: (fault: FaultId) =>
    request<DemoFaultResponse>('/api/demo/fault', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ fault }),
    }),

  completeRoutineTask: (taskId: number) =>
    request<RoutineCompleteResponse>(`/api/routine/${taskId}/complete`, {
      method: 'POST',
    }),

  transmitToGround: (notes?: string, includeFullHistoryDays = 5) =>
    request<GroundTransmitResponse>('/api/ground/transmit', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        notes: notes?.trim() || 'Autonomous medical telemetry packet',
        include_full_history_days: includeFullHistoryDays,
      }),
    }),
};
