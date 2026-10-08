/**
 * CitationCard — Source citation with page, section, and quoted text.
 */
import { FileText, ExternalLink } from 'lucide-react';

interface CitationCardProps {
  page: number;
  section?: string;
  text: string;
  documentName?: string;
  onViewDocument?: () => void;
}

export function CitationCard({ page, section, text, documentName, onViewDocument }: CitationCardProps) {
  return (
    <div className="rounded-lg border border-gray-200 bg-white p-3 text-sm">
      <div className="flex items-center gap-2 text-gray-600 mb-1.5">
        <FileText size={14} />
        <span className="font-medium">{documentName || 'Source Document'}</span>
        <span className="text-gray-400">|</span>
        <span>Page {page}{section ? `, \u00a7${section}` : ''}</span>
      </div>
      <blockquote className="border-l-2 border-amber-300 bg-amber-50 px-3 py-2 text-gray-700 italic text-xs">
        &ldquo;{text}&rdquo;
      </blockquote>
      {onViewDocument && (
        <button
          onClick={onViewDocument}
          className="mt-2 flex items-center gap-1 text-xs text-blue-600 hover:underline"
        >
          <ExternalLink size={12} /> View in Document
        </button>
      )}
    </div>
  );
}
