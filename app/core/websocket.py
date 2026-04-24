from fastapi import WebSocket, WebSocketDisconnect
from typing import List, Dict, Any
import json
import logging

logger = logging.getLogger("nexops.ws")

class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
        logger.info(f"New WebSocket connection. Total: {len(self.active_connections)}")

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
            logger.info(f"WebSocket disconnected. Total: {len(self.active_connections)}")

    async def broadcast(self, message: Dict[str, Any]):
        """Broadcast a message to all connected clients."""
        if not self.active_connections:
            return
            
        disconnected = []
        payload = json.dumps(message)
        
        for connection in self.active_connections:
            try:
                await connection.send_text(payload)
            except Exception:
                disconnected.append(connection)
        
        # Cleanup stale connections
        for conn in disconnected:
            self.disconnect(conn)

manager = ConnectionManager()
