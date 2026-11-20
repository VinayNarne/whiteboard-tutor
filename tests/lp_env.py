"""Where the live tests find the app. Defaults match the README; override when Windows has reserved port 8001:
    LP_BACKEND=http://127.0.0.1:8100   (and run Vite with VITE_BACKEND_PORT=8100 in frontend/.env.local)
    LP_FRONTEND=http://localhost:5174  (only for the standalone scripts; pytest tests auto-detect 5173/5174)
"""
import os

BACKEND = os.environ.get("LP_BACKEND", "http://127.0.0.1:8001")
API = f"{BACKEND}/api"
FRONTEND = os.environ.get("LP_FRONTEND", "http://localhost:5174")
