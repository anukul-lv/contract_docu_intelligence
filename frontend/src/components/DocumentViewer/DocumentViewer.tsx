import { useState } from 'react';
import { ChevronLeft, ChevronRight, ZoomIn, ZoomOut } from 'lucide-react';
import { CitationHighlight } from './CitationHighlight';

interface DocumentViewerProps {
  documentId: string;
  previewUrl?: string;
  citations?: string[];
  totalPages?: number;
}

export function DocumentViewer({ documentId, previewUrl, citations = [], totalPages = 1 }: DocumentViewerProps) {
  const [currentPage, setCurrentPage] = useState(1);
  const [zoom, setZoom] = useState(100);

  return (
    <div className="border rounded-lg overflow-hidden flex flex-col">
      {/* Toolbar */}
      <div className="flex items-center justify-between bg-gray-100 px-3 py-2 border-b">
        <div className="flex items-center gap-2">
          <button
            onClick={() => setCurrentPage((p) => Math.max(1, p - 1))}
            disabled={currentPage <= 1}
            className="p-1 hover:bg-gray-200 rounded disabled:opacity-50"
            aria-label="Previous page"
          >
            <ChevronLeft className="w-4 h-4" />
          </button>
          <span className="text-xs text-gray-600">
            Page {currentPage} of {totalPages}
          </span>
          <button
            onClick={() => setCurrentPage((p) => Math.min(totalPages, p + 1))}
            disabled={currentPage >= totalPages}
            className="p-1 hover:bg-gray-200 rounded disabled:opacity-50"
            aria-label="Next page"
          >
            <ChevronRight className="w-4 h-4" />
          </button>
        </div>
        <div className="flex items-center gap-1">
          <button
            onClick={() => setZoom((z) => Math.max(50, z - 25))}
            className="p-1 hover:bg-gray-200 rounded"
            aria-label="Zoom out"
          >
            <ZoomOut className="w-4 h-4" />
          </button>
          <span className="text-xs text-gray-600 w-10 text-center">{zoom}%</span>
          <button
            onClick={() => setZoom((z) => Math.min(200, z + 25))}
            className="p-1 hover:bg-gray-200 rounded"
            aria-label="Zoom in"
          >
            <ZoomIn className="w-4 h-4" />
          </button>
        </div>
      </div>

      {/* Document display */}
      <div className="flex-1 bg-gray-50 p-4 overflow-auto min-h-[400px]">
        {previewUrl ? (
          <iframe
            src={`${previewUrl}#page=${currentPage}`}
            className="w-full h-full border-0"
            style={{ transform: `scale(${zoom / 100})`, transformOrigin: 'top left' }}
            title={`Document ${documentId}`}
          />
        ) : (
          <div className="flex items-center justify-center h-full text-gray-400 text-sm">
            Document preview not available
          </div>
        )}
      </div>

      {/* Citations panel */}
      {citations.length > 0 && (
        <div className="border-t p-3 max-h-32 overflow-y-auto">
          <p className="text-xs text-gray-500 uppercase mb-2">Citations ({citations.length})</p>
          {citations.map((c, i) => (
            <CitationHighlight key={i} text={c} index={i + 1} />
          ))}
        </div>
      )}
    </div>
  );
}
