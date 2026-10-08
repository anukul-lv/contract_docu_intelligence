/** 4-signal confidence breakdown bar chart. Weights: 50/20/20/10. */

interface Signal {
  name: string;
  score: number;
  weight: number;
  color: string;
}

interface ConfidenceExplainerProps {
  overall: number;
  signals?: {
    ai_confidence: number;
    format_valid: number;
    cross_field_valid: number;
    citation_present: number;
  };
}

export function ConfidenceExplainer({ overall, signals }: ConfidenceExplainerProps) {
  const bars: Signal[] = signals
    ? [
        { name: 'AI Extraction', score: signals.ai_confidence, weight: 50, color: 'bg-blue-500' },
        { name: 'Format Valid', score: signals.format_valid, weight: 20, color: 'bg-green-500' },
        { name: 'Cross-Field', score: signals.cross_field_valid, weight: 20, color: 'bg-yellow-500' },
        { name: 'Citation', score: signals.citation_present, weight: 10, color: 'bg-purple-500' },
      ]
    : [];

  const overallColor =
    overall >= 0.9 ? 'text-green-700' : overall >= 0.7 ? 'text-yellow-700' : 'text-red-700';

  return (
    <div className="space-y-3" aria-label={`Confidence score: ${Math.round(overall * 100)}%`}>
      <div className="flex items-center justify-between">
        <span className="text-sm font-medium text-gray-700">Confidence</span>
        <span className={`text-lg font-bold ${overallColor}`}>
          {Math.round(overall * 100)}%
        </span>
      </div>

      {/* Overall bar */}
      <div className="w-full bg-gray-200 rounded-full h-2">
        <div
          className={`h-2 rounded-full transition-all ${
            overall >= 0.9 ? 'bg-green-500' : overall >= 0.7 ? 'bg-yellow-500' : 'bg-red-500'
          }`}
          style={{ width: `${Math.round(overall * 100)}%` }}
          role="progressbar"
          aria-valuenow={Math.round(overall * 100)}
          aria-valuemin={0}
          aria-valuemax={100}
        />
      </div>

      {/* Signal breakdown */}
      {bars.length > 0 && (
        <div className="space-y-2 pt-2 border-t border-gray-100">
          {bars.map((b) => (
            <div key={b.name} className="flex items-center gap-2">
              <span className="text-xs text-gray-500 w-24 truncate">
                {b.name} ({b.weight}%)
              </span>
              <div className="flex-1 bg-gray-100 rounded-full h-1.5">
                <div
                  className={`h-1.5 rounded-full ${b.color}`}
                  style={{ width: `${Math.round(b.score * 100)}%` }}
                />
              </div>
              <span className="text-xs text-gray-600 w-8 text-right">
                {Math.round(b.score * 100)}%
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
