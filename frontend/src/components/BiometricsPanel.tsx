import { useMemo, useState } from 'react';
import { Plus } from 'lucide-react';
import {
  Area,
  AreaChart,
  CartesianGrid,
  ReferenceArea,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import type {
  LatestMetrics,
  MetricRecord,
  PostMetricsPayload,
  Severity,
  ThresholdRange,
  TrendAlert,
} from '../types/astra';

interface BiometricsPanelProps {
  latest: LatestMetrics;
  records: MetricRecord[];
  thresholds: Record<string, ThresholdRange>;
  trendAlerts: TrendAlert[];
  flaggedMetrics: Record<string, Severity>;
  days: number;
  onChangeDays: (days: number) => void;
  onSubmitMetrics: (payload: PostMetricsPayload) => Promise<void>;
}

type ChartMetricKey =
  | 'sleep_hours'
  | 'systolic_bp'
  | 'heart_rate'
  | 'radiation_msv_daily'
  | 'blood_glucose_mg_dl'
  | 'temperature_c'
  | 'mood_score';

const CHART_TABS: {
  key: ChartMetricKey;
  recordKey: keyof MetricRecord;
  label: string;
  unit: string;
}[] = [
  { key: 'sleep_hours', recordKey: 'sleep_hours', label: 'Daily sleep', unit: 'HOURS' },
  { key: 'systolic_bp', recordKey: 'systolic_bp', label: 'Blood pressure', unit: 'MMHG' },
  { key: 'heart_rate', recordKey: 'heart_rate', label: 'Heart rate', unit: 'BPM' },
  { key: 'radiation_msv_daily', recordKey: 'radiation_msv', label: 'Radiation', unit: 'MSV' },
  { key: 'blood_glucose_mg_dl', recordKey: 'blood_glucose_mg_dl', label: 'Glucose', unit: 'MG/DL' },
  { key: 'temperature_c', recordKey: 'temperature_c', label: 'Temp', unit: '°C' },
  { key: 'mood_score', recordKey: 'mood_score', label: 'Mood', unit: '1-10' },
];

function barColor(sev?: Severity): string {
  if (sev === 'critical') return 'bg-rose-500';
  if (sev === 'caution') return 'bg-amber-500';
  return 'bg-emerald-500';
}

function statusTextColor(sev?: Severity): string {
  if (sev === 'critical') return 'text-rose-600';
  if (sev === 'caution') return 'text-amber-600';
  return 'text-emerald-600';
}

export function BiometricsPanel({
  latest,
  records,
  thresholds,
  trendAlerts,
  flaggedMetrics,
  days,
  onChangeDays,
  onSubmitMetrics,
}: BiometricsPanelProps) {
  const [selectedMetric, setSelectedMetric] = useState<ChartMetricKey>('sleep_hours');
  const [showModal, setShowModal] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);

  const [form, setForm] = useState({
    heart_rate: String(latest.heart_rate),
    systolic_bp: String(latest.systolic_bp),
    diastolic_bp: String(latest.diastolic_bp),
    blood_glucose_mg_dl: String(latest.blood_glucose_mg_dl),
    temperature_c: String(latest.temperature_c),
    sleep_hours: String(latest.sleep_hours),
    mood_score: String(latest.mood_score),
    radiation_msv_daily: String(latest.radiation_msv_daily),
    notes: '',
  });

  const activeConfig =
    CHART_TABS.find((m) => m.key === selectedMetric) ?? CHART_TABS[0];
  const activeThreshold = thresholds[selectedMetric];

  const chartData = useMemo(
    () =>
      records.map((r) => ({
        day: `Day ${String(r.mission_day).padStart(2, '0')}`,
        value: Number(r[activeConfig.recordKey]),
      })),
    [records, activeConfig.recordKey],
  );

  const openLogModal = () => {
    setForm({
      heart_rate: String(latest.heart_rate),
      systolic_bp: String(latest.systolic_bp),
      diastolic_bp: String(latest.diastolic_bp),
      blood_glucose_mg_dl: String(latest.blood_glucose_mg_dl),
      temperature_c: String(latest.temperature_c),
      sleep_hours: String(latest.sleep_hours),
      mood_score: String(latest.mood_score),
      radiation_msv_daily: String(latest.radiation_msv_daily),
      notes: '',
    });
    setFormError(null);
    setShowModal(true);
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setSubmitting(true);
    setFormError(null);
    try {
      await onSubmitMetrics({
        heart_rate: Number(form.heart_rate),
        systolic_bp: Number(form.systolic_bp),
        diastolic_bp: Number(form.diastolic_bp),
        blood_glucose_mg_dl: Number(form.blood_glucose_mg_dl),
        temperature_c: Number(form.temperature_c),
        sleep_hours: Number(form.sleep_hours),
        mood_score: Number(form.mood_score),
        radiation_msv_daily: Number(form.radiation_msv_daily),
        source: 'manual',
        notes: form.notes.trim() || undefined,
      });
      setShowModal(false);
    } catch (err) {
      setFormError(err instanceof Error ? err.message : 'Failed to log metrics');
    } finally {
      setSubmitting(false);
    }
  };

  const bpSeverity = (
    flaggedMetrics.systolic_bp === 'critical' || flaggedMetrics.diastolic_bp === 'critical'
      ? 'critical'
      : flaggedMetrics.systolic_bp || flaggedMetrics.diastolic_bp
  ) as Severity | undefined;

  const cards = [
    {
      label: 'BLOOD PRESSURE',
      value: `${Math.round(latest.systolic_bp)} / ${Math.round(latest.diastolic_bp)}`,
      unit: 'mmHg',
      sub: bpSeverity && bpSeverity !== 'nominal' ? 'Fluid shift deviation' : 'Within space baseline',
      sev: bpSeverity,
      chartKey: 'systolic_bp' as ChartMetricKey,
    },
    {
      label: 'HEART RATE',
      value: latest.heart_rate.toFixed(0),
      unit: 'bpm',
      sub: flaggedMetrics.heart_rate && flaggedMetrics.heart_rate !== 'nominal' ? 'Elevated resting rate' : 'Resting baseline',
      sev: flaggedMetrics.heart_rate,
      chartKey: 'heart_rate' as ChartMetricKey,
    },
    {
      label: 'GLUCOSE',
      value: latest.blood_glucose_mg_dl.toFixed(0),
      unit: 'mg/dL',
      sub: flaggedMetrics.blood_glucose_mg_dl && flaggedMetrics.blood_glucose_mg_dl !== 'nominal' ? 'Metabolic drift' : 'Metabolic stability',
      sev: flaggedMetrics.blood_glucose_mg_dl,
      chartKey: 'blood_glucose_mg_dl' as ChartMetricKey,
    },
    {
      label: 'BODY TEMP',
      value: latest.temperature_c.toFixed(1),
      unit: '°C',
      sub: flaggedMetrics.temperature_c && flaggedMetrics.temperature_c !== 'nominal' ? 'Thermal alert' : 'Thermal regulation',
      sev: flaggedMetrics.temperature_c,
      chartKey: 'temperature_c' as ChartMetricKey,
    },
    {
      label: 'DAILY SLEEP',
      value: latest.sleep_hours.toFixed(1),
      unit: 'hrs',
      sub: flaggedMetrics.sleep_hours && flaggedMetrics.sleep_hours !== 'nominal' ? 'Below circadian target' : 'Circadian baseline',
      sev: flaggedMetrics.sleep_hours,
      chartKey: 'sleep_hours' as ChartMetricKey,
    },
    {
      label: 'RADIATION',
      value: latest.radiation_msv_daily.toFixed(2),
      unit: 'mSv/day',
      sub: `${latest.radiation_msv_total.toFixed(1)} mSv cumulative`,
      sev: flaggedMetrics.radiation_msv_daily,
      chartKey: 'radiation_msv_daily' as ChartMetricKey,
    },
  ];

  return (
    <div className="flex flex-col gap-3">
      {/* Section Header */}
      <div className="flex items-center justify-between">
        <div>
          <div className="text-[11px] font-bold uppercase tracking-wider text-slate-700">
            02 &nbsp; BIOMETRIC TELEMETRY
          </div>
          <div className="text-[11px] text-slate-400">
            Continuous monitoring • personalized space baselines
          </div>
        </div>

        <div className="flex items-center gap-2">
          <span className="inline-flex items-center gap-1 text-[11px] font-mono font-semibold text-emerald-600">
            LIVE
            <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 animate-pulse" />
          </span>
          <button
            type="button"
            onClick={openLogModal}
            className="flex items-center gap-1 px-2.5 py-1 rounded-lg border border-slate-200 bg-white hover:bg-slate-50 text-[11px] font-semibold text-slate-700 cursor-pointer shadow-2xs"
          >
            <Plus className="w-3 h-3" />
            Log Vitals
          </button>
        </div>
      </div>

      {/* 6 Metric Cards (3x2) */}
      <div className="grid grid-cols-2 sm:grid-cols-3 gap-2.5">
        {cards.map((c) => {
          const isSelected = selectedMetric === c.chartKey;
          return (
            <button
              key={c.label}
              type="button"
              onClick={() => setSelectedMetric(c.chartKey)}
              className={`rounded-xl border bg-white p-3 text-left transition-all cursor-pointer shadow-2xs flex flex-col justify-between ${
                isSelected ? 'border-slate-900 ring-1 ring-slate-900/10' : 'border-slate-200 hover:border-slate-300'
              }`}
            >
              <div className="text-[10px] font-semibold uppercase tracking-wider text-slate-400">
                {c.label}
              </div>
              <div className="mt-1.5 flex items-baseline gap-1">
                <span className="text-2xl font-bold tracking-tight text-slate-900 font-mono">
                  {c.value}
                </span>
                <span className="text-[11px] text-slate-400">{c.unit}</span>
              </div>
              <div className={`text-[11px] font-medium mt-1.5 ${statusTextColor(c.sev)}`}>
                {c.sub}
              </div>
              {/* Mini Threshold Bar */}
              <div className="mt-2 h-1 w-full rounded-full bg-slate-100 overflow-hidden relative">
                <div className={`h-full w-1/2 rounded-full mx-auto ${barColor(c.sev)}`} />
              </div>
            </button>
          );
        })}
      </div>

      {/* 30-day Trend Monitor */}
      <section className="rounded-xl border border-slate-200 bg-white shadow-xs p-4 flex flex-col gap-3">
        <div className="flex flex-wrap items-start justify-between gap-2">
          <div>
            <h3 className="text-sm font-bold text-slate-900">
              {days}-day trend monitor
            </h3>
            <p className="text-[11px] text-slate-400">
              Space-adapted baseline vs. physiological drift
            </p>
          </div>

          <div className="flex items-center bg-slate-100 p-0.5 rounded-lg border border-slate-200 text-[11px] font-mono">
            {[14, 30].map((d) => (
              <button
                key={d}
                type="button"
                onClick={() => onChangeDays(d)}
                className={`px-2.5 py-0.5 rounded-md cursor-pointer transition-colors ${
                  days === d
                    ? 'bg-white text-slate-900 font-semibold shadow-2xs'
                    : 'text-slate-500 hover:text-slate-800'
                }`}
              >
                {d}D
              </button>
            ))}
          </div>
        </div>

        {/* Metric Tabs */}
        <div className="flex flex-wrap gap-1 border-b border-slate-100 pb-2">
          {CHART_TABS.map((tab) => {
            const active = selectedMetric === tab.key;
            return (
              <button
                key={tab.key}
                type="button"
                onClick={() => setSelectedMetric(tab.key)}
                className={`px-2.5 py-1 rounded-md text-[11px] font-medium transition-colors cursor-pointer ${
                  active
                    ? 'bg-slate-900 text-white'
                    : 'text-slate-500 hover:bg-slate-100 hover:text-slate-800'
                }`}
              >
                {tab.label}
              </button>
            );
          })}
        </div>

        <div className="text-[10px] font-mono uppercase tracking-wider text-slate-400">
          {activeConfig.unit}
        </div>

        <div className="h-48 w-full">
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart data={chartData} margin={{ top: 4, right: 8, left: -18, bottom: 0 }}>
              <defs>
                <linearGradient id="clinicalArea" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor="#2563eb" stopOpacity={0.14} />
                  <stop offset="95%" stopColor="#2563eb" stopOpacity={0.01} />
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" />
              <XAxis dataKey="day" stroke="#94a3b8" fontSize={10} tickLine={false} />
              <YAxis stroke="#94a3b8" fontSize={10} tickLine={false} domain={['auto', 'auto']} />
              <Tooltip
                contentStyle={{
                  backgroundColor: '#ffffff',
                  borderColor: '#e2e8f0',
                  borderRadius: '0.5rem',
                  fontSize: '11px',
                  color: '#0f172a',
                }}
              />
              {activeThreshold && (
                <ReferenceArea
                  y1={activeThreshold.nominal_min}
                  y2={activeThreshold.nominal_max}
                  fill="#10b981"
                  fillOpacity={0.09}
                  strokeOpacity={0}
                />
              )}
              <Area
                type="monotone"
                dataKey="value"
                name={activeConfig.label}
                stroke="#2563eb"
                strokeWidth={2}
                fillOpacity={1}
                fill="url(#clinicalArea)"
              />
            </AreaChart>
          </ResponsiveContainer>
        </div>

        {activeThreshold && (
          <div className="flex flex-wrap items-center justify-between gap-2 pt-2 border-t border-slate-100 text-[11px] text-slate-500">
            <div className="flex items-center gap-4">
              <span className="flex items-center gap-1.5">
                <span className="w-2.5 h-2 rounded-xs bg-emerald-200 border border-emerald-400" />
                Space baseline: {activeThreshold.nominal_min}–{activeThreshold.nominal_max}{' '}
                {activeThreshold.unit}
              </span>
              <span className="flex items-center gap-1.5">
                <span className="w-3 h-0.5 bg-blue-600" />
                Observed {activeConfig.label.toLowerCase()}
              </span>
            </div>
          </div>
        )}
      </section>

      {/* Trend Observations Card */}
      <section className="rounded-xl border border-slate-200 bg-white shadow-xs p-4 flex flex-col gap-2.5">
        <div className="flex items-center justify-between">
          <div className="text-[10px] font-semibold uppercase tracking-wider text-slate-400">
            TREND OBSERVATIONS
          </div>
          <span className="text-[11px] font-mono text-slate-400">
            0{trendAlerts.length > 0 ? trendAlerts.length : 1}
          </span>
        </div>

        {trendAlerts.length > 0 ? (
          trendAlerts.map((alert, idx) => (
            <div
              key={idx}
              className={`rounded-lg border-l-4 p-2.5 flex items-start justify-between gap-3 bg-slate-50 ${
                alert.severity === 'critical'
                  ? 'border-l-rose-500'
                  : 'border-l-amber-500'
              }`}
            >
              <div>
                <div className="text-xs font-semibold text-slate-800">
                  {alert.title || 'Physiological Drift Detected'}
                </div>
                <p className="text-[11px] text-slate-500 mt-0.5">{alert.message}</p>
              </div>
              <span
                className={`text-[10px] font-bold uppercase shrink-0 ${
                  alert.severity === 'critical' ? 'text-rose-600' : 'text-amber-600'
                }`}
              >
                {alert.severity}
              </span>
            </div>
          ))
        ) : (
          <div className="rounded-lg border-l-4 border-l-emerald-500 bg-slate-50 p-2.5 flex items-start justify-between gap-3">
            <div>
              <div className="text-xs font-semibold text-slate-800">
                Multi-day trends within space-adjusted thresholds
              </div>
              <p className="text-[11px] text-slate-500 mt-0.5">
                No adverse circadian, metabolic, or radiation slopes detected over the past 7 days.
              </p>
            </div>
            <span className="text-[10px] font-bold uppercase text-emerald-600 shrink-0">
              NOMINAL
            </span>
          </div>
        )}
      </section>

      {/* Manual Vitals Entry Modal */}
      {showModal && (
        <div className="fixed inset-0 z-50 bg-slate-900/50 backdrop-blur-xs flex items-center justify-center p-4">
          <div className="w-full max-w-lg rounded-2xl border border-slate-200 bg-white p-5 shadow-2xl">
            <div className="flex items-center justify-between mb-4">
              <h3 className="text-base font-bold text-slate-900">
                Log Astronaut Vitals
              </h3>
              <button
                type="button"
                onClick={() => setShowModal(false)}
                className="text-xs text-slate-500 hover:text-slate-800 cursor-pointer"
              >
                Close
              </button>
            </div>

            {formError && (
              <div className="mb-3 rounded-lg border border-rose-200 bg-rose-50 p-2.5 text-xs text-rose-700">
                {formError}
              </div>
            )}

            <form onSubmit={handleSubmit} className="grid grid-cols-2 gap-3 text-xs">
              {[
                { key: 'heart_rate', label: 'Heart Rate (bpm)', step: '1' },
                { key: 'blood_glucose_mg_dl', label: 'Blood Glucose (mg/dL)', step: '1' },
                { key: 'systolic_bp', label: 'Systolic BP (mmHg)', step: '1' },
                { key: 'diastolic_bp', label: 'Diastolic BP (mmHg)', step: '1' },
                { key: 'temperature_c', label: 'Body Temp (°C)', step: '0.1' },
                { key: 'sleep_hours', label: 'Sleep Hours (hrs)', step: '0.1' },
                { key: 'mood_score', label: 'Mood Score (1–10)', step: '1' },
                { key: 'radiation_msv_daily', label: 'Daily Radiation (mSv)', step: '0.01' },
              ].map((field) => (
                <label key={field.key} className="flex flex-col gap-1">
                  <span className="text-slate-600 font-medium">{field.label}</span>
                  <input
                    type="number"
                    step={field.step}
                    required
                    value={form[field.key as keyof typeof form]}
                    onChange={(e) =>
                      setForm((prev) => ({ ...prev, [field.key]: e.target.value }))
                    }
                    className="rounded-lg border border-slate-300 bg-white px-2.5 py-1.5 text-slate-900 font-mono focus:outline-none focus:border-slate-900"
                  />
                </label>
              ))}

              <label className="col-span-2 flex flex-col gap-1">
                <span className="text-slate-600 font-medium">Notes (optional)</span>
                <input
                  type="text"
                  placeholder="e.g., Post-EVA check or mild headache"
                  value={form.notes}
                  onChange={(e) => setForm((prev) => ({ ...prev, notes: e.target.value }))}
                  className="rounded-lg border border-slate-300 bg-white px-2.5 py-1.5 text-slate-900 focus:outline-none focus:border-slate-900"
                />
              </label>

              <div className="col-span-2 flex justify-end gap-2 pt-2">
                <button
                  type="button"
                  onClick={() => setShowModal(false)}
                  className="px-3 py-1.5 rounded-lg border border-slate-200 text-slate-600 hover:bg-slate-50 cursor-pointer"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={submitting}
                  className="px-4 py-1.5 rounded-lg bg-slate-900 hover:bg-slate-800 text-white font-semibold disabled:opacity-50 cursor-pointer"
                >
                  {submitting ? 'Evaluating...' : 'Save & Evaluate Risk'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
