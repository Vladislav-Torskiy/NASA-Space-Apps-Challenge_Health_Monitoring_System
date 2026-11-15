import { useState } from 'react';
import { CheckCircle2, Radio, Send, X } from 'lucide-react';
import type { GroundTransmitResponse, MissionState } from '../types/astra';

interface GroundCommsModalProps {
  open: boolean;
  mission: MissionState;
  onClose: () => void;
  onTransmit: (notes?: string) => Promise<GroundTransmitResponse>;
}

export function GroundCommsModal({
  open,
  mission,
  onClose,
  onTransmit,
}: GroundCommsModalProps) {
  const [notes, setNotes] = useState('');
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [packet, setPacket] = useState<GroundTransmitResponse | null>(null);

  if (!open) return null;

  const handleSend = async () => {
    setSending(true);
    setError(null);
    try {
      const res = await onTransmit(notes);
      setPacket(res);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Transmission failed');
    } finally {
      setSending(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 bg-slate-900/50 backdrop-blur-xs flex items-center justify-center p-4">
      <div className="w-full max-w-2xl rounded-2xl border border-slate-200 bg-white p-5 shadow-2xl max-h-[90vh] overflow-y-auto flex flex-col gap-4">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2.5">
            <Radio className="w-5 h-5 text-slate-900" />
            <div>
              <h3 className="text-base font-bold text-slate-900">
                Transmit Telemetry Packet to Flight Surgeon
              </h3>
              <p className="text-xs text-slate-500">
                Current One-Way Light Time (OWLT):{' '}
                <span className="font-mono font-semibold text-slate-800">
                  {mission.owlt_label}
                </span>
              </p>
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="p-1.5 rounded-lg text-slate-400 hover:text-slate-800 hover:bg-slate-100 cursor-pointer"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        {error && (
          <div className="rounded-lg border border-rose-200 bg-rose-50 p-2.5 text-xs text-rose-700">
            {error}
          </div>
        )}

        <div className="flex flex-col gap-2">
          <label className="text-xs font-medium text-slate-700">
            Astronaut Note for Ground Medical Team
          </label>
          <div className="flex gap-2">
            <input
              type="text"
              placeholder="e.g., Requesting review of elevated HR and CO2 drift..."
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              className="flex-1 rounded-lg border border-slate-300 bg-white px-3 py-2 text-xs text-slate-900 focus:outline-none focus:border-slate-900"
            />
            <button
              type="button"
              disabled={sending}
              onClick={handleSend}
              className="px-4 py-2 rounded-lg bg-slate-900 hover:bg-slate-800 text-white text-xs font-semibold flex items-center gap-1.5 disabled:opacity-50 cursor-pointer"
            >
              <Send className="w-3.5 h-3.5" />
              {sending ? 'Transmitting...' : 'Send Packet'}
            </button>
          </div>
        </div>

        {packet && (
          <div className="rounded-xl border border-slate-200 bg-slate-50 p-4 flex flex-col gap-3">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <span className="text-xs font-mono font-semibold text-slate-800">
                Packet #{packet.packet_id} • {packet.status}
              </span>
              <span className="text-[11px] font-mono text-slate-500">
                {new Date(packet.created_at).toLocaleString()}
              </span>
            </div>

            <div className="flex flex-wrap items-center gap-2">
              {packet.status_timeline.map((step, i) => (
                <div
                  key={step}
                  className="flex items-center gap-1.5 text-[11px] px-2.5 py-1 rounded-full bg-emerald-50 border border-emerald-200 text-emerald-700"
                >
                  <CheckCircle2 className="w-3 h-3" />
                  <span>
                    {i + 1}. {step}
                  </span>
                </div>
              ))}
            </div>

            <div className="rounded-lg border border-amber-200 bg-amber-50 p-3">
              <div className="text-[10px] font-semibold uppercase tracking-wider text-amber-800 mb-1">
                Interim Autonomous Guidance (While Awaiting Ground Reply)
              </div>
              <ul className="space-y-1 text-xs text-amber-900">
                {packet.interim_guidance.map((g, idx) => (
                  <li key={idx}>• {g}</li>
                ))}
              </ul>
            </div>

            <div>
              <div className="text-[10px] font-semibold uppercase tracking-wider text-slate-500 mb-1">
                Compact Telemetry Summary
              </div>
              <pre className="text-[11px] font-mono text-slate-800 bg-white border border-slate-200 rounded-lg p-2.5 whitespace-pre-wrap">
                {packet.text_summary}
              </pre>
            </div>

            <details className="text-xs">
              <summary className="cursor-pointer text-slate-700 hover:text-slate-900 font-medium">
                Inspect Raw JSON Telemetry Packet
              </summary>
              <pre className="mt-2 max-h-48 overflow-auto text-[11px] font-mono text-slate-700 bg-white border border-slate-200 rounded-lg p-2.5">
                {JSON.stringify(packet.payload, null, 2)}
              </pre>
            </details>
          </div>
        )}
      </div>
    </div>
  );
}
