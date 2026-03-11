from datetime import datetime
from pprint import pprint
from typing import Dict, List, Tuple, Set, Annotated, Union, Optional
import json
import os

from fastapi import (
    FastAPI,
    HTTPException,
    Body,
    Path,
    Request,
    status,
    Query,
    WebSocket, 
    WebSocketDisconnect
)

import asyncio
import json
import logging
import os
import signal
from contextlib import asynccontextmanager
from typing import Dict, List, Literal, Optional, Tuple

from fastapi.staticfiles import StaticFiles
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse, HTMLResponse
from fastapi.middleware.wsgi import WSGIMiddleware

# 🔥 NEW
from contextlib import asynccontextmanager

from app.config import get_config
from app.connection_manager import ConnectionManager
from app.engine.emitter import EventEmitter
from app.engine.message_router import auto_load_handlers, dispatch_message
from app.engine.schemas import BaseRequest

# =========================================================
# 🔥 LIFESPAN (Modern replacement for startup/shutdown)
# =========================================================
@asynccontextmanager
async def lifespan(app: FastAPI):
    print("🚀 Starting AI Governance Backend...")

    # 🔥 Example: initialize shared resources
    app.state.start_time = datetime.utcnow()
    app.state.cache = {}  # placeholder (can be Redis later)
    
    # Example: Load configs / models / rules
    # app.state.intent_engine = load_intent_model()
    # app.state.policy_engine = init_policy_engine()

    auto_load_handlers()   # 🔥 THIS IS REQUIRED

    yield

    print("🛑 Shutting down AI Governance Backend...")

    # 🔥 Cleanup (if needed)
    # await app.state.db.close()
    # await app.state.llm_client.close()


# =========================================================
# 🔥 APP INIT (WITH LIFESPAN)
# =========================================================
app = FastAPI(lifespan=lifespan)


# =========================================================
# 🔥 VALIDATION HANDLER
# =========================================================
@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content=jsonable_encoder({
            "detail": exc.errors(),
            "body": exc.body
        }),
    )


# =========================================================
# 🔥 OPTIONAL DASH MOUNT
# =========================================================
# from .dash_app import app as db1
# app.mount("/dash", WSGIMiddleware(db1.server))


# =========================================================
# 🔥 CORS
# =========================================================
origins = [
    "http://localhost",
    "http://localhost:8080",
    "http://localhost:3000",
    "http://10.49.55.139:90",
    "http://10.49.55.139",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


manager = ConnectionManager()

# =========================================================
# 🔥 ROUTES
# =========================================================
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket, user_id: Optional[str] = None):
    """
    Central WebSocket entrypoint.
    All logic is routed through dispatch_message()
    No direct business logic here.
    """

    client_id = await manager.connect(websocket, user_id)

    
    # Emit the message to both Console and WebSocket
    emitter = EventEmitter(websocket=websocket)
    await emitter.info("🔌Connected", payload={"client_id": client_id} )


    try:
        while True:
            try:
                raw = await websocket.receive_text()
                req = BaseRequest.parse_raw(raw)

                # response = {"a" : 100}
                
                # print(f"********-------------{raw} / {req}")      
                response = await dispatch_message(
                    websocket=websocket,
                    client_id=client_id,
                    request=req,
                    manager=manager, 
                ) 
                

                if response is not None:
                    await websocket.send_json(response)

            except WebSocketDisconnect:
                manager.disconnect(client_id)
                break

            except Exception as e:
                await websocket.send_json({
                    "status": "error",
                    "message": str(e)
                })

    except Exception as e:
        print(f"WebSocket error: {e}")