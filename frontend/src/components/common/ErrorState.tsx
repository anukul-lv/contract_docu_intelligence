import { AlertTriangle, WifiOff, Clock, RefreshCw } from 'lucide-react';

type ErrorScenario =
  | 'partial_failure'
  | 'total_failure'
  | 'cold_start'
  | 'session_expired'
  | 'submission_failed'
  | 'network_error'
  | 'generic';

interface ErrorStateProps {
  scenario: ErrorScenario;
  message?: string;
  failedCount?: number;
  totalCount?: number;
  onRetry?: () => void;
  onViewFailures?: () => void;
}

const SCENARIO_CONFIG: Record<ErrorScenario, { icon: typeof AlertTriangle; title: string; color: string }> = {
  partial_failure: { icon: AlertTriangle, title: 'Partial Extraction Failure', color: 'text-yellow-600' },
  total_failure: { icon: AlertTriangle, title: 'Extraction Failed', color: 'text-red-600' },
  cold_start: { icon: Clock, title: 'Connecting to Compute', color: 'text-blue-600' },
  session_expired: { icon: RefreshCw, title: 'Session Expired', color: 'text-orange-600' },
  submission_failed: { icon: AlertTriangle, title: 'Submission Failed', color: 'text-red-600' },
  network_error: { icon: WifiOff, title: 'Connection Lost', color: 'text-gray-600' },
  generic: { icon: AlertTriangle, title: 'Something Went Wrong', color: 'text-red-600' },
};

export function ErrorState({ scenario, message, failedCount, totalCount, onRetry, onViewFailures }: ErrorStateProps) {
  const config = SCENARIO_CONFIG[scenario];
  const Icon = config.icon;

  return (
    <div className="flex flex-col items-center justify-center py-12 px-4 text-center" role="alert">
      <Icon className={`w-12 h-12 ${config.color} mb-4`} />
      <h3 className="text-lg font-semibold text-gray-900 mb-2">{config.title}</h3>

      {scenario === 'partial_failure' && failedCount != null && totalCount != null && (
        <p className="text-sm text-gray-600 mb-4">
          {failedCount} of {totalCount} documents failed.
        </p>
      )}

      {scenario === 'cold_start' && (
        <p className="text-sm text-gray-500 mb-4">This may take 10–15 seconds.</p>
      )}

      {scenario === 'network_error' && (
        <p className="text-sm text-gray-500 mb-4">Retrying automatically...</p>
      )}

      {message && <p className="text-sm text-gray-600 mb-4">{message}</p>}

      <div className="flex gap-3">
        {onRetry && (
          <button
            onClick={onRetry}
            className="px-4 py-2 bg-blue-600 text-white text-sm rounded-md hover:bg-blue-700"
          >
            Retry
          </button>
        )}
        {onViewFailures && (
          <button
            onClick={onViewFailures}
            className="px-4 py-2 border border-gray-300 text-sm rounded-md hover:bg-gray-50"
          >
            View Failures
          </button>
        )}
      </div>
    </div>
  );
}
