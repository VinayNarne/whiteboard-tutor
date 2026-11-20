// frontend/src/utils/clientLog.ts
// Sends what goes wrong in the browser to the backend log (POST /api/client-log), so a session's server events and browser errors sit in one file:
// uncaught exceptions, unhandled promise rejections, console.error / console.warn, and API calls that fail (HTTP 4xx/5xx or no answer).
// It must never cause trouble of its own: everything is wrapped, batched, de-duplicated and capped, and it never reports its own requests.

type ClientEvent = {
  kind: string;
  message: string;
  source?: string;
  stack?: string;
  status?: number;
  page_url: string;
  notebook_id?: string;
  ts: string;
};

const ENDPOINT = '/api/client-log';
const MAX_PER_PAGE_LOAD = 200;
const FLUSH_MS = 1500;

let queue: ClientEvent[] = [];
let sent = 0;
let timer: number | undefined;
const recent = new Map<string, number>();

function notebookId(): string | undefined {
  try {
    return new URLSearchParams(window.location.search).get('notebook_id') || undefined;
  } catch {
    return undefined;
  }
}

function text(value: unknown): string {
  try {
    if (value instanceof Error) return `${value.name}: ${value.message}`;
    if (typeof value === 'string') return value;
    return JSON.stringify(value) ?? String(value);
  } catch {
    return String(value);
  }
}

function flush(): void {
  timer = undefined;
  if (!queue.length) return;
  const batch = queue.splice(0, 20);
  try {
    // The original fetch, so a failing report does not report itself
    originalFetch(ENDPOINT, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ events: batch }), keepalive: true }).catch(() => {});
  } catch {
    /* nothing to do */
  }
  if (queue.length) timer = window.setTimeout(flush, FLUSH_MS);
}

function report(kind: string, message: string, extra: Partial<ClientEvent> = {}): void {
  try {
    if (sent >= MAX_PER_PAGE_LOAD) return;
    const key = `${kind}|${message}`;
    const now = Date.now();
    if (now - (recent.get(key) ?? 0) < 5000) return;          // the same thing again within 5 s: once is enough
    recent.set(key, now);
    sent += 1;
    queue.push({ kind, message: message.slice(0, 2000), page_url: window.location.href.slice(0, 500), notebook_id: notebookId(), ts: new Date().toISOString(), ...extra });
    if (timer === undefined) timer = window.setTimeout(flush, FLUSH_MS);
  } catch {
    /* never throw from the reporter */
  }
}

const originalFetch: typeof window.fetch = window.fetch.bind(window);

export function installClientLog(): void {
  window.addEventListener('error', (e) => {
    report('error', e.message || text(e.error), { source: `${e.filename}:${e.lineno}:${e.colno}`, stack: e.error instanceof Error ? e.error.stack?.slice(0, 3000) : undefined });
  });
  window.addEventListener('unhandledrejection', (e) => {
    const r = e.reason;
    report('unhandledrejection', text(r), { stack: r instanceof Error ? r.stack?.slice(0, 3000) : undefined });
  });
  for (const level of ['error', 'warn'] as const) {
    const original = console[level].bind(console);
    console[level] = (...args: unknown[]) => {
      original(...args);
      report(`console.${level}`, args.map(text).join(' '));
    };
  }
  // API calls: a 4xx/5xx answer or no answer at all. The body of a failed call is NOT read (it may be large or private); only the status and the URL path.
  window.fetch = async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === 'string' ? input : input instanceof URL ? input.href : input.url;
    const path = url.replace(/^https?:\/\/[^/]+/, '').split('?')[0];
    const method = (init?.method || (typeof input !== 'string' && !(input instanceof URL) ? input.method : 'GET') || 'GET').toUpperCase();
    try {
      const res = await originalFetch(input, init);
      if (res.status >= 400 && path !== ENDPOINT) report('http_error', `${method} ${path} -> ${res.status}`, { status: res.status });
      return res;
    } catch (err) {
      if (path !== ENDPOINT) report('network_error', `${method} ${path} -> ${text(err)}`);
      throw err;
    }
  };
}
