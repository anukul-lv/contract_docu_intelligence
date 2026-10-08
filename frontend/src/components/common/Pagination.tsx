import { ChevronLeft, ChevronRight } from 'lucide-react';

interface PaginationProps {
  hasMore: boolean;
  hasPrev: boolean;
  onNext: () => void;
  onPrev: () => void;
  totalCount?: number;
  loading?: boolean;
}

export function Pagination({ hasMore, hasPrev, onNext, onPrev, totalCount, loading }: PaginationProps) {
  return (
    <div className="flex items-center justify-between border-t border-gray-200 pt-3 mt-4">
      <div className="text-sm text-gray-500">
        {totalCount != null && <span>{totalCount.toLocaleString()} total</span>}
      </div>
      <div className="flex gap-2">
        <button
          onClick={onPrev}
          disabled={!hasPrev || loading}
          className="inline-flex items-center gap-1 px-3 py-1.5 text-sm border border-gray-300 rounded-md hover:bg-gray-50 disabled:opacity-50 disabled:cursor-not-allowed"
          aria-label="Previous page"
        >
          <ChevronLeft className="w-4 h-4" />
          Previous
        </button>
        <button
          onClick={onNext}
          disabled={!hasMore || loading}
          className="inline-flex items-center gap-1 px-3 py-1.5 text-sm border border-gray-300 rounded-md hover:bg-gray-50 disabled:opacity-50 disabled:cursor-not-allowed"
          aria-label="Next page"
        >
          Next
          <ChevronRight className="w-4 h-4" />
        </button>
      </div>
    </div>
  );
}
