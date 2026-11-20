// frontend/src/hooks/useNotebookWebSocket.ts
// Adapted from the webinar project's useDeckWebSocket.ts
// One shared WS connection per notebook, multiple event types, auto-reconnect.

import { useEffect, useRef, useState, useCallback } from 'react';
import type { WsEvent } from '../types';
import { debug } from '../utils/debug';

// WebSocket connects directly to the backend — NOT through the Vite proxy.
// Vite's own HMR WebSocket conflicts with ws:true proxying and causes the
// connection to open and immediately close, breaking all real-time draw events.
import { BACKEND_WS_PORT } from '../utils/backend';

export function useNotebookWebSocket(
  notebookId: string | null,
  onEvent?: (event: WsEvent) => void
) {
  const [isConnected, setIsConnected] = useState(false);
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const isClosingExplicitlyRef = useRef(false);
  const hasConnectedOnceRef = useRef(false);
  const onEventRef = useRef(onEvent);

  useEffect(() => { onEventRef.current = onEvent; }, [onEvent]);

  const connect = useCallback(() => {
    if (!notebookId) return;

    if (reconnectTimeoutRef.current) {
      clearTimeout(reconnectTimeoutRef.current);
      reconnectTimeoutRef.current = null;
    }

    // Direct connection to the backend bypasses the Vite proxy entirely.
    const protocol = globalThis.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const host = globalThis.location.hostname; // e.g. localhost (no port)
    const wsUrl = `${protocol}//${host}:${BACKEND_WS_PORT}/api/ws/notebooks/${notebookId}`;

    isClosingExplicitlyRef.current = false;
    const ws = new WebSocket(wsUrl);
    wsRef.current = ws;

    ws.onopen = () => {
      if (isClosingExplicitlyRef.current) { ws.close(); return; }
      setIsConnected(true);
      if (hasConnectedOnceRef.current) {
        debug('[WS] Reconnected to notebook — syncing canvas and page events');
        if (typeof window !== 'undefined') {
          window.dispatchEvent(new CustomEvent('notebook_reconnected', { detail: { notebookId } }));
        }
      } else {
        hasConnectedOnceRef.current = true;
      }
    };

    ws.onmessage = (msg) => {
      try {
        const ev = JSON.parse(msg.data) as WsEvent;
        onEventRef.current?.(ev);
      } catch (err) {
        console.error('WS parse error:', err);
      }
    };

    ws.onclose = () => {
      setIsConnected(false);
      if (!isClosingExplicitlyRef.current) {
        reconnectTimeoutRef.current = setTimeout(connect, 3000);
      }
    };

    ws.onerror = () => { /* onclose fires immediately after */ };
  }, [notebookId]);

  useEffect(() => {
    connect();
    return () => {
      isClosingExplicitlyRef.current = true;
      if (reconnectTimeoutRef.current) clearTimeout(reconnectTimeoutRef.current);
      const ws = wsRef.current;
      wsRef.current = null;
      if (!ws) return;
      if (ws.readyState === WebSocket.CONNECTING) {
        ws.onopen = () => { try { ws.close(); } catch { /* ignore */ } };
        ws.onerror = () => {};
        ws.onclose = () => {};
      } else if (ws.readyState === WebSocket.OPEN) {
        try { ws.close(); } catch { /* ignore */ }
      }
    };
  }, [notebookId, connect]);

  return { isConnected };
}
