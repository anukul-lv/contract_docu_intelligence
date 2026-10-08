/**
 * ProvenanceTimeline — Visual timeline of value changes (review history).
 */
import { Check, Edit3, Flag, RotateCcw, Cpu } from 'lucide-react';

interface TimelineEvent {
  actionType: string;
  previousValue?: string;
  newValue?: string;
  performedBy: string;
  performedAt: string;
}

interface ProvenanceTimelineProps {
  events: TimelineEvent[];
}

const ACTION_CONFIG: Record<string, { icon: typeof Check; color: string; label: string }> = {
  APPROVED: { icon: Check, color: 'text-green-600', label: 'Approved' },
  CORRECTED: { icon: Edit3, color: 'text-blue-600', label: 'Corrected' },
  FLAGGED: { icon: Flag, color: 'text-red-600', label: 'Flagged' },
  REVERTED: { icon: RotateCcw, color: 'text-orange-600', label: 'Reverted' },
  CLAIMED: { icon: Check, color: 'text-gray-500', label: 'Claimed' },
  AI_EXTRACTED: { icon: Cpu, color: 'text-purple-600', label: 'AI Extracted' },
};

export function ProvenanceTimeline({ events }: ProvenanceTimelineProps) {
  return (
    <div className="space-y-0">
      {events.map((event, i) => {
        const config = ACTION_CONFIG[event.actionType] || ACTION_CONFIG.CLAIMED;
        const Icon = config.icon;
        const isLast = i === events.length - 1;

        return (
          <div key={i} className="flex gap-3">
            {/* Vertical line + dot */}
            <div className="flex flex-col items-center">
              <div className={`flex h-6 w-6 items-center justify-center rounded-full border-2 bg-white ${config.color}`}>
                <Icon size={12} />
              </div>
              {!isLast && <div className="w-0.5 flex-1 bg-gray-200" />}
            </div>

            {/* Content */}
            <div className="pb-4 text-sm">
              <div className="flex items-center gap-2">
                <span className={`font-medium ${config.color}`}>{config.label}</span>
                <span className="text-xs text-gray-400">
                  {new Date(event.performedAt).toLocaleDateString()}
                </span>
              </div>
              {event.previousValue && event.newValue && (
                <div className="mt-0.5 text-xs text-gray-600">
                  <span className="line-through text-gray-400">{event.previousValue}</span>
                  {' \u2192 '}
                  <span className="font-medium">{event.newValue}</span>
                </div>
              )}
              <div className="text-xs text-gray-500">by {event.performedBy}</div>
            </div>
          </div>
        );
      })}
    </div>
  );
}
