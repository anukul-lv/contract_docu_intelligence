import { useCallback, useState } from 'react';
import { Upload, FileText, X } from 'lucide-react';
import { useUploadMutation } from '@/hooks/useApi';
import { ROUTES } from '@/lib/constants';

interface UploadZoneProps {
  onUploadComplete?: () => void;
}

export function UploadZone({ onUploadComplete }: UploadZoneProps) {
  const [dragActive, setDragActive] = useState(false);
  const [stagedFiles, setStagedFiles] = useState<File[]>([]);

  const uploadMutation = useUploadMutation(ROUTES.DOCUMENTS_UPLOAD, {
    invalidateKeys: [['documents']],
  });

  const handleDrag = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setDragActive(e.type === 'dragenter' || e.type === 'dragover');
  }, []);

  const handleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setDragActive(false);
    const files = Array.from(e.dataTransfer.files).filter(
      (f) => f.type === 'application/pdf' || f.name.endsWith('.pdf'),
    );
    setStagedFiles((prev) => [...prev, ...files]);
  }, []);

  const handleFileSelect = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files) {
      setStagedFiles((prev) => [...prev, ...Array.from(e.target.files!)]);
    }
  }, []);

  const removeFile = useCallback((idx: number) => {
    setStagedFiles((prev) => prev.filter((_, i) => i !== idx));
  }, []);

  const uploadAll = useCallback(async () => {
    for (const file of stagedFiles) {
      await uploadMutation.mutateAsync(file);
    }
    setStagedFiles([]);
    onUploadComplete?.();
  }, [stagedFiles, uploadMutation, onUploadComplete]);

  return (
    <div className="space-y-4">
      {/* Drop zone */}
      <div
        className={`border-2 border-dashed rounded-lg p-8 text-center transition-colors ${
          dragActive ? 'border-blue-400 bg-blue-50' : 'border-gray-300 hover:border-gray-400'
        }`}
        onDragEnter={handleDrag}
        onDragLeave={handleDrag}
        onDragOver={handleDrag}
        onDrop={handleDrop}
        role="button"
        tabIndex={0}
        aria-label="Upload documents by drag and drop or browse"
      >
        <Upload className="w-10 h-10 text-gray-400 mx-auto mb-3" />
        <p className="text-sm text-gray-600 mb-1">Drag and drop PDF contracts here</p>
        <p className="text-xs text-gray-400 mb-3">or</p>
        <label className="px-4 py-2 bg-blue-600 text-white text-sm rounded-md hover:bg-blue-700 cursor-pointer">
          Browse Files
          <input type="file" className="hidden" accept=".pdf" multiple onChange={handleFileSelect} />
        </label>
      </div>

      {/* Staged file list */}
      {stagedFiles.length > 0 && (
        <div className="space-y-2">
          <div className="flex items-center justify-between">
            <span className="text-sm font-medium text-gray-700">
              {stagedFiles.length} file{stagedFiles.length > 1 ? 's' : ''} staged
            </span>
            <button
              onClick={uploadAll}
              disabled={uploadMutation.isPending}
              className="px-4 py-1.5 bg-green-600 text-white text-sm rounded-md hover:bg-green-700 disabled:opacity-50"
            >
              {uploadMutation.isPending ? 'Uploading...' : 'Upload All'}
            </button>
          </div>
          {stagedFiles.map((file, i) => (
            <div key={`${file.name}-${i}`} className="flex items-center gap-2 p-2 bg-gray-50 rounded">
              <FileText className="w-4 h-4 text-gray-400" />
              <span className="text-sm text-gray-700 flex-1 truncate">{file.name}</span>
              <span className="text-xs text-gray-400">{(file.size / 1024).toFixed(0)} KB</span>
              <button onClick={() => removeFile(i)} className="text-gray-400 hover:text-red-500">
                <X className="w-4 h-4" />
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
