# cognitract/emitter.py
import json
import logging
from typing import Any, Dict, Optional

logger = logging.getLogger("chat_server")

class EventEmitter:
    def __init__(self, websocket=None, console: bool = True):
        """
        websocket: WebSocket or None
        console: emit to console/logs
        """
        self.websocket = websocket
        self.console = console

    async def emit(
        self,
        message: str,
        *,
        level: str = "info",
        event: Optional[str] = None,
        payload: Optional[Dict[str, Any]] = None,
    ):
        data = {
            "level": level,
            "event": event,
            "message": message,
            "payload": payload,
        }

        # Console / logs
        if self.console:
            log_fn = getattr(logger, level, logger.info)
            log_fn(message)

        # WebSocket
        if self.websocket:
            await self.websocket.send_json(data)

    # Convenience helpers
    async def info(self, message: str, **kwargs):
        await self.emit(message, level="info", **kwargs)

    async def warn(self, message: str, **kwargs):
        await self.emit(message, level="warning", **kwargs)

    async def error(self, message: str, **kwargs):
        await self.emit(message, level="error", **kwargs)
