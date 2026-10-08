import { useCallback, useEffect, useRef, useState } from 'react';
import type { SSEEvent } from '@/lib/types';

type SSEStatus = 'connecting' | 'open' | 'closed' | 'error';

interface UseSSEOptions {
  url: string;
  enabled?: boolean;
  onEvent?: (event: SSEEvent) => void;
  onComplete?: () => void;
  maxReconnectDelay?: number;
}

export function useSSE({ url, enabled = true, onEvent, onComplete, maxReconnectDelay = 30_000 }: UseSSEOptions) {
  const [status, setStatus] = useState<SSEStatus>('closed');
  const lastEventIdRef = useRef<string | null>(null);
  const reconnectDelayRef = useRef(1000);
  const sourceRef = useRef<EventSource | null>(null);

  const connect = useCallback(() => {
    if (!enabled) return;

    const sseUrl = lastEventIdRef.current
      ? `${url}?lastEventId=${lastEventIdRef.current}`
      : url;

    const source = new EventSource(sseUrl);
    sourceRef.current = source;
    setStatus('connecting');

    source.onopen = () => {
      setStatus('open');
      reconnectDelayRef.current = 1000; // reset backoff
    };

    source.onmessage = (ev) => {
      try {
        const data: SSEEvent = JSON.parse(ev.data);
        if (ev.lastEventId) lastEventIdRef.current = ev.lastEventId;
        onEvent?.(data);

        // Terminal events
        const terminal = ['JOB_COMPLETED', 'JOB_COMPLETED_WITH_ERRORS', 'JOB_FAILED', 'JOB_CANCELLED'];
        if (terminal.includes(data.event_type)) {
          source.close();
          setStatus('closed');
          onComplete?.();
        }
      } catch { /* ignore parse errors */ }
    };

    source.onerror = () => {
      source.close();
      setStatus('error');

      // Exponential backoff reconnection
      const delay = Math.min(reconnectDelayRef.current, maxReconnectDelay);
      reconnectDelayRef.current = delay * 2;
      setTimeout(connect, delay + Math.random() * 500);
    };
  }, [url, enabled, onEvent, onComplete, maxReconnectDelay]);

  useEffect(() => {
    if (enabled) connect();
    return () => {
      sourceRef.current?.close();
      setStatus('closed');
    };
  }, [connect, enabled]);

  const disconnect = useCallback(() => {
    sourceRef.current?.close();
    setStatus('closed');
  }, []);

  return { status, disconnect };
}
