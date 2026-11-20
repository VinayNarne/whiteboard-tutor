"""
backend/ws.py
WebSocket event manager for Learning Platform.
Event protocol: { seq, type, payload, timestamp }
Page replay is served by GET .../pages/{id}/events (PageEvent table).

Adapted from the webinar project's ws.py (same proven pattern).
"""

import json
from typing import Dict, List, Any
from datetime import datetime, timezone
from fastapi import WebSocket


class ConnectionManager:
    def __init__(self):
        # notebook_id -> list of active WebSocket connections
        self.active_connections: Dict[str, List[WebSocket]] = {}

    async def connect(self, notebook_id: str, websocket: WebSocket):
        await websocket.accept()
        if notebook_id not in self.active_connections:
            self.active_connections[notebook_id] = []
        self.active_connections[notebook_id].append(websocket)

    def disconnect(self, notebook_id: str, websocket: WebSocket):
        if notebook_id in self.active_connections:
            if websocket in self.active_connections[notebook_id]:
                self.active_connections[notebook_id].remove(websocket)
            if not self.active_connections[notebook_id]:
                del self.active_connections[notebook_id]

    async def send_event(self, websocket: WebSocket, event_dict: dict):
        try:
            await websocket.send_text(json.dumps(event_dict))
        except Exception:
            pass

    async def broadcast_to_notebook(self, notebook_id: str, event_dict: dict):
        if notebook_id in self.active_connections:
            conns = list(self.active_connections[notebook_id])
            for conn in conns:
                try:
                    await conn.send_text(json.dumps(event_dict))
                except Exception:
                    self.disconnect(notebook_id, conn)


manager = ConnectionManager()


async def emit_notebook_event(notebook_id: str, event_type: str, payload: Dict[str, Any]) -> dict:
    """
    Broadcasts a structured event to all WebSocket subscribers for this notebook.
    Events are NOT persisted here — PageEvent table is the source of truth.
    Session-level events (chat turns, page transitions) are persisted via their own models.
    """
    now = datetime.now(timezone.utc)
    event_dict = {
        "type": event_type,
        "payload": payload,
        "timestamp": now.isoformat()
    }
    await manager.broadcast_to_notebook(notebook_id, event_dict)
    return event_dict
