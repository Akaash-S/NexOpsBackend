from fastapi import WebSocket, WebSocketDisconnect
from typing import List, Dict, Any
import json
import logging

import asyncio

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

    async def broadcast_local(self, message: Dict[str, Any]):
        """Broadcast a message to all connected clients local to this process."""
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

    async def broadcast(self, message: Dict[str, Any]):
        """Broadcast a message across all server processes via Redis Pub/Sub."""
        from app.core.redis import redis_client
        if redis_client:
            try:
                # Publish to Redis channel so all uvicorn processes hear it
                await redis_client.publish("nexops:ws_broadcast", json.dumps(message))
                logger.info("Successfully published WS broadcast to Redis Pub/Sub")
            except Exception as e:
                logger.error(f"Failed to publish WS broadcast to Redis: {e}")
        
        # Also broadcast locally in the current process context
        await self.broadcast_local(message)

manager = ConnectionManager()

async def start_ws_redis_listener():
    """Starts background task listening to Redis Pub/Sub WS channel."""
    from app.core.redis import redis_client
    if not redis_client:
        logger.warning("Redis client not available for WS Pub/Sub.")
        return

    try:
        pubsub = redis_client.pubsub()
        await pubsub.subscribe("nexops:ws_broadcast")
        logger.info("Subscribed to Redis WS broadcast channel: nexops:ws_broadcast")
        
        while True:
            try:
                message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
                if message and message["type"] == "message":
                    data = json.loads(message["data"])
                    await manager.broadcast_local(data)
            except asyncio.CancelledError:
                logger.info("Redis WS subscription listener cancelled.")
                break
            except Exception as err:
                logger.error(f"Error in Redis WS subscription loop: {err}")
                await asyncio.sleep(1.0)
    except Exception as e:
        logger.error(f"Failed to start Redis WS subscription: {e}")
