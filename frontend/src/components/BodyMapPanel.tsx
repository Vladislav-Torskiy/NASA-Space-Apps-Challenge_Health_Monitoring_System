import { useState } from 'react';
import bodyAnatomy from '../assets/body-anatomy.jpg';
import type { BodyZoneStatus, Severity, SystemLayerId } from '../types/astra';

interface BodyMapPanelProps {
  zones: BodyZoneStatus[];
  selectedZoneId: string;
  onSelectZone: (zoneId: string) => void;
}

const LAYERS: { id: SystemLayerId; label: string }[] = [
  { id: 'all', label: 'All' },
  { id: 'cardiovascular', label: 'Cardio' },
  { id: 'musculoskeletal', label: 'Musculoskeletal' },
  { id: 'immune_radiation', label: 'Immune' },
  { id: 'neuro_behavioral', label: 'Neuro' },
];

/**
 * Anatomy image is 896x1200 (3:4). The map container is square, the image is
 * rendered at full height and centered, so it spans 75% of the width starting at 12.5%.
 * Node coordinates below are in IMAGE percentages and get mapped to container percentages.
 */
const IMG_WIDTH_RATIO = 0.75;
const IMG_LEFT_OFFSET = (1 - IMG_WIDTH_RATIO) / 2;

function toContainerX(imgXPercent: number): number {
  return (IMG_LEFT_OFFSET + (imgXPercent / 100) * IMG_WIDTH_RATIO) * 100;
}

interface ZoneLayout {
  /** organ point on the image, in image % */
  imgX: number;
  imgY: number;
  side: 'left' | 'right';
  /** callout top, in container % */
  boxTop: number;
}

const ZONE_LAYOUT: Record<string, ZoneLayout> = {
  brain_cognition: { imgX: 50, imgY: 8, side: 'right', boxTop: 4 },
  eyes_sans: { imgX: 46.5, imgY: 12.5, side: 'left', boxTop: 17 },
  heart_vessels: { imgX: 54, imgY: 38.5, side: 'right', boxTop: 31 },
  lungs_airway: { imgX: 40, imgY: 36, side: 'left', boxTop: 40 },
  kidneys_fluid: { imgX: 58, imgY: 54, side: 'right', boxTop: 52 },
  bones_spine: { imgX: 50, imgY: 47, side: 'left', boxTop: 58 },
  immune_system: { imgX: 51, imgY: 64, side: 'right', boxTop: 70 },
  skin: { imgX: 23, imgY: 58, side: 'left', boxTop: 76 },
};

const BOX_WIDTH = 29; // container %
const BOX_EDGE_INSET = 2; // container %
const BOX_ANCHOR_DY = 4.2; // vertical offset of leader anchor from box top

const STATUS_STYLE: Record<
  Severity,
  { color: string; badge: string; label: string; text: string }
> = {
  nominal: {
    color: '#10b981',
    badge: 'bg-emerald-50 text-emerald-700 border-emerald-200',
    text: 'text-emerald-600',
    label: 'Nominal',
  },
  caution: {
    color: '#f59e0b',
    badge: 'bg-amber-50 text-amber-800 border-amber-200',
    text: 'text-amber-600',
    label: 'Caution',
  },
  critical: {
    color: '#ef4444',
    badge: 'bg-rose-50 text-rose-700 border-rose-200',
    text: 'text-rose-600',
    label: 'Critical',
  },
};

export function BodyMapPanel({
  zones,
  selectedZoneId,
  onSelectZone,
}: BodyMapPanelProps) {
  const [activeLayer, setActiveLayer] = useState<SystemLayerId>('all');

  const selectedZone =
    zones.find((z) => z.zone_id === selectedZoneId) ?? zones[0] ?? null;

  const guideSteps = selectedZone
    ? selectedZone.self_exam_guide
        .split(/(?<=[.!?])\s+/)
        .filter((s) => s.trim().length > 0)
        .slice(0, 3)
    : [];

  return (
    <div className="flex flex-col gap-3">
      {/* Section Header */}
      <div>
        <div className="text-[11px] font-bold uppercase tracking-wider text-slate-700">
          01 &nbsp; PHYSIOLOGICAL SYSTEMS MAPPING
        </div>
        <div className="text-[11px] text-slate-400">
          {zones.length} systems monitored
        </div>
      </div>

      {/* Body Map Card */}
      <section className="rounded-xl border border-slate-200 bg-white shadow-xs overflow-hidden">
        {/* Segmented layer tabs */}
        <div className="p-2.5 border-b border-slate-100">
          <div className="grid grid-cols-5 bg-slate-100 rounded-lg p-0.5">
            {LAYERS.map((layer) => {
              const active = activeLayer === layer.id;
              return (
                <button
                  key={layer.id}
                  type="button"
                  onClick={() => setActiveLayer(layer.id)}
                  className={`px-1 py-1.5 rounded-md text-[11px] font-medium truncate transition-all cursor-pointer ${
                    active
                      ? 'bg-white text-slate-900 font-semibold shadow-2xs border border-slate-200'
                      : 'text-slate-500 hover:text-slate-800'
                  }`}
                >
                  {layer.label}
                </button>
              );
            })}
          </div>
        </div>

        {/* Anatomical map */}
        <div className="relative w-full aspect-square bg-white select-none">
          <img
            src={bodyAnatomy}
            alt="Anterior anatomical view of the astronaut"
            draggable={false}
            className="absolute top-0 h-full w-auto"
            style={{ left: `${IMG_LEFT_OFFSET * 100}%`, width: `${IMG_WIDTH_RATIO * 100}%` }}
          />

          {/* Leader lines */}
          <svg
            className="absolute inset-0 w-full h-full pointer-events-none"
            viewBox="0 0 100 100"
            preserveAspectRatio="none"
          >
            {zones.map((zone) => {
              const l = ZONE_LAYOUT[zone.zone_id];
              if (!l) return null;
              const isSelected = selectedZone?.zone_id === zone.zone_id;
              const matches = activeLayer === 'all' || zone.layer === activeLayer;
              const nodeX = toContainerX(l.imgX);
              const anchorX =
                l.side === 'left' ? BOX_EDGE_INSET + BOX_WIDTH : 100 - BOX_EDGE_INSET - BOX_WIDTH;
              const anchorY = l.boxTop + BOX_ANCHOR_DY;
              const elbowX = l.side === 'left' ? anchorX + 4 : anchorX - 4;
              return (
                <polyline
                  key={zone.zone_id}
                  points={`${nodeX},${l.imgY} ${elbowX},${anchorY} ${anchorX},${anchorY}`}
                  fill="none"
                  stroke={isSelected ? STATUS_STYLE[zone.status].color : '#cbd5e1'}
                  strokeWidth={isSelected ? 1.6 : 1}
                  vectorEffect="non-scaling-stroke"
                  opacity={matches ? 1 : 0.25}
                />
              );
            })}
          </svg>

          {/* Organ nodes */}
          {zones.map((zone) => {
            const l = ZONE_LAYOUT[zone.zone_id];
            if (!l) return null;
            const st = STATUS_STYLE[zone.status];
            const isSelected = selectedZone?.zone_id === zone.zone_id;
            const matches = activeLayer === 'all' || zone.layer === activeLayer;
            return (
              <button
                key={`node-${zone.zone_id}`}
                type="button"
                aria-label={zone.label}
                onClick={() => onSelectZone(zone.zone_id)}
                className="absolute -translate-x-1/2 -translate-y-1/2 cursor-pointer transition-opacity"
                style={{
                  left: `${toContainerX(l.imgX)}%`,
                  top: `${l.imgY}%`,
                  opacity: matches ? 1 : 0.25,
                }}
              >
                {(zone.status !== 'nominal' || isSelected) && (
                  <span
                    className="absolute inset-0 rounded-full animate-ping"
                    style={{ backgroundColor: st.color, opacity: 0.35 }}
                  />
                )}
                <span
                  className="relative flex items-center justify-center w-4 h-4 rounded-full bg-white shadow-sm"
                  style={{ border: `2px solid ${st.color}` }}
                >
                  <span
                    className="w-1.5 h-1.5 rounded-full"
                    style={{ backgroundColor: st.color }}
                  />
                </span>
              </button>
            );
          })}

          {/* Callout cards */}
          {zones.map((zone) => {
            const l = ZONE_LAYOUT[zone.zone_id];
            if (!l) return null;
            const st = STATUS_STYLE[zone.status];
            const isSelected = selectedZone?.zone_id === zone.zone_id;
            const matches = activeLayer === 'all' || zone.layer === activeLayer;
            return (
              <button
                key={`card-${zone.zone_id}`}
                type="button"
                onClick={() => onSelectZone(zone.zone_id)}
                className={`absolute rounded-md bg-white/95 backdrop-blur-[1px] px-2 py-1 text-left cursor-pointer transition-all ${
                  isSelected
                    ? 'border-[1.5px] border-slate-900 shadow-sm'
                    : 'border border-slate-200 hover:border-slate-300'
                }`}
                style={{
                  top: `${l.boxTop}%`,
                  width: `${BOX_WIDTH}%`,
                  ...(l.side === 'left'
                    ? { left: `${BOX_EDGE_INSET}%` }
                    : { right: `${BOX_EDGE_INSET}%` }),
                  opacity: matches ? 1 : 0.3,
                }}
              >
                <div className="text-[10.5px] font-semibold text-slate-800 truncate leading-tight">
                  {zone.label}
                </div>
                <div className="flex items-center gap-1 mt-0.5">
                  <span
                    className="w-1.5 h-1.5 rounded-full shrink-0"
                    style={{ backgroundColor: st.color }}
                  />
                  <span className={`text-[9.5px] font-medium ${st.text}`}>{st.label}</span>
                </div>
              </button>
            );
          })}
        </div>

        <div className="flex items-center justify-between px-3 py-2 border-t border-slate-100 text-[9.5px] font-mono uppercase tracking-wider text-slate-400">
          <span>ANTERIOR VIEW</span>
          <span>ATLAS / {activeLayer === 'all' ? 'ALL SYSTEMS' : activeLayer.replace('_', ' ')}</span>
        </div>
      </section>

      {/* Selected Zone Inspector Card */}
      {selectedZone && (
        <section className="rounded-xl border border-slate-200 bg-white shadow-xs p-4 flex flex-col gap-3">
          <div className="flex items-start justify-between gap-2">
            <div>
              <div className="text-[10px] font-semibold uppercase tracking-wider text-slate-400">
                SELECTED ZONE
              </div>
              <h3 className="text-lg font-bold text-slate-900 leading-tight">
                {selectedZone.label}
              </h3>
            </div>
            <span
              className={`inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-md text-[11px] font-semibold border ${
                STATUS_STYLE[selectedZone.status].badge
              }`}
            >
              {STATUS_STYLE[selectedZone.status].label}
            </span>
          </div>

          <div>
            <div className="text-[10px] font-bold uppercase tracking-wider text-sky-700 mb-1">
              NASA HRP / {selectedZone.space_hazard.split('(')[0].trim().toUpperCase()}
            </div>
            <p className="text-xs font-semibold text-slate-800 leading-snug">
              {selectedZone.summary}
            </p>
            <p className="text-[11px] text-slate-500 mt-1 leading-relaxed">
              {selectedZone.why_exam_needed}
            </p>
          </div>

          <div className="border-t border-slate-100 pt-2.5">
            <div className="text-[10px] font-semibold uppercase tracking-wider text-slate-400 mb-2">
              GUIDED SELF-EXAMINATION
            </div>
            <div className="flex flex-col gap-1.5">
              {guideSteps.map((step, i) => (
                <div key={i} className="flex items-start gap-2.5 text-xs text-slate-700">
                  <span className="font-mono text-[10px] font-semibold text-slate-400 pt-0.5">
                    0{i + 1}
                  </span>
                  <span className="leading-snug">{step}</span>
                </div>
              ))}
            </div>
          </div>
        </section>
      )}
    </div>
  );
}
