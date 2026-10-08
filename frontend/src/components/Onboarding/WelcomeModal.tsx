import { useState, useEffect } from 'react';
import { X, FileText, Search, CheckSquare, Shield } from 'lucide-react';

const STORAGE_KEY = 'healthcontracts-welcome-seen';

interface WelcomeModalProps {
  onStartTour?: () => void;
  onTrySampleData?: () => void;
}

export function WelcomeModal({ onStartTour, onTrySampleData }: WelcomeModalProps) {
  const [open, setOpen] = useState(false);

  useEffect(() => {
    if (!localStorage.getItem(STORAGE_KEY)) setOpen(true);
  }, []);

  const dismiss = () => {
    localStorage.setItem(STORAGE_KEY, 'true');
    setOpen(false);
  };

  if (!open) return null;

  const features = [
    { icon: FileText, title: 'Upload & Extract', desc: 'Ingest healthcare contracts and extract key fields with AI.' },
    { icon: Search, title: 'Explore & Filter', desc: 'Search, filter, and drill into contract details.' },
    { icon: CheckSquare, title: 'Review & Approve', desc: 'Human-in-the-loop review with trust badges.' },
    { icon: Shield, title: 'HIPAA Compliant', desc: 'PHI detection, audit logging, and role-based access.' },
  ];

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50" role="dialog" aria-modal="true">
      <div className="bg-white rounded-xl shadow-xl max-w-lg w-full mx-4 p-6">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-xl font-bold text-gray-900">Welcome to HealthContracts AI</h2>
          <button onClick={dismiss} className="text-gray-400 hover:text-gray-600" aria-label="Close">
            <X className="w-5 h-5" />
          </button>
        </div>

        <p className="text-sm text-gray-600 mb-6">
          Your intelligent platform for healthcare contract analysis. Upload contracts,
          extract structured data, review with confidence scores, and explore insights.
        </p>

        <div className="grid grid-cols-2 gap-3 mb-6">
          {features.map((f) => (
            <div key={f.title} className="flex items-start gap-2 p-3 bg-gray-50 rounded-lg">
              <f.icon className="w-5 h-5 text-blue-600 flex-shrink-0 mt-0.5" />
              <div>
                <p className="text-sm font-medium text-gray-800">{f.title}</p>
                <p className="text-xs text-gray-500">{f.desc}</p>
              </div>
            </div>
          ))}
        </div>

        <div className="flex gap-3">
          {onTrySampleData && (
            <button
              onClick={() => { onTrySampleData(); dismiss(); }}
              className="flex-1 px-4 py-2 bg-blue-600 text-white text-sm rounded-md hover:bg-blue-700"
            >
              Try Sample Data
            </button>
          )}
          {onStartTour && (
            <button
              onClick={() => { onStartTour(); dismiss(); }}
              className="flex-1 px-4 py-2 border border-gray-300 text-sm rounded-md hover:bg-gray-50"
            >
              Take a Tour
            </button>
          )}
          <button onClick={dismiss} className="px-4 py-2 text-sm text-gray-500 hover:text-gray-700">
            Skip
          </button>
        </div>
      </div>
    </div>
  );
}
