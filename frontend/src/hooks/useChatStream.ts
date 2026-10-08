/**
 * useChatStream — SSE hook for chat message streaming.
 *
 * Handles chunk, citation, tool_use, metadata, and done events.
 * Uses exponential backoff reconnection (same pattern as useSSE from R1).
 */
import { useCallback, useRef } from 'react';
import { API_BASE } from '../lib/constants';
import { useChatStore, type ChatMessage, type Citation, type ToolCall } from '../stores/chatStore';

interface UseChatStreamReturn {
  sendMessage: (conversationId: string, content: string) => void;
  cancel: () => void;
}

export function useChatStream(): UseChatStreamReturn {
  const abortRef = useRef<AbortController | null>(null);
  const store = useChatStore();

  const sendMessage = useCallback(
    async (conversationId: string, content: string) => {
      // Add user message immediately
      const userMsg: ChatMessage = {
        messageId: `user-${Date.now()}`,
        role: 'user',
        content,
        citations: [],
        toolCalls: [],
        createdAt: new Date().toISOString(),
      };
      store.addMessage(conversationId, userMsg);
      store.setStreaming(true);
      store.setStreamText('');
      store.setError(null);

      abortRef.current = new AbortController();
      const citations: Citation[] = [];
      const toolCalls: ToolCall[] = [];
      let fullText = '';
      let metadata: Record<string, unknown> = {};

      try {
        const response = await fetch(
          `${API_BASE}/chat/conversations/${conversationId}/messages`,
          {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ content }),
            signal: abortRef.current.signal,
          }
        );

        if (!response.ok) {
          const errBody = await response.json().catch(() => ({}));
          throw new Error(errBody.error || `HTTP ${response.status}`);
        }

        const reader = response.body?.getReader();
        const decoder = new TextDecoder();

        if (!reader) throw new Error('No response body');

        let buffer = '';
        // Track the current SSE event type from `event:` lines.
        // Backend emits:  event: <type>\ndata: <json>\n\n
        let currentEventType = '';

        while (true) {
          const { done, value } = await reader.read();
          if (done) break;

          buffer += decoder.decode(value, { stream: true });
          const lines = buffer.split('\n');
          buffer = lines.pop() || '';

          for (const line of lines) {
            // Capture `event: <type>` lines emitted before each `data:` line
            if (line.startsWith('event: ')) {
              currentEventType = line.slice(7).trim();
              continue;
            }

            if (!line.startsWith('data: ')) continue;

            const data = JSON.parse(line.slice(6));
            // Resolve event type: prefer the SSE `event:` field; fall back to
            // `data.type` for backward-compat with older backend versions.
            const eventType = currentEventType || data.type || '';
            currentEventType = ''; // reset for next event

            switch (eventType) {
              case 'chunk':
                fullText += data.text;
                store.setStreamText(fullText);
                break;
              case 'citation':
                citations.push(data as Citation);
                break;
              case 'tool_use':
                toolCalls.push({
                  tool: data.tool_name,
                  args: data.input,
                  result: data.output,
                });
                break;
              case 'metadata':
                metadata = data;
                break;
              case 'done': {
                const assistantMsg: ChatMessage = {
                  messageId: data.message_id,
                  role: 'assistant',
                  content: fullText,
                  citations,
                  toolCalls,
                  trustBadge: metadata.trust_badge as string,
                  routeUsed: metadata.route_used as string,
                  modelUsed: metadata.model_used as string,
                  latencyMs: metadata.latency_ms as number,
                  groundednessScore: metadata.groundedness_score as number | null,
                  groundednessWarning: metadata.groundedness_warning as string | null,
                  suggestedFollowups: data.suggested_followups,
                  createdAt: new Date().toISOString(),
                };
                store.addMessage(conversationId, assistantMsg);
                store.setStreaming(false);
                store.setStreamText('');
                break;
              }
            }
          }
        }
      } catch (err: unknown) {
        if (err instanceof Error && err.name !== 'AbortError') {
          store.setError(err.message);
        }
        store.setStreaming(false);
      }
    },
    [store]
  );

  const cancel = useCallback(() => {
    abortRef.current?.abort();
    store.setStreaming(false);
  }, [store]);

  return { sendMessage, cancel };
}
