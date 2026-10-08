/**
 * ConversationList — Left sidebar showing conversation history.
 */
import { MessageSquare, Plus, Trash2 } from 'lucide-react';
import type { Conversation } from '../../stores/chatStore';

interface ConversationListProps {
  conversations: Conversation[];
  activeId: string | null;
  onSelect: (id: string) => void;
  onCreate: () => void;
  onDelete: (id: string) => void;
}

function formatDate(dateStr?: string): string {
  if (!dateStr) return '';
  const d = new Date(dateStr);
  const now = new Date();
  const diff = now.getTime() - d.getTime();
  if (diff < 86400000) return 'Today';
  if (diff < 172800000) return 'Yesterday';
  return d.toLocaleDateString();
}

export function ConversationList({
  conversations,
  activeId,
  onSelect,
  onCreate,
  onDelete,
}: ConversationListProps) {
  // Group by date
  const grouped = conversations.reduce<Record<string, Conversation[]>>((acc, conv) => {
    const label = formatDate(conv.lastMessageAt || conv.createdAt);
    (acc[label] = acc[label] || []).push(conv);
    return acc;
  }, {});

  return (
    <aside className="flex h-full w-60 flex-col border-r bg-gray-50">
      <div className="p-3">
        <button
          onClick={onCreate}
          className="flex w-full items-center gap-2 rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm hover:bg-gray-100"
        >
          <Plus size={16} /> New Chat
        </button>
      </div>

      <div className="flex-1 overflow-y-auto px-2">
        {Object.entries(grouped).map(([label, convs]) => (
          <div key={label} className="mb-3">
            <div className="px-2 py-1 text-xs font-medium text-gray-500">{label}</div>
            {convs.map((conv) => (
              <div
                key={conv.conversationId}
                className={`group flex items-center gap-2 rounded-md px-2 py-1.5 text-sm cursor-pointer ${
                  activeId === conv.conversationId
                    ? 'bg-blue-100 text-blue-800'
                    : 'text-gray-700 hover:bg-gray-100'
                }`}
                onClick={() => onSelect(conv.conversationId)}
              >
                <MessageSquare size={14} className="shrink-0" />
                <span className="truncate flex-1">
                  {conv.title || `Chat ${conv.conversationId.slice(0, 8)}`}
                </span>
                <button
                  onClick={(e) => {
                    e.stopPropagation();
                    onDelete(conv.conversationId);
                  }}
                  className="hidden group-hover:block text-gray-400 hover:text-red-500"
                  aria-label="Delete conversation"
                >
                  <Trash2 size={12} />
                </button>
              </div>
            ))}
          </div>
        ))}
      </div>
    </aside>
  );
}
