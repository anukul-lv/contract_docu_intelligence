import { useState } from 'react';
import { Play, StopCircle, RotateCcw } from 'lucide-react';
import { useExtractionStore } from '@/stores/extractionStore';
import { useApiMutation, useApiQuery } from '@/hooks/useApi';
import { useSSE } from '@/hooks/useSSE';
import { ROUTES } from '@/lib/constants';
import { ProgressBar } from './ProgressBar';
import { ErrorState } from '@/components/common/ErrorState';
import type { ExtractionStartResponse, ExtractionProfile, SSEEvent } from '@/lib/types';

export function ExtractionConsole() {
  const store = useExtractionStore();
  const [costEstimate, setCostEstimate] = useState<number | null>(null);

  const { data: profilesData } = useApiQuery<ExtractionProfile[]>(
    ['profiles'],
    ROUTES.SETTINGS_PROFILES,
  );
  const profiles = profilesData?.data ?? [];

  const startMutation = useApiMutation<
    { profile: string; volume_path?: string },
    ExtractionStartResponse
  >(ROUTES.EXTRACT_START, {
    onSuccess: (res) => {
      store.setRun(res.data.run_id, 'SUBMITTED');
      setCostEstimate(res.data.estimated_cost);
    },
  });

  const cancelMutation = useApiMutation<Record<string, never>, { cancelled: boolean }>(
    store.currentRunId ? ROUTES.EXTRACT_CANCEL(store.currentRunId) : '',
  );

  const retryMutation = useApiMutation<Record<string, never>, ExtractionStartResponse>(
    store.currentRunId ? ROUTES.EXTRACT_RETRY(store.currentRunId) : '',
  );

  // SSE for real-time progress
  useSSE({
    url: store.currentRunId ? ROUTES.EXTRACT_STREAM(store.currentRunId) : '',
    enabled: !!store.currentRunId && !!store.runState && !['COMPLETED', 'FAILED', 'CANCELLED'].includes(store.runState),
    onEvent: (event: SSEEvent) => {
      if (event.event_type === 'PROGRESS_UPDATE' && event.event_payload) {
        const p = event.event_payload as Record<string, number>;
        store.updateProgress(
          p.completed ?? store.completedDocuments,
          p.failed ?? store.failedDocuments,
          p.elapsed_sec ?? store.elapsedSec,
          p.remaining_sec ?? store.estimatedRemainingSec,
        );
      }
      if (event.event_type === 'JOB_COMPLETED') store.setRun(store.currentRunId!, 'COMPLETED');
      if (event.event_type === 'JOB_COMPLETED_WITH_ERRORS') store.setRun(store.currentRunId!, 'COMPLETED_WITH_ERRORS');
      if (event.event_type === 'JOB_FAILED') store.setRun(store.currentRunId!, 'FAILED');
    },
  });

  const isRunning = store.runState && ['SUBMITTED', 'PENDING', 'STARTING', 'RUNNING'].includes(store.runState);
  const handleStart = () => {
    startMutation.mutate({
      profile: store.selectedProfile,
      volume_path: store.connectedVolumePath ?? undefined,
    });
  };

  return (
    <div className="border rounded-lg p-4 space-y-4">
      <h3 className="text-sm font-medium text-gray-700">Extraction Console</h3>

      {/* Profile selector */}
      <div>
        <label className="block text-xs text-gray-500 mb-1">Healthcare Profile</label>
        <select
          value={store.selectedProfile}
          onChange={(e) => store.setProfile(e.target.value)}
          disabled={!!isRunning}
          className="w-full px-2 py-1.5 text-sm border border-gray-300 rounded-md"
        >
          {profiles.map((p) => (
            <option key={p.name} value={p.name}>{p.description || p.name}</option>
          ))}
          {profiles.length === 0 && <option value="general_healthcare">General Healthcare</option>}
        </select>
      </div>

      {/* Action buttons */}
      <div className="flex gap-2">
        {!isRunning && (
          <button
            onClick={handleStart}
            disabled={startMutation.isPending}
            className="flex items-center gap-2 px-4 py-2 bg-green-600 text-white text-sm rounded-md hover:bg-green-700 disabled:opacity-50"
          >
            <Play className="w-4 h-4" />
            {startMutation.isPending ? 'Starting...' : 'Start Extraction'}
          </button>
        )}
        {isRunning && (
          <button
            onClick={() => cancelMutation.mutate({})}
            className="flex items-center gap-2 px-4 py-2 bg-red-600 text-white text-sm rounded-md hover:bg-red-700"
          >
            <StopCircle className="w-4 h-4" /> Cancel
          </button>
        )}
        {store.runState === 'COMPLETED_WITH_ERRORS' && (
          <button
            onClick={() => retryMutation.mutate({})}
            className="flex items-center gap-2 px-4 py-2 bg-yellow-600 text-white text-sm rounded-md hover:bg-yellow-700"
          >
            <RotateCcw className="w-4 h-4" /> Retry Failed
          </button>
        )}
      </div>

      {/* Progress */}
      {store.currentRunId && (
        <ProgressBar
          completed={store.completedDocuments}
          failed={store.failedDocuments}
          total={store.totalDocuments}
          elapsedSec={store.elapsedSec}
          remainingSec={store.estimatedRemainingSec}
          state={store.runState}
        />
      )}

      {/* Cost estimate */}
      {costEstimate != null && (
        <p className="text-xs text-gray-500">Estimated cost: ${costEstimate.toFixed(2)}</p>
      )}

      {/* Terminal error state */}
      {store.runState === 'FAILED' && (
        <ErrorState scenario="total_failure" onRetry={() => retryMutation.mutate({})} />
      )}
      {store.runState === 'COMPLETED_WITH_ERRORS' && (
        <ErrorState
          scenario="partial_failure"
          failedCount={store.failedDocuments}
          totalCount={store.totalDocuments}
          onRetry={() => retryMutation.mutate({})}
        />
      )}
    </div>
  );
}
