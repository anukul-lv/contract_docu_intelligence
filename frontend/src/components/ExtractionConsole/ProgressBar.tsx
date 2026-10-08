import type { JobState } from '@/lib/types';

interface ProgressBarProps {
  completed: number;
  failed: number;
  total: number;
  elapsedSec: number;
  remainingSec: number;
  state: JobState | null;
}

function formatTime(sec: number): string {
  if (sec < 60) return `${Math.round(sec)}s`;
  const m = Math.floor(sec / 60);
  const s = Math.round(sec % 60);
  return `${m}m ${s}s`;
}

export function ProgressBar({ completed, failed, total, elapsedSec, remainingSec, state }: ProgressBarProps) {
  const pct = total > 0 ? Math.round(((completed + failed) / total) * 100) : 0;
  const successPct = total > 0 ? Math.round((completed / total) * 100) : 0;
  const failPct = total > 0 ? Math.round((failed / total) * 100) : 0;

  const stateLabel: Record<string, string> = {
    CREATED: 'Created',
    SUBMITTED: 'Submitted',
    PENDING: 'Pending...',
    STARTING: 'Starting...',
    RUNNING: 'Processing',
    COMPLETING: 'Completing...',
    COMPLETED: 'Completed',
    COMPLETED_WITH_ERRORS: 'Completed with errors',
    FAILED: 'Failed',
    CANCELLED: 'Cancelled',
  };

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between text-sm">
        <span className="text-gray-700 font-medium">{state ? stateLabel[state] ?? state : ''}</span>
        <span className="text-gray-500">{pct}%</span>
      </div>

      {/* Stacked progress bar */}
      <div className="w-full bg-gray-200 rounded-full h-2.5 overflow-hidden flex">
        <div className="bg-green-500 h-2.5 transition-all" style={{ width: `${successPct}%` }} />
        <div className="bg-red-400 h-2.5 transition-all" style={{ width: `${failPct}%` }} />
      </div>

      <div className="flex items-center justify-between text-xs text-gray-500">
        <span>
          {completed} done{failed > 0 && <span className="text-red-500"> &middot; {failed} failed</span>} / {total} total
        </span>
        <span>
          {elapsedSec > 0 && `${formatTime(elapsedSec)} elapsed`}
          {remainingSec > 0 && ` · ~${formatTime(remainingSec)} remaining`}
        </span>
      </div>
    </div>
  );
}
