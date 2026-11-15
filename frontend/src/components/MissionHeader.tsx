import { useState } from 'react';
import {
  ArrowUpRight,
  ChevronDown,
  Flame,
  Moon,
  RotateCcw,
  ShieldAlert,
  Wind,
} from 'lucide-react';
import type { EnvironmentId, FaultId, HealthResponse, MissionState } from '../types/astra';

interface MissionHeaderProps {
  mission: MissionState;
  health: HealthResponse | null;
  backendOnline: boolean;
  attentionCount: number;
  busyAction: string | null;
  onSwitchEnvironment: (env: EnvironmentId) => void;
  onInjectFault: (fault: FaultId) => void;
  onOpenGroundComms: () => void;
}

const ENVIRONMENTS: { id: EnvironmentId; label: string; subtitle: string }[] = [
  { id: 'spacecraft', label: 'Spacecraft Transit', subtitle: 'ARTEMIS DEEP SPACE / TRANSIT TO MARS' },
  { id: 'station', label: 'Space Station', subtitle: 'ISS ORBITAL / CIS-LUNAR GATEWAY (0G)' },
  { id: 'rover', label: 'Lunar Rover', subtitle: 'SURFACE EVA RELAY / PARTIAL GRAVITY' },
  { id: 'base', label: 'Base Habitat', subtitle: 'PLANETARY SURFACE HABITAT (0.16G / 0.38G)' },
];

const FAULTS: { id: FaultId; label: string; icon: typeof Flame }[] = [
  { id: 'solar_flare', label: 'Solar Particle Event', icon: Flame },
  { id: 'co2_drift', label: 'CO2 Scrubber Drift', icon: Wind },
  { id: 'sleep_deficit', label: 'Circadian Sleep Deficit', icon: Moon },
  { id: 'reset_baseline', label: 'Reset Baseline', icon: RotateCcw },
];

export function MissionHeader({
  mission,
  health,
  backendOnline,
  attentionCount,
  busyAction,
  onSwitchEnvironment,
  onInjectFault,
  onOpenGroundComms,
}: MissionHeaderProps) {
  const [crisisMenuOpen, setCrisisMenuOpen] = useState(false);

  const currentEnv =
    ENVIRONMENTS.find((e) => e.id === mission.environment) ?? ENVIRONMENTS[0];
  const nowUtc = new Date().toISOString().slice(11, 19);

  return (
    <header className="bg-white border-b border-slate-200">
      {/* Top Navigation Bar */}
      <div className="max-w-[1640px] mx-auto px-4 sm:px-6 h-14 flex items-center justify-between gap-3 border-b border-slate-200/80">
        {/* Brand + Protocol Pill */}
        <div className="flex items-center gap-3 shrink-0">
          <div className="flex items-center gap-2">
            <div className="w-7 h-7 rounded-md bg-slate-900 flex items-center justify-center text-white font-bold text-xs tracking-tighter">
              A+
            </div>
            <span className="text-sm font-bold tracking-tight text-slate-900">
              ASTRA-MED
            </span>
          </div>
          <span className="hidden xl:inline-flex items-center px-2 py-0.5 rounded border border-slate-200 bg-slate-50 text-[10px] font-mono text-slate-500 uppercase">
            CLINICAL PROTOCOL v2.4 (OFFLINE WAL)
          </span>
        </div>

        {/* Center Segmented Environment Switcher */}
        <div className="hidden lg:flex items-center bg-slate-100 p-1 rounded-lg border border-slate-200/80">
          {ENVIRONMENTS.map((env) => {
            const active = mission.environment === env.id;
            return (
              <button
                key={env.id}
                type="button"
                disabled={busyAction !== null}
                onClick={() => onSwitchEnvironment(env.id)}
                className={`px-3 py-1 rounded-md text-xs font-medium transition-all cursor-pointer ${
                  active
                    ? 'bg-white text-slate-900 shadow-xs border border-slate-200/80 font-semibold'
                    : 'text-slate-500 hover:text-slate-800'
                } disabled:opacity-50`}
              >
                {env.label}
              </button>
            );
          })}
        </div>

        {/* Right Controls: Day, OWLT, Simulation Crisis, Transmit CTA */}
        <div className="flex items-center gap-2.5 shrink-0">
          <span className="text-xs font-semibold text-slate-700 font-mono">
            Day {mission.mission_day}
          </span>
          <span className="hidden md:inline-block text-slate-300">|</span>
          <span className="hidden md:inline-block text-xs text-slate-500">
            OWLT Latency:{' '}
            <strong className="font-mono text-slate-800">{mission.owlt_label}</strong>
          </span>

          {/* Simulation Crisis Dropdown */}
          <div className="relative">
            <button
              type="button"
              onClick={() => setCrisisMenuOpen((v) => !v)}
              className={`flex items-center gap-1 px-2.5 py-1.5 rounded-lg border text-xs font-medium cursor-pointer transition-colors ${
                mission.active_fault
                  ? 'border-rose-300 bg-rose-50 text-rose-700'
                  : 'border-slate-200 bg-white text-slate-700 hover:bg-slate-50'
              }`}
            >
              {mission.active_fault && <ShieldAlert className="w-3.5 h-3.5" />}
              <span>
                {mission.active_fault
                  ? mission.active_fault.replace('_', ' ')
                  : 'Simulation Crisis'}
              </span>
              <ChevronDown className="w-3.5 h-3.5 text-slate-400" />
            </button>

            {crisisMenuOpen && (
              <div className="absolute right-0 mt-1.5 w-52 rounded-xl border border-slate-200 bg-white shadow-lg py-1 z-40">
                {FAULTS.map((f) => {
                  const Icon = f.icon;
                  return (
                    <button
                      key={f.id}
                      type="button"
                      disabled={busyAction !== null}
                      onClick={() => {
                        setCrisisMenuOpen(false);
                        onInjectFault(f.id);
                      }}
                      className="w-full px-3 py-2 text-left text-xs text-slate-700 hover:bg-slate-50 flex items-center gap-2 cursor-pointer disabled:opacity-50"
                    >
                      <Icon className="w-3.5 h-3.5 text-slate-500" />
                      <span>{f.label}</span>
                    </button>
                  );
                })}
              </div>
            )}
          </div>

          <button
            type="button"
            onClick={onOpenGroundComms}
            className="flex items-center gap-1.5 px-3.5 py-1.5 rounded-lg bg-slate-900 hover:bg-slate-800 text-white text-xs font-semibold transition-colors cursor-pointer"
          >
            <ArrowUpRight className="w-3.5 h-3.5" />
            <span>Transmit Packet to Ground</span>
          </button>
        </div>
      </div>

      {/* Mobile Environment Switcher */}
      <div className="lg:hidden px-4 py-2 border-b border-slate-200 flex gap-1.5 overflow-x-auto bg-slate-50">
        {ENVIRONMENTS.map((env) => {
          const active = mission.environment === env.id;
          return (
            <button
              key={env.id}
              type="button"
              onClick={() => onSwitchEnvironment(env.id)}
              className={`px-2.5 py-1 rounded-md text-xs font-medium whitespace-nowrap border ${
                active
                  ? 'bg-white text-slate-900 border-slate-300 shadow-xs'
                  : 'text-slate-500 border-transparent'
              }`}
            >
              {env.label}
            </button>
          );
        })}
      </div>

      {/* Sub-header: Crew Health Overview + Active Crew + Status */}
      <div className="max-w-[1640px] mx-auto px-4 sm:px-6 py-3.5 flex flex-wrap items-center justify-between gap-4 bg-white">
        <div>
          <div className="text-[10px] font-semibold uppercase tracking-widest text-slate-400">
            AUTONOMOUS SPACE TELEMETRY &amp; RISK ASSESSMENT
          </div>
          <h1 className="text-2xl font-bold tracking-tight text-slate-900 leading-tight">
            Crew health overview
          </h1>
          <div className="text-[11px] font-mono text-slate-400 uppercase mt-0.5">
            {currentEnv.subtitle}
          </div>
        </div>

        {/* Active Crew Member */}
        <div className="flex items-center gap-4 border-l border-slate-200 pl-4">
          <div>
            <div className="text-[10px] font-semibold uppercase tracking-wider text-slate-400">
              ACTIVE CREW MEMBER
            </div>
            <div className="text-sm font-bold text-slate-900">CDR. Alex Morgan</div>
            <div className="text-[11px] text-slate-500">
              Crew ID 004 • Male, 38 • Baseline calibrated
            </div>
          </div>
          <span className="px-2.5 py-1 rounded-md border border-slate-200 bg-slate-50 text-xs font-medium text-slate-700">
            Crew 01
          </span>
        </div>

        {/* Right Telemetry Sync & Attention Summary */}
        <div className="flex flex-col items-end gap-1.5">
          <div className="flex items-center gap-3">
            {attentionCount > 0 ? (
              <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md bg-amber-50 border border-amber-200 text-xs font-medium text-amber-800">
                <span className="w-1.5 h-1.5 rounded-full bg-amber-500" />
                {attentionCount} observation{attentionCount > 1 ? 's' : ''} need attention
              </span>
            ) : (
              <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md bg-emerald-50 border border-emerald-200 text-xs font-medium text-emerald-800">
                <span className="w-1.5 h-1.5 rounded-full bg-emerald-500" />
                All systems nominal
              </span>
            )}
            <span className="text-[11px] font-mono text-slate-400">
              Last sync: {nowUtc} UTC
            </span>
          </div>
          <div className="flex items-center gap-4 text-[11px] text-slate-500">
            <span className="flex items-center gap-1.5">
              <span
                className={`w-1.5 h-1.5 rounded-full ${
                  backendOnline ? 'bg-emerald-500' : 'bg-rose-500'
                }`}
              />
              {backendOnline ? 'All 6 biosensors connected' : 'Biosensors offline'}
            </span>
            <span>
              {health?.vision_provider === 'gemini_free_ready'
                ? 'Hybrid AI + local active'
                : 'Local processing active'}
            </span>
          </div>
        </div>
      </div>
    </header>
  );
}
