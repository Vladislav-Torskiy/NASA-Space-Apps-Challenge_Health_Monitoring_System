import { useCallback, useEffect, useState } from 'react';
import { AlertCircle, RefreshCw } from 'lucide-react';
import { api } from './api/client';
import { MOCK_DASHBOARD, MOCK_EVALUATION, MOCK_HISTORY } from './api/mockData';
import { BiometricsPanel } from './components/BiometricsPanel';
import { BodyMapPanel } from './components/BodyMapPanel';
import { GroundCommsModal } from './components/GroundCommsModal';
import { MissionHeader } from './components/MissionHeader';
import { RoutineGamificationPanel } from './components/RoutineGamificationPanel';
import { VisionPanel } from './components/VisionPanel';
import type {
  DashboardResponse,
  EnvironmentId,
  FaultId,
  HealthResponse,
  MetricsHistoryResponse,
  PostMetricsPayload,
  RiskEvaluationResponse,
  VisionMode,
} from './types/astra';

export function App() {
  const [dashboard, setDashboard] = useState<DashboardResponse | null>(null);
  const [history, setHistory] = useState<MetricsHistoryResponse | null>(null);
  const [evaluation, setEvaluation] = useState<RiskEvaluationResponse | null>(null);
  const [health, setHealth] = useState<HealthResponse | null>(null);

  const [days, setDays] = useState(30);
  const [selectedZoneId, setSelectedZoneId] = useState('heart_vessels');
  const [loading, setLoading] = useState(true);
  const [backendOnline, setBackendOnline] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busyAction, setBusyAction] = useState<string | null>(null);
  const [completingTaskId, setCompletingTaskId] = useState<number | null>(null);
  const [recentlyUnlocked, setRecentlyUnlocked] = useState<string[]>([]);
  const [groundModalOpen, setGroundModalOpen] = useState(false);

  const loadAll = useCallback(
    async (requestedDays = days) => {
      setLoading(true);
      setError(null);
      try {
        const [dashRes, histRes, evalRes, healthRes] = await Promise.all([
          api.getDashboard(),
          api.getMetricsHistory(requestedDays),
          api.evaluateRisk(),
          api.getHealth(),
        ]);
        setDashboard(dashRes);
        setHistory(histRes);
        setEvaluation(evalRes);
        setHealth(healthRes);
        setBackendOnline(true);
      } catch (err) {
        setBackendOnline(false);
        setError(
          err instanceof Error
            ? err.message
            : 'Unable to reach ASTRA-Med backend on http://localhost:8000',
        );
      } finally {
        setLoading(false);
      }
    },
    [days],
  );

  useEffect(() => {
    void loadAll(days);
  }, [days, loadAll]);

  const handleSwitchEnvironment = async (env: EnvironmentId) => {
    setBusyAction(`env:${env}`);
    try {
      const res = await api.switchEnvironment(env);
      setEvaluation(res.evaluation);
      const [dashRes, histRes] = await Promise.all([
        api.getDashboard(),
        api.getMetricsHistory(days),
      ]);
      setDashboard(dashRes);
      setHistory(histRes);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to switch environment');
    } finally {
      setBusyAction(null);
    }
  };

  const handleInjectFault = async (fault: FaultId) => {
    setBusyAction(`fault:${fault}`);
    try {
      const res = await api.injectFault(fault);
      setEvaluation(res.evaluation);
      const [dashRes, histRes] = await Promise.all([
        api.getDashboard(),
        api.getMetricsHistory(days),
      ]);
      setDashboard(dashRes);
      setHistory(histRes);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to inject fault');
    } finally {
      setBusyAction(null);
    }
  };

  const handleSubmitMetrics = async (payload: PostMetricsPayload) => {
    const res = await api.postMetrics(payload);
    setEvaluation(res.evaluation);
    const [dashRes, histRes] = await Promise.all([
      api.getDashboard(),
      api.getMetricsHistory(days),
    ]);
    setDashboard(dashRes);
    setHistory(histRes);
  };

  const handleAnalyzeVision = async (
    image: File | Blob,
    mode: VisionMode,
    environment: EnvironmentId,
    notes?: string,
  ) => {
    const res = await api.analyzeVision(image, mode, environment, notes);
    const [dashRes, evalRes] = await Promise.all([
      api.getDashboard(),
      api.evaluateRisk(environment),
    ]);
    setDashboard(dashRes);
    setEvaluation(evalRes);
    return res;
  };

  const handleCompleteRoutine = async (taskId: number) => {
    setCompletingTaskId(taskId);
    try {
      const res = await api.completeRoutineTask(taskId);
      setRecentlyUnlocked(res.newly_unlocked_badges);
      setDashboard((prev) =>
        prev
          ? {
              ...prev,
              gamification: res.gamification,
              routine_tasks: prev.routine_tasks.map((t) =>
                t.id === taskId ? res.task : t,
              ),
            }
          : prev,
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to complete routine task');
    } finally {
      setCompletingTaskId(null);
    }
  };

  if (loading && !dashboard) {
    return (
      <div className="min-h-screen bg-slate-50 text-slate-700 flex flex-col items-center justify-center gap-3">
        <RefreshCw className="w-6 h-6 text-slate-900 animate-spin" />
        <p className="text-xs font-mono text-slate-500">
          Initializing ASTRA-Med Clinical Console...
        </p>
      </div>
    );
  }

  const enterDemoMode = () => {
    setDashboard(MOCK_DASHBOARD);
    setHistory(MOCK_HISTORY);
    setEvaluation(MOCK_EVALUATION);
    setHealth({
      status: 'ok',
      vision_provider: 'offline_opencv_ready',
      tesseract_available: false,
      mission_day: 24,
    });
    setBackendOnline(false);
    setError(null);
  };

  if (!dashboard || !history) {
    return (
      <div className="min-h-screen bg-slate-50 text-slate-900 flex items-center justify-center p-6">
        <div className="max-w-lg w-full rounded-2xl border border-slate-200 bg-white p-6 shadow-sm flex flex-col gap-4">
          <div className="flex items-center gap-2 text-rose-600 font-bold text-base">
            <AlertCircle className="w-5 h-5" />
            Backend Telemetry Link Offline
          </div>
          <p className="text-xs text-slate-600 leading-relaxed">
            Could not connect to the FastAPI backend at{' '}
            <code className="text-slate-900 font-semibold">
              {(import.meta.env.VITE_API_BASE_URL as string | undefined) ||
                'http://localhost:8000'}
            </code>
            . Start the backend server and click Retry, or preview the UI with built-in demo telemetry:
          </p>
          <pre className="text-xs font-mono bg-slate-950 rounded-lg p-3 text-slate-100 overflow-x-auto">
            cd d:\nasa\backend{'\n'}python -m venv .venv{'\n'}.\.venv\Scripts\Activate.ps1{'\n'}pip install -r requirements.txt{'\n'}uvicorn app.main:app --reload --port 8000
          </pre>
          {error && <p className="text-xs text-rose-600 font-mono">{error}</p>}
          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              onClick={() => void loadAll(days)}
              className="px-4 py-2 rounded-lg bg-slate-900 hover:bg-slate-800 text-white text-xs font-semibold flex items-center gap-1.5 cursor-pointer"
            >
              <RefreshCw className="w-3.5 h-3.5" />
              Retry Connection
            </button>
            <button
              type="button"
              onClick={enterDemoMode}
              className="px-4 py-2 rounded-lg border border-slate-300 bg-white hover:bg-slate-50 text-slate-800 text-xs font-semibold cursor-pointer"
            >
              Preview UI (Demo Data)
            </button>
          </div>
        </div>
      </div>
    );
  }

  const activeZones = evaluation?.body_zones ?? dashboard.body_zones;
  const attentionCount = activeZones.filter((z) => z.status !== 'nominal').length;
  const nowUtc = new Date().toISOString().slice(11, 19);

  return (
    <div className="min-h-screen bg-slate-50 text-slate-900 flex flex-col">
      <MissionHeader
        mission={dashboard.mission}
        health={health}
        backendOnline={backendOnline}
        attentionCount={attentionCount}
        busyAction={busyAction}
        onSwitchEnvironment={handleSwitchEnvironment}
        onInjectFault={handleInjectFault}
        onOpenGroundComms={() => setGroundModalOpen(true)}
      />

      <main className="max-w-[1640px] w-full mx-auto px-4 sm:px-6 py-4 flex-1 flex flex-col gap-4">
        {error && (
          <div className="rounded-xl border border-rose-200 bg-rose-50 px-4 py-2.5 text-xs text-rose-700 flex items-center justify-between">
            <span>{error}</span>
            <button
              type="button"
              onClick={() => setError(null)}
              className="underline cursor-pointer"
            >
              Dismiss
            </button>
          </div>
        )}

        {/* 3-Column Clinical Mission Console Grid */}
        <div className="grid grid-cols-1 xl:grid-cols-12 gap-4 items-start">
          {/* Column 1: 01 Physiological Systems Mapping */}
          <div className="xl:col-span-4">
            <BodyMapPanel
              zones={activeZones}
              selectedZoneId={selectedZoneId}
              onSelectZone={setSelectedZoneId}
            />
          </div>

          {/* Column 2: 02 Biometric Telemetry */}
          <div className="xl:col-span-4">
            <BiometricsPanel
              latest={dashboard.latest_metrics}
              records={history.records}
              thresholds={history.thresholds}
              trendAlerts={evaluation?.trend_alerts ?? history.trend_alerts}
              flaggedMetrics={evaluation?.flagged_metrics ?? {}}
              days={days}
              onChangeDays={setDays}
              onSubmitMetrics={handleSubmitMetrics}
            />
          </div>

          {/* Column 3: 03 AI Diagnostics & Crew Protocol */}
          <div className="xl:col-span-4 flex flex-col gap-3">
            <div>
              <div className="text-[11px] font-bold uppercase tracking-wider text-slate-700">
                03 &nbsp; AI DIAGNOSTICS &amp; CREW PROTOCOL
              </div>
              <div className="text-[11px] text-slate-400">
                Onboard intelligence • autonomous care
              </div>
            </div>

            <VisionPanel
              environment={dashboard.mission.environment}
              onAnalyze={handleAnalyzeVision}
              onConfirmOcr={handleSubmitMetrics}
            />

            <RoutineGamificationPanel
              gamification={dashboard.gamification}
              tasks={dashboard.routine_tasks}
              completingTaskId={completingTaskId}
              recentlyUnlocked={recentlyUnlocked}
              onCompleteTask={handleCompleteRoutine}
            />
          </div>
        </div>
      </main>

      {/* Bottom Clinical Status Footer */}
      <footer className="border-t border-slate-200 bg-white">
        <div className="max-w-[1640px] mx-auto px-4 sm:px-6 py-2.5 flex flex-wrap items-center justify-between gap-2 text-[10px] font-mono text-slate-400">
          <div className="flex items-center gap-2">
            <span className="w-1.5 h-1.5 rounded-full bg-emerald-500" />
            <span>OFFLINE-FIRST • Encrypted local storage • WAL synchronized</span>
          </div>
          <div className="uppercase tracking-wider text-slate-400">
            CLINICAL DECISION SUPPORT — NOT A SUBSTITUTE FOR FLIGHT SURGEON REVIEW
          </div>
          <div>
            MET D{dashboard.mission.mission_day} {nowUtc} / UTC
          </div>
        </div>
      </footer>

      <GroundCommsModal
        open={groundModalOpen}
        mission={dashboard.mission}
        onClose={() => setGroundModalOpen(false)}
        onTransmit={(notes) => api.transmitToGround(notes)}
      />
    </div>
  );
}

export default App;
