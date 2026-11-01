from typing import Dict, Set
from fastapi import WebSocket


class ConnectionManager:
    """Keeps track of which users are connected to which chat rooms,
    so a new message can be pushed instantly to everyone in that chat."""

    def __init__(self):
        # chat_id -> set of (user_id, websocket)
        self.active_connections: Dict[int, Set[tuple]] = {}

    async def connect(self, chat_id: int, user_id: int, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.setdefault(chat_id, set()).add((user_id, websocket))

    def disconnect(self, chat_id: int, user_id: int, websocket: WebSocket):
        connections = self.active_connections.get(chat_id)
        if connections:
            connections.discard((user_id, websocket))
            if not connections:
                del self.active_connections[chat_id]

    async def broadcast(self, chat_id: int, message: dict, exclude_user_id: int = None):
        connections = self.active_connections.get(chat_id, set())
        for user_id, ws in list(connections):
            if exclude_user_id is not None and user_id == exclude_user_id:
                continue
            try:
                await ws.send_json(message)
            except Exception:
                # connection probably dropped — clean it up
                self.disconnect(chat_id, user_id, ws)


manager = ConnectionManager()
