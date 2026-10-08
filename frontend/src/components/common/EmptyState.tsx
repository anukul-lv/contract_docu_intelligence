import { FileText, CheckCircle, Search, Upload } from 'lucide-react';
import { useNavigate } from 'react-router-dom';

type EmptyPage = 'explorer' | 'review' | 'ingest' | 'admin' | 'chat';

interface EmptyStateProps {
  page: EmptyPage;
  onTrySampleData?: () => void;
}

const PAGE_CONFIG: Record<EmptyPage, { icon: typeof FileText; title: string; message: string }> = {
  explorer: {
    icon: Search,
    title: 'No contracts yet',
    message: 'Upload your first contracts or try sample data to get started.',
  },
  review: {
    icon: CheckCircle,
    title: 'All caught up!',
    message: 'No items pending review. Check back later or view completed reviews.',
  },
  ingest: {
    icon: Upload,
    title: 'Ready to ingest',
    message: 'Drag and drop files or connect to a Unity Catalog volume.',
  },
  admin: {
    icon: FileText,
    title: 'No audit entries',
    message: 'Audit log entries will appear as users interact with the system.',
  },
  chat: {
    icon: FileText,
    title: 'Start a conversation',
    message: 'Ask questions about your healthcare contracts, compare terms, or explore clauses.',
  },
};

export function EmptyState({ page, onTrySampleData }: EmptyStateProps) {
  const navigate = useNavigate();
  const config = PAGE_CONFIG[page];
  const Icon = config.icon;

  return (
    <div className="flex flex-col items-center justify-center py-16 px-4 text-center">
      <Icon className="w-16 h-16 text-gray-300 mb-4" />
      <h3 className="text-lg font-semibold text-gray-700 mb-2">{config.title}</h3>
      <p className="text-sm text-gray-500 mb-6 max-w-md">{config.message}</p>

      <div className="flex gap-3">
        {page === 'explorer' && (
          <button
            onClick={() => navigate('/ingest')}
            className="px-4 py-2 bg-blue-600 text-white text-sm rounded-md hover:bg-blue-700"
          >
            Upload Contracts
          </button>
        )}
        {onTrySampleData && (
          <button
            onClick={onTrySampleData}
            className="px-4 py-2 border border-gray-300 text-sm rounded-md hover:bg-gray-50"
          >
            Try Sample Data
          </button>
        )}
      </div>
    </div>
  );
}
