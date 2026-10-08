import { useState } from 'react';
import { Database, Loader2 } from 'lucide-react';
import { api } from '@/lib/api';
import { ROUTES } from '@/lib/constants';

interface SampleDataButtonProps {
  onLoaded?: () => void;
}

export function SampleDataButton({ onLoaded }: SampleDataButtonProps) {
  const [loading, setLoading] = useState(false);
  const [loaded, setLoaded] = useState(false);

  const handleLoad = async () => {
    setLoading(true);
    try {
      // Start extraction with default profile on the test corpus volume
      await api.post(ROUTES.EXTRACT_START, {
        profile: 'general_healthcare',
        volume_path: '/Volumes/dev/doc_intel/prvdr_contracts/',
        sample_mode: true,
        max_documents: 10,
      });
      setLoaded(true);
      onLoaded?.();
    } catch {
      // Error handled by API layer
    } finally {
      setLoading(false);
    }
  };

  if (loaded) {
    return (
      <span className="inline-flex items-center gap-1 text-sm text-green-600">
        <Database className="w-4 h-4" /> Sample data loaded
      </span>
    );
  }

  return (
    <button
      onClick={handleLoad}
      disabled={loading}
      className="inline-flex items-center gap-2 px-4 py-2 border border-gray-300 text-sm rounded-md hover:bg-gray-50 disabled:opacity-50"
    >
      {loading ? (
        <Loader2 className="w-4 h-4 animate-spin" />
      ) : (
        <Database className="w-4 h-4" />
      )}
      {loading ? 'Loading samples...' : 'Try Sample Data'}
    </button>
  );
}
