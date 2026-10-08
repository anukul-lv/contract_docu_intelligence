/**
 * SuggestedFollowups — AI-generated follow-up question chips.
 */
import { MessageSquare } from 'lucide-react';

interface SuggestedFollowupsProps {
  suggestions: string[];
  onSelect: (suggestion: string) => void;
}

export function SuggestedFollowups({ suggestions, onSelect }: SuggestedFollowupsProps) {
  if (!suggestions.length) return null;

  return (
    <div className="flex flex-wrap gap-2 px-4 pb-2">
      {suggestions.map((s, i) => (
        <button
          key={i}
          onClick={() => onSelect(s)}
          className="flex items-center gap-1.5 rounded-full border border-blue-200 bg-blue-50 px-3 py-1.5 text-xs text-blue-700 hover:bg-blue-100 transition-colors"
        >
          <MessageSquare size={12} />
          {s}
        </button>
      ))}
    </div>
  );
}
