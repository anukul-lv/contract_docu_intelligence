import { CheckCheck, X } from 'lucide-react';
import { useReviewStore } from '@/stores/reviewStore';
import { useApiMutation } from '@/hooks/useApi';
import { ROUTES } from '@/lib/constants';

export function BatchActions() {
  const selection = useReviewStore((s) => s.batchSelection);
  const items = useReviewStore((s) => s.queueItems);
  const clearSelection = useReviewStore((s) => s.clearSelection);

  const batchApprove = useApiMutation<{ review_ids: string[] }, { approved_count: number }>(
    ROUTES.REVIEW_BATCH_APPROVE,
    { invalidateKeys: [['review-queue']] },
  );

  if (selection.length === 0) return null;

  // Filter out critical items per R1_06 spec
  const criticalIds = new Set(
    items
      .filter((i) => i.field_class === 'critical_financial' || i.field_class === 'critical_compliance')
      .map((i) => i.review_id),
  );
  const eligibleIds = selection.filter((id) => !criticalIds.has(id));
  const blockedCount = selection.length - eligibleIds.length;

  return (
    <div className="flex items-center gap-3 bg-blue-50 border border-blue-200 rounded-md px-4 py-2">
      <span className="text-sm text-blue-800">
        {selection.length} selected
        {blockedCount > 0 && (
          <span className="text-xs text-orange-600 ml-1">({blockedCount} critical — manual only)</span>
        )}
      </span>

      <button
        onClick={() => batchApprove.mutate({ review_ids: eligibleIds })}
        disabled={eligibleIds.length === 0 || batchApprove.isPending}
        className="flex items-center gap-1 px-3 py-1 bg-green-600 text-white text-sm rounded-md hover:bg-green-700 disabled:opacity-50"
      >
        <CheckCheck className="w-4 h-4" />
        {batchApprove.isPending ? 'Approving...' : `Batch Approve (${eligibleIds.length})`}
      </button>

      <button
        onClick={clearSelection}
        className="text-gray-500 hover:text-gray-700"
        aria-label="Clear selection"
      >
        <X className="w-4 h-4" />
      </button>
    </div>
  );
}
