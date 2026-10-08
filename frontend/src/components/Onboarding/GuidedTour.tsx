import { useState } from 'react';
import { ChevronRight, ChevronLeft, X } from 'lucide-react';

interface TourStep {
  title: string;
  description: string;
  targetSelector?: string;
}

const TOUR_STEPS: TourStep[] = [
  { title: 'Upload Zone', description: 'Drag and drop PDF contracts here, or connect to a Unity Catalog volume for batch ingestion.' },
  { title: 'Profile Selector', description: 'Choose a healthcare extraction profile to match your contract type. 5 built-in profiles available.' },
  { title: 'Extraction Console', description: 'Start extraction, monitor real-time progress via SSE, and manage runs.' },
  { title: 'Review Queue', description: 'Review AI-extracted fields with trust badges. Approve, correct, or flag with optimistic locking.' },
  { title: 'Contract Explorer', description: 'Browse all contracts with filters. Drill into detail views with confidence breakdowns.' },
  { title: 'Trust Badges', description: 'Color-coded badges show data provenance: Verified, AI Extracted, Corrected, Flagged, or Low Confidence.' },
];

interface GuidedTourProps {
  onComplete?: () => void;
}

export function GuidedTour({ onComplete }: GuidedTourProps) {
  const [step, setStep] = useState(0);
  const [active, setActive] = useState(true);

  if (!active) return null;

  const current = TOUR_STEPS[step];
  const isLast = step === TOUR_STEPS.length - 1;

  const handleClose = () => {
    setActive(false);
    onComplete?.();
  };

  return (
    <div className="fixed bottom-6 right-6 bg-white rounded-xl shadow-xl border w-80 p-4 z-40">
      <div className="flex items-center justify-between mb-2">
        <span className="text-xs text-gray-400">Step {step + 1} of {TOUR_STEPS.length}</span>
        <button onClick={handleClose} className="text-gray-400 hover:text-gray-600" aria-label="Close tour">
          <X className="w-4 h-4" />
        </button>
      </div>

      <h4 className="text-sm font-semibold text-gray-900 mb-1">{current.title}</h4>
      <p className="text-xs text-gray-600 mb-4">{current.description}</p>

      <div className="flex items-center justify-between">
        <button
          onClick={() => setStep((s) => s - 1)}
          disabled={step === 0}
          className="flex items-center gap-1 text-xs text-gray-500 hover:text-gray-700 disabled:opacity-50"
        >
          <ChevronLeft className="w-3 h-3" /> Back
        </button>

        {isLast ? (
          <button
            onClick={handleClose}
            className="px-3 py-1 bg-blue-600 text-white text-xs rounded-md hover:bg-blue-700"
          >
            Done
          </button>
        ) : (
          <button
            onClick={() => setStep((s) => s + 1)}
            className="flex items-center gap-1 px-3 py-1 bg-blue-600 text-white text-xs rounded-md hover:bg-blue-700"
          >
            Next <ChevronRight className="w-3 h-3" />
          </button>
        )}
      </div>

      {/* Progress dots */}
      <div className="flex justify-center gap-1 mt-3">
        {TOUR_STEPS.map((_, i) => (
          <div
            key={i}
            className={`w-1.5 h-1.5 rounded-full ${i === step ? 'bg-blue-600' : 'bg-gray-200'}`}
          />
        ))}
      </div>
    </div>
  );
}
