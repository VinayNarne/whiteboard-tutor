// All HTTP calls to our backend. Each function returns the raw Response so callers keep their own
// status/error handling. Base URL is relative ("/api"), proxied to the backend by Vite in dev.
const JSON_HEADERS = { 'Content-Type': 'application/json' };
const nb = (notebookId: string) => `/api/notebooks/${notebookId}`;
const page = (notebookId: string, pageId: string) => `${nb(notebookId)}/pages/${pageId}`;

export const listNotebooks = () => fetch(`/api/notebooks`);

export const createNotebook = (topic: string) =>
  fetch(`/api/notebooks`, { method: 'POST', headers: JSON_HEADERS, body: JSON.stringify({ topic }) });

export const getNotebook = (notebookId: string) => fetch(nb(notebookId));

export const deleteNotebook = (notebookId: string) => fetch(nb(notebookId), { method: 'DELETE' });

export const updateNotebook = (notebookId: string, body: { topic: string; title: string }) =>
  fetch(nb(notebookId), { method: 'PATCH', headers: JSON_HEADERS, body: JSON.stringify(body) });

export const createPage = (notebookId: string) =>
  fetch(`${nb(notebookId)}/pages`, { method: 'POST', headers: JSON_HEADERS, body: '{}' });

export const savePage = (notebookId: string, pageId: string) =>
  fetch(`${page(notebookId, pageId)}/save`, { method: 'POST' });

export const renamePage = (notebookId: string, pageId: string, title: string) =>
  fetch(page(notebookId, pageId), { method: 'PATCH', headers: JSON_HEADERS, body: JSON.stringify({ title }) });

export const deletePage = (notebookId: string, pageId: string) =>
  fetch(page(notebookId, pageId), { method: 'DELETE' });

export const getPageEvents = (notebookId: string, pageId: string) =>
  fetch(`${page(notebookId, pageId)}/events`);

export const undoPage = (notebookId: string, pageId: string) =>
  fetch(`${page(notebookId, pageId)}/undo`, { method: 'POST' });

export const interruptChat = (notebookId: string) =>
  fetch(`${nb(notebookId)}/interrupt`, { method: 'POST' });

export const sendChat = (notebookId: string, payload: unknown) =>
  fetch(`${nb(notebookId)}/chat`, { method: 'POST', headers: JSON_HEADERS, body: JSON.stringify(payload) });

export const transcribeVoice = (blob: Blob) =>
  fetch('/api/transcribe-voice', { method: 'POST', headers: { 'Content-Type': blob.type || 'audio/webm' }, body: blob });

// Learner card (what the tutor remembers). Every route returns the updated card.
export const getLearner = () => fetch('/api/learner');

export const addPreference = (kind: string) =>
  fetch('/api/learner/preferences', { method: 'POST', headers: JSON_HEADERS, body: JSON.stringify({ kind }) });

export const removePreference = (kind: string) =>
  fetch(`/api/learner/preferences/${encodeURIComponent(kind)}`, { method: 'DELETE' });

export const forgetKnown = (conceptId: string) =>
  fetch(`/api/learner/concepts/${encodeURIComponent(conceptId)}/known`, { method: 'DELETE' });

export const forgetMisconception = (conceptId: string) =>
  fetch(`/api/learner/concepts/${encodeURIComponent(conceptId)}/misconception`, { method: 'DELETE' });

export const forgetLearner = () => fetch('/api/learner', { method: 'DELETE' });
