# supportwiz/server/connection_manager.py

import uuid
from typing import Any, Dict, Optional

from fastapi import WebSocket
from fastapi.websockets import WebSocketDisconnect

'''
✔ Your decorator-based router
✔ lifespan startup
✔ Multiple independent WebSocket clients
✔ Optional per-client state (chat handlers, sessions, etc.)
✔ Broadcast support
✔ Clean disconnect handling
✔ Strong typing & structure
'''

class ConnectionManager:
    """
    Manages active WebSocket connections and per-client state.
    """

    def __init__(self):
        # A dict: client_id -> WebSocket
        self.connections: Dict[str, WebSocket] = {}

        # Optional per-client state (chat handlers, sessions, etc.)
        self.client_state: Dict[str, Dict[str, Any]] = {}

    # -------------------------------------------------------------------------
    # CONNECTION LIFECYCLE
    # -------------------------------------------------------------------------
    async def connect(self, websocket: WebSocket, user_id: str = "unknown") -> str:
        """
        Accepts WebSocket and registers a new client ID.
        """
        await websocket.accept()

        client_id = str(uuid.uuid4())
        self.connections[client_id] = websocket

        # Set initial state
        self.client_state[client_id] = {
            "user_id": user_id,
            "handlers": {}  # optional: store per-index chat handlers etc.
        }

        return client_id

    # -------------------------------------------------------------------------
    def disconnect(self, client_id: str):
        """
        Remove client and its state.
        """
        if client_id in self.connections:
            del self.connections[client_id]

        if client_id in self.client_state:
            del self.client_state[client_id]

    # -------------------------------------------------------------------------
    def get_websocket(self, client_id: str) -> Optional[WebSocket]:
        """
        Retrieve WebSocket for a client.
        """
        return self.connections.get(client_id)

    # -------------------------------------------------------------------------
    def get_client_state(self, client_id: str) -> Dict[str, Any]:
        """
        Get metadata or session state for a client.
        """
        return self.client_state.get(client_id, {})

    # -------------------------------------------------------------------------
    async def send_to_client(self, client_id: str, message: Any):
        """
        Send message to a single client.
        """
        ws = self.connections.get(client_id)
        if not ws:
            return

        try:
            if isinstance(message, dict):
                await ws.send_json(message)
            else:
                await ws.send_text(str(message))
        except WebSocketDisconnect:
            self.disconnect(client_id)

    # -------------------------------------------------------------------------
    async def broadcast(self, message: Any, exclude: Optional[str] = None):
        """
        Send message to all connected clients except `exclude`.
        """
        dead_clients = []

        for client_id, ws in self.connections.items():
            if client_id == exclude:
                continue

            try:
                if isinstance(message, dict):
                    await ws.send_json(message)
                else:
                    await ws.send_text(str(message))
            except WebSocketDisconnect:
                dead_clients.append(client_id)

        # Cleanup dead websockets
        for client_id in dead_clients:
            self.disconnect(client_id)

    # -------------------------------------------------------------------------
    # OPTIONAL: SUPPORT FOR PER-INDEX CHAT HANDLERS
    # -------------------------------------------------------------------------
    def set_handler(self, client_id: str, index_name: str, handler):
        """
        Store chat handler for a given client and index.
        """
        if client_id in self.client_state:
            self.client_state[client_id]["handlers"][index_name] = handler

    def get_handler(self, client_id: str, index_name: str):
        """
        Retrieve chat handler for a given client and index.
        """
        return (
            self.client_state.get(client_id, {})
            .get("handlers", {})
            .get(index_name)
        )


    # If you want chat handlers to auto-create
    # def get_or_create_handler(self, client_id, index_name, factory_fn):
    #     handler = self.get_handler(client_id, index_name)
    #     if handler:
    #         return handler

    #     handler = factory_fn(index_name=index_name)
    #     self.set_handler(client_id, index_name, handler)
    #     return handler