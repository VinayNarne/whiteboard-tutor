// The API's port, for the two places that talk to it directly (WebSockets). Everything else goes through the Vite
// proxy. Change it with VITE_BACKEND_PORT in frontend/.env.local when Windows has reserved port 8001.
export const BACKEND_WS_PORT = Number(import.meta.env.VITE_BACKEND_PORT) || 8001;
