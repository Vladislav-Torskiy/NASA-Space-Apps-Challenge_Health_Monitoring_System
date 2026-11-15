import { useEffect, useRef, useState } from 'react';
import { CheckCircle2, ScanLine, Upload } from 'lucide-react';
import type {
  EnvironmentId,
  EscalationLevel,
  PostMetricsPayload,
  VisionAnalyzeResponse,
  VisionMode,
} from '../types/astra';

interface VisionPanelProps {
  environment: EnvironmentId;
  onAnalyze: (
    image: File | Blob,
    mode: VisionMode,
    environment: EnvironmentId,
    notes?: string,
  ) => Promise<VisionAnalyzeResponse>;
  onConfirmOcr: (payload: PostMetricsPayload) => Promise<void>;
}

const MODES: { id: VisionMode; label: string }[] = [
  { id: 'ultrasound', label: 'Ultrasound' },
  { id: 'skin_eye', label: 'Dermatology & Eye' },
  { id: 'device_ocr', label: 'Device Display OCR' },
];

const TARGET_PRESETS: Record<VisionMode, { label: string; value: string }[]> = {
  ultrasound: [
    { label: 'Auto-detect', value: '' },
    { label: 'Lung / Pleura', value: 'lung' },
    { label: 'Cardiac / Echo', value: 'cardiac echo' },
    { label: 'Kidney / Renal', value: 'kidney renal' },
    { label: 'Ocular / SANS', value: 'ocular sans' },
  ],
  skin_eye: [
    { label: 'Auto-detect', value: '' },
    { label: 'Skin / Derm', value: 'skin' },
    { label: 'Ocular / Eye (SANS)', value: 'ocular eye sans' },
  ],
  device_ocr: [
    { label: 'Auto-detect', value: '' },
    { label: 'Glucose (mg/dL)', value: 'glucose' },
    { label: 'Temp (°C)', value: 'temperature' },
    { label: 'Heart Rate (bpm)', value: 'heart rate bpm' },
    { label: 'Systolic BP (mmHg)', value: 'systolic bp mmhg' },
  ],
};

const ESCALATION_BANNER: Record<EscalationLevel, { label: string; cls: string }> = {
  self_care: {
    label: 'Level 1: Self-Care Protocol',
    cls: 'bg-emerald-50 border-emerald-200 text-emerald-800',
  },
  crew_attention: {
    label: 'Level 2: Crew Attention Required',
    cls: 'bg-amber-50 border-amber-200 text-amber-800',
  },
  flight_surgeon: {
    label: 'Level 3: Flight Surgeon Alert',
    cls: 'bg-rose-50 border-rose-200 text-rose-800',
  },
};

export function VisionPanel({ environment, onAnalyze, onConfirmOcr }: VisionPanelProps) {
  const [mode, setMode] = useState<VisionMode>('ultrasound');
  const [targetPreset, setTargetPreset] = useState<string>(TARGET_PRESETS.ultrasound[0].value);
  const [contextNotes, setContextNotes] = useState<string>('');
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const [selectedFile, setSelectedFile] = useState<File | Blob | null>(null);
  const [analyzing, setAnalyzing] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [confirmedMsg, setConfirmedMsg] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<VisionAnalyzeResponse | null>(null);

  const [cameraOn, setCameraOn] = useState(false);
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const fileInputRef = useRef<HTMLInputElement | null>(null);

  useEffect(() => {
    return () => {
      streamRef.current?.getTracks().forEach((t) => t.stop());
    };
  }, []);

  const stopCamera = () => {
    streamRef.current?.getTracks().forEach((t) => t.stop());
    streamRef.current = null;
    setCameraOn(false);
  };

  const toggleCamera = async () => {
    if (cameraOn) {
      stopCamera();
      return;
    }
    setError(null);
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        video: { facingMode: 'environment' },
      });
      streamRef.current = stream;
      setCameraOn(true);
      setTimeout(() => {
        if (videoRef.current) {
          videoRef.current.srcObject = stream;
        }
      }, 50);
    } catch {
      setError('Camera unavailable. Upload a DICOM, PNG, or JPG file instead.');
    }
  };

  const captureAndAnalyze = () => {
    const video = videoRef.current;
    if (!video) return;
    const canvas = document.createElement('canvas');
    canvas.width = video.videoWidth || 640;
    canvas.height = video.videoHeight || 480;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;
    ctx.drawImage(video, 0, 0, canvas.width, canvas.height);
    canvas.toBlob(
      async (blob) => {
        if (!blob) return;
        setSelectedFile(blob);
        setPreviewUrl(URL.createObjectURL(blob));
        setResult(null);
        setConfirmedMsg(null);
        stopCamera();
        await runAnalyze(blob);
      },
      'image/jpeg',
      0.92,
    );
  };

  const runAnalyze = async (fileOrBlob: File | Blob, overridePreset?: string) => {
    setAnalyzing(true);
    setError(null);
    setConfirmedMsg(null);
    const activePreset = overridePreset !== undefined ? overridePreset : targetPreset;
    const combinedNotes = [activePreset, contextNotes].filter((s) => s.trim().length > 0).join(' ').trim();
    try {
      const res = await onAnalyze(fileOrBlob, mode, environment, combinedNotes || undefined);
      setResult(res);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Vision analysis failed');
    } finally {
      setAnalyzing(false);
    }
  };

  const handleFile = (file: File) => {
    setSelectedFile(file);
    setPreviewUrl(URL.createObjectURL(file));
    setResult(null);
    setConfirmedMsg(null);
    setError(null);
    if (cameraOn) stopCamera();
    void runAnalyze(file);
  };

  const handleConfirmOcr = async () => {
    if (!result?.extracted_value) return;
    const { metric, value, unit } = result.extracted_value;
    setConfirming(true);
    setError(null);
    try {
      const payload: PostMetricsPayload = {
        source: 'device_ocr',
        notes: `Confirmed via Device OCR (${value} ${unit})`,
      };
      if (metric === 'blood_glucose_mg_dl') payload.blood_glucose_mg_dl = value;
      else if (metric === 'heart_rate') payload.heart_rate = value;
      else if (metric === 'systolic_bp') payload.systolic_bp = value;
      else if (metric === 'diastolic_bp') payload.diastolic_bp = value;
      else if (metric === 'temperature_c') payload.temperature_c = value;
      else if (metric === 'radiation_msv_daily') payload.radiation_msv_daily = value;

      await onConfirmOcr(payload);
      setConfirmedMsg(`Logged ${value} ${unit} to mission timeline.`);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to log OCR value');
    } finally {
      setConfirming(false);
    }
  };

  return (
    <section className="rounded-xl border border-slate-200 bg-white shadow-xs p-4 flex flex-col gap-3">
      {/* Header */}
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-bold text-slate-900">Diagnostic module</h3>
        <span className="inline-flex items-center gap-1.5 text-[10px] font-mono font-semibold text-emerald-600 uppercase">
          <span className="w-1.5 h-1.5 rounded-full bg-emerald-500" />
          ON-DEVICE
        </span>
      </div>

      {/* Mode Tabs */}
      <div className="flex border-b border-slate-200 gap-1 overflow-x-auto">
        {MODES.map((m) => {
          const active = mode === m.id;
          return (
            <button
              key={m.id}
              type="button"
              onClick={() => {
                setMode(m.id);
                setTargetPreset(TARGET_PRESETS[m.id][0].value);
                setResult(null);
                setConfirmedMsg(null);
              }}
              className={`px-2.5 py-1.5 text-xs font-medium border-b-2 transition-colors whitespace-nowrap cursor-pointer ${
                active
                  ? 'border-slate-900 text-slate-900 font-semibold'
                  : 'border-transparent text-slate-400 hover:text-slate-700'
              }`}
            >
              {m.label}
            </button>
          );
        })}
      </div>

      {/* Target Preset & Optional Clinical Context */}
      <div className="flex flex-col gap-1.5">
        <div className="flex flex-wrap gap-1">
          {TARGET_PRESETS[mode].map((preset) => {
            const active = targetPreset === preset.value;
            return (
              <button
                key={preset.label}
                type="button"
                disabled={analyzing}
                onClick={() => {
                  setTargetPreset(preset.value);
                  if (selectedFile) {
                    void runAnalyze(selectedFile, preset.value);
                  }
                }}
                className={`px-2 py-0.5 rounded-md text-[10px] font-medium border transition-colors cursor-pointer disabled:opacity-50 ${
                  active
                    ? 'border-slate-900 bg-slate-900 text-white'
                    : 'border-slate-200 bg-slate-50 text-slate-600 hover:border-slate-300 hover:text-slate-900'
                }`}
              >
                {preset.label}
              </button>
            );
          })}
        </div>
        <input
          type="text"
          value={contextNotes}
          onChange={(e) => setContextNotes(e.target.value)}
          placeholder="Optional clinical context notes..."
          className="w-full rounded-md border border-slate-200 bg-slate-50 px-2.5 py-1 text-[11px] text-slate-800 placeholder:text-slate-400 focus:outline-none focus:border-slate-400 focus:bg-white"
        />
      </div>

      {/* Upload + Feed Toggle Bar */}
      <div className="flex items-center justify-between gap-2 rounded-lg border border-slate-200 bg-slate-50 px-3 py-2">
        <button
          type="button"
          onClick={() => fileInputRef.current?.click()}
          className="flex items-center gap-2 text-xs font-medium text-slate-700 hover:text-slate-900 cursor-pointer"
        >
          <Upload className="w-3.5 h-3.5 text-slate-500" />
          <span>Upload scan</span>
          <span className="text-[10px] font-mono text-slate-400">DICOM, PNG, JPG</span>
        </button>

        <input
          ref={fileInputRef}
          type="file"
          accept="image/*"
          className="hidden"
          onChange={(e) => {
            const file = e.target.files?.[0];
            if (file) handleFile(file);
          }}
        />

        <button
          type="button"
          onClick={() => void toggleCamera()}
          className="flex items-center gap-1.5 text-[11px] text-slate-500 cursor-pointer"
          title="Toggle live webcam feed"
        >
          <span
            className={`w-7 h-4 rounded-full p-0.5 transition-colors flex items-center ${
              cameraOn ? 'bg-emerald-500 justify-end' : 'bg-slate-300 justify-start'
            }`}
          >
            <span className="w-3 h-3 rounded-full bg-white shadow-2xs" />
          </span>
          <span>Feed</span>
        </button>
      </div>

      {error && (
        <div className="rounded-lg border border-rose-200 bg-rose-50 p-2 text-[11px] text-rose-700">
          {error}
        </div>
      )}

      {/* Dark Scan Viewport */}
      <div
        onDragOver={(e) => e.preventDefault()}
        onDrop={(e) => {
          e.preventDefault();
          const file = e.dataTransfer.files?.[0];
          if (file) handleFile(file);
        }}
        className="rounded-lg bg-slate-950 border border-slate-800 relative overflow-hidden min-h-[175px] flex items-center justify-center"
      >
        <div className="absolute top-2 left-2.5 z-10 text-[9px] font-mono text-slate-400 uppercase">
          {mode === 'ultrasound'
            ? 'US / LONG AXIS'
            : mode === 'skin_eye'
              ? 'DERM / OCULAR'
              : 'DEVICE / OCR'}
        </div>

        {cameraOn ? (
          <div className="w-full relative">
            <video
              ref={videoRef}
              autoPlay
              playsInline
              muted
              className="w-full h-44 object-cover"
            />
            <button
              type="button"
              onClick={captureAndAnalyze}
              className="absolute bottom-2 left-1/2 -translate-x-1/2 px-3 py-1 rounded-md bg-white text-slate-900 text-[11px] font-semibold shadow cursor-pointer"
            >
              Capture &amp; Analyze
            </button>
          </div>
        ) : result?.annotated_image_base64 ? (
          <img
            src={result.annotated_image_base64}
            alt="Annotated CV scan"
            className="max-h-48 w-full object-contain"
          />
        ) : previewUrl ? (
          <img
            src={previewUrl}
            alt="Scan preview"
            className="max-h-48 w-full object-contain"
          />
        ) : (
          <button
            type="button"
            onClick={() => fileInputRef.current?.click()}
            className="flex flex-col items-center justify-center text-slate-400 hover:text-slate-200 p-6 cursor-pointer"
          >
            <ScanLine className="w-6 h-6 mb-1.5 opacity-60" />
            <span className="text-[11px]">
              Drop scan image or click Upload scan
            </span>
          </button>
        )}

        {analyzing && (
          <div className="absolute inset-0 bg-slate-950/75 flex items-center justify-center text-xs font-mono text-sky-300">
            Running Hybrid CV Analysis...
          </div>
        )}
      </div>

      {/* Diagnostic Result Details */}
      {result ? (
        <div className="flex flex-col gap-2.5">
          <div className="flex items-center justify-between gap-2">
            <div>
              <div className="text-xs font-bold text-slate-900 capitalize">
                Severity: {result.severity}
              </div>
              <div className="text-[10px] text-slate-400">
                Dual Hybrid Engine • {result.provider_used} (
                {Math.round(result.confidence * 100)}%)
              </div>
            </div>
            {result.roi_boxes.length > 0 && (
              <span className="px-2 py-0.5 rounded border border-slate-200 bg-slate-50 text-[10px] font-mono text-slate-600">
                ROI DETECTED
              </span>
            )}
          </div>

          {result.extracted_value && (
            <div className="rounded-lg border border-sky-200 bg-sky-50 p-2.5 flex items-center justify-between gap-2">
              <div>
                <div className="text-[10px] font-semibold uppercase text-sky-700">
                  OCR Reading
                </div>
                <div className="text-sm font-bold font-mono text-slate-900">
                  {result.extracted_value.value} {result.extracted_value.unit}
                </div>
              </div>
              <button
                type="button"
                disabled={confirming || confirmedMsg !== null}
                onClick={() => void handleConfirmOcr()}
                className="px-2.5 py-1 rounded-md bg-slate-900 hover:bg-slate-800 text-white text-[11px] font-semibold disabled:opacity-50 cursor-pointer flex items-center gap-1"
              >
                <CheckCircle2 className="w-3 h-3" />
                {confirmedMsg ? 'Logged' : confirming ? '...' : 'Confirm & Log'}
              </button>
            </div>
          )}

          {confirmedMsg && (
            <div className="text-[11px] text-emerald-700 bg-emerald-50 border border-emerald-200 rounded-md px-2.5 py-1.5">
              {confirmedMsg}
            </div>
          )}

          <div
            className={`rounded-md border px-2.5 py-1.5 text-[11px] font-semibold ${
              ESCALATION_BANNER[result.escalation_level].cls
            }`}
          >
            {ESCALATION_BANNER[result.escalation_level].label}
          </div>

          <p className="text-[11px] text-slate-600 leading-relaxed">
            {result.explanation_simple}
          </p>

          <div className="flex flex-col gap-1.5">
            {result.action_steps.slice(0, 3).map((step, i) => (
              <div key={i} className="flex items-start gap-2 text-[11px] text-slate-700">
                <span className="font-mono text-[10px] font-semibold text-slate-400 bg-slate-100 px-1.5 py-0.5 rounded">
                  0{i + 1}
                </span>
                <span className="leading-snug">{step}</span>
              </div>
            ))}
          </div>

          {selectedFile && !analyzing && (
            <button
              type="button"
              onClick={() => void runAnalyze(selectedFile)}
              className="text-[11px] font-medium text-slate-500 hover:text-slate-900 self-end cursor-pointer"
            >
              Re-run analysis
            </button>
          )}
        </div>
      ) : (
        <div className="text-[11px] text-slate-400 leading-relaxed">
          Upload an image or enable live webcam feed to run autonomous onboard CV
          screening and escalation guidance.
        </div>
      )}
    </section>
  );
}
