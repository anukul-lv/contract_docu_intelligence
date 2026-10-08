import { FileText, Eye } from 'lucide-react';
import { useApiQuery } from '@/hooks/useApi';
import { ROUTES } from '@/lib/constants';
import { LoadingSpinner } from '@/components/common/LoadingSpinner';

interface FileEntry {
  file_name: string;
  file_path: string;
  size_bytes: number;
  uploaded_at: string;
  document_version_id: string;
}

interface FileListProps {
  onPreview?: (id: string) => void;
}

export function FileList({ onPreview }: FileListProps) {
  const { data, isLoading } = useApiQuery<FileEntry[]>(['documents'], ROUTES.DOCUMENTS_LIST);
  const files = data?.data ?? [];

  if (isLoading) return <LoadingSpinner size="sm" label="Loading files..." />;

  if (files.length === 0) {
    return <p className="text-sm text-gray-500 py-4 text-center">No files uploaded yet.</p>;
  }

  return (
    <div className="divide-y divide-gray-100">
      {files.map((f) => (
        <div key={f.document_version_id} className="flex items-center gap-3 py-2">
          <FileText className="w-4 h-4 text-gray-400 flex-shrink-0" />
          <div className="flex-1 min-w-0">
            <p className="text-sm text-gray-800 truncate">{f.file_name}</p>
            <p className="text-xs text-gray-400">
              {(f.size_bytes / 1024).toFixed(0)} KB &middot; {new Date(f.uploaded_at).toLocaleDateString()}
            </p>
          </div>
          {onPreview && (
            <button
              onClick={() => onPreview(f.document_version_id)}
              className="text-gray-400 hover:text-blue-600"
              aria-label={`Preview ${f.file_name}`}
            >
              <Eye className="w-4 h-4" />
            </button>
          )}
        </div>
      ))}
    </div>
  );
}
