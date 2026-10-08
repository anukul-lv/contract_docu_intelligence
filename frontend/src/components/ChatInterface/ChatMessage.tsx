/**
 * ChatMessage — Single chat message with citations, trust badge, and feedback.
 */
import { Bot, ThumbsDown, ThumbsUp, User } from 'lucide-react';
import type { ChatMessage as ChatMessageType } from '../../stores/chatStore';
import { useChatStore } from '../../stores/chatStore';
import { TrustBadge } from '../TrustBadge/TrustBadge';
import { ToolCallDisplay } from './ToolCallDisplay';

interface ChatMessageProps {
  message: ChatMessageType;
  isStreaming?: boolean;
  streamText?: string;
}

export function ChatMessage({ message, isStreaming, streamText }: ChatMessageProps) {
  const { submitFeedback } = useChatStore();
  const isUser = message.role === 'user';
  const displayText = isStreaming ? streamText || '' : message.content;

  return (
    <div className={`flex gap-3 px-4 py-3 ${isUser ? 'bg-white' : 'bg-gray-50'}`}>
      <div className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-full ${
        isUser ? 'bg-blue-100 text-blue-700' : 'bg-purple-100 text-purple-700'
      }`}>
        {isUser ? <User size={16} /> : <Bot size={16} />}
      </div>

      <div className="min-w-0 flex-1 space-y-2">
        {/* Message text */}
        <div className="prose prose-sm max-w-none whitespace-pre-wrap">
          {displayText}
          {isStreaming && <span className="animate-pulse">█</span>}
        </div>

        {/* Groundedness warning */}
        {message.groundednessWarning && (
          <div className="rounded-md border border-orange-200 bg-orange-50 px-3 py-1.5 text-xs text-orange-700">
            {message.groundednessWarning}
          </div>
        )}

        {/* Citations */}
        {message.citations.length > 0 && (
          <div className="flex flex-wrap gap-1.5">
            {message.citations.map((c, i) => (
              <span
                key={i}
                className="inline-flex items-center rounded-full bg-amber-50 border border-amber-200 px-2 py-0.5 text-xs text-amber-800 cursor-pointer hover:bg-amber-100"
                title={c.text}
              >
                {c.document}, Page {c.page}{c.section ? `, §${c.section}` : ''}
              </span>
            ))}
          </div>
        )}

        {/* Tool calls */}
        {!isUser && <ToolCallDisplay toolCalls={message.toolCalls} />}

        {/* Footer: trust badge, route, feedback */}
        {!isUser && !isStreaming && (
          <div className="flex items-center gap-3 text-xs text-gray-500">
            {message.trustBadge && (
              <TrustBadge type={message.trustBadge as any} size="sm" />
            )}
            {message.routeUsed && (
              <span>Route {message.routeUsed}</span>
            )}
            {message.latencyMs != null && (
              <span>{(message.latencyMs / 1000).toFixed(1)}s</span>
            )}
            <div className="ml-auto flex items-center gap-1">
              <button
                onClick={() => submitFeedback(message.messageId, 'positive')}
                className={`rounded p-1 hover:bg-green-100 ${
                  message.feedbackRating === 'positive' ? 'text-green-600 bg-green-50' : 'text-gray-400'
                }`}
                aria-label="Helpful"
              >
                <ThumbsUp size={14} />
              </button>
              <button
                onClick={() => submitFeedback(message.messageId, 'negative')}
                className={`rounded p-1 hover:bg-red-100 ${
                  message.feedbackRating === 'negative' ? 'text-red-600 bg-red-50' : 'text-gray-400'
                }`}
                aria-label="Not helpful"
              >
                <ThumbsDown size={14} />
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
