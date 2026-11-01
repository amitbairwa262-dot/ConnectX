from typing import Dict
from fastapi import WebSocket


class CallConnectionManager:
    """Tracks one active call-signaling WebSocket per user (not per chat),
    so an incoming call or WebRTC signal can reach a user wherever they are."""

    def __init__(self):
        self.active: Dict[int, WebSocket] = {}

    async def connect(self, user_id: int, websocket: WebSocket):
        await websocket.accept()
        self.active[user_id] = websocket

    def disconnect(self, user_id: int):
        self.active.pop(user_id, None)

    async def send_to(self, user_id: int, message: dict) -> bool:
        ws = self.active.get(user_id)
        if not ws:
            return False
        try:
            await ws.send_json(message)
            return True
        except Exception:
            self.disconnect(user_id)
            return False

    def is_online(self, user_id: int) -> bool:
        return user_id in self.active


manager = CallConnectionManager()
