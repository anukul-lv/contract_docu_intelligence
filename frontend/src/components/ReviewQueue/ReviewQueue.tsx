import { useCallback, useEffect, useState } from 'react';
import { useReviewStore } from '@/stores/reviewStore';
import { useApiQuery } from '@/hooks/useApi';
import { ROUTES } from '@/lib/constants';
import { Pagination } from '@/components/common/Pagination';
import { LoadingSpinner } from '@/components/common/LoadingSpinner';
import type { ReviewItem, PaginationMeta } from '@/lib/types';

interface ReviewQueueProps {
  onSelectItem: (item: ReviewItem) => void;
}

export function ReviewQueue({ onSelectItem }: ReviewQueueProps) {
  const store = useReviewStore();
  const setQueue = useReviewStore((s) => s.setQueue);
  const [cursor, setCursor] = useState<string | null>(null);
  const [prevCursors, setPrevCursors] = useState<string[]>([]);

  const url = cursor
    ? `${ROUTES.REVIEW_QUEUE}?cursor=${cursor}`
    : ROUTES.REVIEW_QUEUE;

  const { data, isLoading } = useApiQuery<ReviewItem[]>(
    ['review-queue', cursor ?? 'start', JSON.stringify(store.filters)],
    url,
  );

  const items = data?.data ?? [];
  const pagination = data?.meta?.pagination as PaginationMeta | undefined;

  useEffect(() => {
    setQueue(items);
  }, [items, setQueue]);

  const handleNext = useCallback(() => {
    if (pagination?.next_cursor) {
      setPrevCursors((p) => [...p, cursor ?? '']);
      setCursor(pagination.next_cursor);
    }
  }, [pagination, cursor]);

  const handlePrev = useCallback(() => {
    const prev = prevCursors[prevCursors.length - 1];
    setPrevCursors((p) => p.slice(0, -1));
    setCursor(prev || null);
  }, [prevCursors]);

  if (isLoading) return <LoadingSpinner label="Loading review queue..." />;

  const statusColor: Record<string, string> = {
    PENDING: 'text-yellow-600 bg-yellow-50',
    IN_REVIEW: 'text-blue-600 bg-blue-50',
    APPROVED: 'text-green-600 bg-green-50',
    CORRECTED: 'text-purple-600 bg-purple-50',
    FLAGGED: 'text-red-600 bg-red-50',
  };

  return (
    <div>
      <table className="w-full text-sm">
        <thead>
          <tr className="text-left text-xs text-gray-500 uppercase border-b">
            <th className="py-2 pr-2 w-8">
              <input
                type="checkbox"
                checked={store.batchSelection.length === items.length && items.length > 0}
                onChange={() => {
                  if (store.batchSelection.length === items.length) store.clearSelection();
                  else store.selectAll(items.map((i) => i.review_id));
                }}
                aria-label="Select all"
              />
            </th>
            <th className="py-2 px-2">Field</th>
            <th className="py-2 px-2">Value</th>
            <th className="py-2 px-2">Confidence</th>
            <th className="py-2 px-2">Class</th>
            <th className="py-2 px-2">Status</th>
          </tr>
        </thead>
        <tbody>
          {items.map((item) => (
            <tr
              key={item.review_id}
              className="border-b hover:bg-gray-50 cursor-pointer"
              onClick={() => onSelectItem(item)}
            >
              <td className="py-2 pr-2" onClick={(e) => e.stopPropagation()}>
                <input
                  type="checkbox"
                  checked={store.batchSelection.includes(item.review_id)}
                  onChange={() => store.toggleBatchSelect(item.review_id)}
                  aria-label={`Select ${item.field_name}`}
                />
              </td>
              <td className="py-2 px-2 font-medium text-gray-800">{item.field_name}</td>
              <td className="py-2 px-2 text-gray-600 truncate max-w-[200px]">
                {item.human_corrected_value ?? item.ai_extracted_value ?? '—'}
              </td>
              <td className="py-2 px-2">
                <span className={`text-xs font-medium ${
                  item.ai_confidence >= 0.9 ? 'text-green-600' : item.ai_confidence >= 0.7 ? 'text-yellow-600' : 'text-red-600'
                }`}>
                  {Math.round(item.ai_confidence * 100)}%
                </span>
              </td>
              <td className="py-2 px-2">
                <span className="text-xs text-gray-500">{item.field_class.replace('_', ' ')}</span>
              </td>
              <td className="py-2 px-2">
                <span className={`text-xs px-1.5 py-0.5 rounded-full ${statusColor[item.review_status] ?? ''}`}>
                  {item.review_status}
                </span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      <Pagination
        hasMore={pagination?.has_more ?? false}
        hasPrev={prevCursors.length > 0}
        onNext={handleNext}
        onPrev={handlePrev}
        totalCount={pagination?.total_count}
        loading={isLoading}
      />
    </div>
  );
}
