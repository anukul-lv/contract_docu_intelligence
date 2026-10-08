/**
 * ToolCallDisplay — Expandable display of agent tool invocations.
 */
import { ChevronDown, ChevronRight, Code, Database, Search, Shield } from 'lucide-react';
import { useState } from 'react';
import type { ToolCall } from '../../stores/chatStore';

const TOOL_ICONS: Record<string, typeof Code> = {
  sql_query: Database,
  ai_search_tool: Search,
  ai_extract_on_demand: Code,
  review_status_check: Shield,
};

interface ToolCallDisplayProps {
  toolCalls: ToolCall[];
}

export function ToolCallDisplay({ toolCalls }: ToolCallDisplayProps) {
  const [expanded, setExpanded] = useState(false);

  if (!toolCalls.length) return null;

  return (
    <div className="mt-2 rounded-md border border-gray-200 bg-gray-50 text-xs">
      <button
        onClick={() => setExpanded(!expanded)}
        className="flex w-full items-center gap-1.5 px-3 py-2 text-gray-600 hover:text-gray-800"
      >
        {expanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
        <Code size={14} />
        {toolCalls.length} tool{toolCalls.length > 1 ? 's' : ''} used
      </button>
      {expanded && (
        <div className="space-y-2 border-t border-gray-200 px-3 py-2">
          {toolCalls.map((tc, i) => {
            const Icon = TOOL_ICONS[tc.tool] || Code;
            return (
              <div key={i} className="rounded bg-white p-2 border border-gray-100">
                <div className="flex items-center gap-1.5 font-medium text-gray-700">
                  <Icon size={12} />
                  {tc.tool}
                </div>
                <pre className="mt-1 overflow-x-auto text-gray-500 whitespace-pre-wrap">
                  {JSON.stringify(tc.args, null, 2)}
                </pre>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
