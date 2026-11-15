import { Check } from 'lucide-react';
import type { GamificationState, RoutineTask } from '../types/astra';

interface RoutineGamificationPanelProps {
  gamification: GamificationState;
  tasks: RoutineTask[];
  completingTaskId: number | null;
  recentlyUnlocked: string[];
  onCompleteTask: (taskId: number) => void;
}

export function RoutineGamificationPanel({
  gamification,
  tasks,
  completingTaskId,
  recentlyUnlocked,
  onCompleteTask,
}: RoutineGamificationPanelProps) {
  const score = gamification.readiness_score;
  const strokeColor =
    score >= 80 ? '#2563eb' : score >= 55 ? '#f59e0b' : '#ef4444';

  const radius = 28;
  const circumference = 2 * Math.PI * radius;
  const offset =
    circumference - (Math.max(0, Math.min(100, score)) / 100) * circumference;

  const doneCount = tasks.filter((t) => t.completed).length;

  return (
    <section className="rounded-xl border border-slate-200 bg-white shadow-xs p-4 flex flex-col gap-3">
      {/* Header */}
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-bold text-slate-900">Mission routine</h3>
        <span className="text-[11px] font-mono text-slate-400">
          {doneCount} / {tasks.length} complete
        </span>
      </div>

      {/* Readiness Index Ring */}
      <div className="flex items-center gap-3.5 pb-3 border-b border-slate-100">
        <div className="relative w-16 h-16 flex items-center justify-center shrink-0">
          <svg className="w-16 h-16 -rotate-90" viewBox="0 0 68 68">
            <circle
              cx="34"
              cy="34"
              r={radius}
              fill="none"
              stroke="#e2e8f0"
              strokeWidth="5"
            />
            <circle
              cx="34"
              cy="34"
              r={radius}
              fill="none"
              stroke={strokeColor}
              strokeWidth="5"
              strokeLinecap="round"
              strokeDasharray={circumference}
              strokeDashoffset={offset}
              className="transition-all duration-500"
            />
          </svg>
          <span className="absolute text-lg font-bold font-mono text-slate-900">
            {score}
          </span>
        </div>

        <div>
          <div className="text-[10px] font-semibold uppercase tracking-wider text-slate-400">
            READINESS INDEX
          </div>
          <div className="text-sm font-bold text-slate-900">
            {score >= 80
              ? 'Fit for scheduled duties'
              : score >= 55
                ? 'Modified duty advised'
                : 'Medical review required'}
          </div>
          <div className="text-[11px] text-slate-400">
            {gamification.streak_days}-day countermeasure streak
          </div>
        </div>
      </div>

      {/* Checklist */}
      <div className="flex flex-col gap-2">
        {tasks.map((task) => {
          const busy = completingTaskId === task.id;
          return (
            <button
              key={task.id}
              type="button"
              disabled={task.completed || busy}
              onClick={() => onCompleteTask(task.id)}
              className={`w-full flex items-center justify-between gap-2 text-left py-1 rounded-md transition-colors ${
                task.completed ? 'cursor-default' : 'hover:bg-slate-50 cursor-pointer'
              }`}
            >
              <div className="flex items-center gap-2.5 min-w-0">
                <span
                  className={`w-4 h-4 rounded-xs border flex items-center justify-center shrink-0 ${
                    task.completed
                      ? 'bg-slate-900 border-slate-900 text-white'
                      : 'border-slate-300 bg-white'
                  }`}
                >
                  {task.completed && <Check className="w-3 h-3" />}
                </span>
                <span
                  className={`text-xs truncate ${
                    task.completed
                      ? 'text-slate-500 line-through'
                      : 'text-slate-800 font-medium'
                  }`}
                >
                  {task.title}
                </span>
              </div>

              <span className="px-1.5 py-0.5 rounded bg-slate-100 border border-slate-200 text-[9px] font-mono uppercase text-slate-500 shrink-0">
                {task.hazard_category.split('&')[0].trim()}
              </span>
            </button>
          );
        })}
      </div>

      {recentlyUnlocked.length > 0 && (
        <div className="rounded-md border border-emerald-200 bg-emerald-50 px-2.5 py-1.5 text-[11px] text-emerald-800">
          Unlocked: <strong>{recentlyUnlocked.join(', ')}</strong>
        </div>
      )}

      {/* Earned Badges Footer */}
      <div className="pt-2.5 border-t border-slate-100 flex flex-wrap items-center gap-1.5">
        <span className="text-[10px] font-semibold uppercase tracking-wider text-slate-400 mr-1">
          EARNED
        </span>
        {gamification.badges.slice(0, 3).map((b) => (
          <span
            key={b.code}
            title={b.description}
            className={`px-2 py-0.5 rounded-md text-[10px] font-medium border ${
              b.unlocked
                ? 'bg-emerald-50 border-emerald-200 text-emerald-700'
                : 'bg-slate-50 border-slate-200 text-slate-400'
            }`}
          >
            {b.unlocked ? '✓ ' : ''}
            {b.title}
          </span>
        ))}
      </div>
    </section>
  );
}
