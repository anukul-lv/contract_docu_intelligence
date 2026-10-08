import { useCallback, useState } from 'react';
import { api, ApiError } from '@/lib/api';
import { ROUTES } from '@/lib/constants';
import { useReviewStore } from '@/stores/reviewStore';

export function useReviewActions() {
  const [loading, setLoading] = useState<string | null>(null);
  const [conflict, setConflict] = useState(false);
  const updateItem = useReviewStore((s) => s.updateItemOptimistic);

  const handleAction = useCallback(
    async (action: () => Promise<void>, reviewId: string) => {
      setLoading(reviewId);
      setConflict(false);
      try {
        await action();
      } catch (err) {
        if (err instanceof ApiError && err.status === 409) {
          setConflict(true);
        } else {
          throw err;
        }
      } finally {
        setLoading(null);
      }
    },
    [],
  );

  const claim = useCallback(
    (reviewId: string, expectedVersion: number) =>
      handleAction(async () => {
        updateItem(reviewId, { review_status: 'IN_REVIEW' });
        await api.post(ROUTES.REVIEW_CLAIM(reviewId), { expected_version: expectedVersion });
      }, reviewId),
    [handleAction, updateItem],
  );

  const approve = useCallback(
    (reviewId: string, expectedVersion: number, comment?: string) =>
      handleAction(async () => {
        updateItem(reviewId, { review_status: 'APPROVED' });
        await api.post(ROUTES.REVIEW_APPROVE(reviewId), { expected_version: expectedVersion, comment });
      }, reviewId),
    [handleAction, updateItem],
  );

  const correct = useCallback(
    (reviewId: string, expectedVersion: number, correctedValue: string, reason: string, comment?: string) =>
      handleAction(async () => {
        updateItem(reviewId, { review_status: 'CORRECTED', human_corrected_value: correctedValue });
        await api.post(ROUTES.REVIEW_CORRECT(reviewId), {
          expected_version: expectedVersion,
          corrected_value: correctedValue,
          correction_reason: reason,
          comment,
        });
      }, reviewId),
    [handleAction, updateItem],
  );

  const flag = useCallback(
    (reviewId: string, expectedVersion: number, reason: string) =>
      handleAction(async () => {
        updateItem(reviewId, { review_status: 'FLAGGED' });
        await api.post(ROUTES.REVIEW_FLAG(reviewId), { expected_version: expectedVersion, reason });
      }, reviewId),
    [handleAction, updateItem],
  );

  return { claim, approve, correct, flag, loading, conflict };
}
