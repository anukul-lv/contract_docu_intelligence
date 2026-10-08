/**
 * ChatInterface — Main chat area with message list, streaming display, and input.
 */
import { useEffect, useRef } from 'react';
import { useChatStore } from '../../stores/chatStore';
import { useChatStream } from '../../hooks/useChatStream';
import { ChatMessage } from './ChatMessage';
import { ChatInput } from './ChatInput';
import { SuggestedFollowups } from './SuggestedFollowups';
import { EmptyState } from '../common/EmptyState';

const STARTER_PROMPTS: Record<string, string[]> = {
  default: [
    'Which provider contracts expire next quarter?',
    'Show all contracts missing BAA documentation',
    'Compare capitation rates across Texas MCO contracts',
  ],
};

interface ChatInterfaceProps {
  conversationId: string;
}

export function ChatInterface({ conversationId }: ChatInterfaceProps) {
  const { messages, isStreaming, currentStreamText, error } = useChatStore();
  const { sendMessage } = useChatStream();
  const scrollRef = useRef<HTMLDivElement>(null);

  const convMessages = messages[conversationId] || [];

  // Auto-scroll on new messages
  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: 'smooth' });
  }, [convMessages.length, currentStreamText]);

  const handleSend = (content: string) => {
    sendMessage(conversationId, content);
  };

  return (
    <div className="flex h-full flex-col">
      {/* Scope selector */}
      <div className="flex items-center gap-2 border-b px-4 py-2 bg-white">
        <label className="text-xs text-gray-500">Scope:</label>
        <select className="rounded border border-gray-300 px-2 py-1 text-sm">
          <option value="all">All Contracts</option>
          <option value="document">Single Document</option>
          <option value="contract_type">Contract Type</option>
        </select>
      </div>

      {/* Messages area */}
      <div ref={scrollRef} className="flex-1 overflow-y-auto">
        {convMessages.length === 0 && !isStreaming ? (
          <div className="flex h-full items-center justify-center">
            <div className="text-center">
              <EmptyState page="chat" />
              <div className="mt-4">
                <SuggestedFollowups
                  suggestions={STARTER_PROMPTS.default}
                  onSelect={handleSend}
                />
              </div>
            </div>
          </div>
        ) : (
          <div>
            {convMessages.map((msg) => (
              <ChatMessage key={msg.messageId} message={msg} />
            ))}
            {isStreaming && (
              <ChatMessage
                message={{
                  messageId: 'streaming',
                  role: 'assistant',
                  content: '',
                  citations: [],
                  toolCalls: [],
                  createdAt: new Date().toISOString(),
                }}
                isStreaming
                streamText={currentStreamText}
              />
            )}
          </div>
        )}
      </div>

      {/* Error display */}
      {error && (
        <div className="border-t border-red-200 bg-red-50 px-4 py-2 text-sm text-red-700">
          {error}
        </div>
      )}

      {/* Input */}
      <ChatInput
        onSend={handleSend}
        disabled={isStreaming}
        placeholder={isStreaming ? 'Waiting for response...' : undefined}
      />
    </div>
  );
}
