from datetime import datetime
from typing import Optional

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.connection_manager import ConnectionManager
from app.engine.emitter import EventEmitter
from app.engine.message_router import (
    dispatch_message,
    dispatch_rest,
    register_handler_openapi_routes,
)
from app.engine.schemas import BaseRequest


@asynccontextmanager
async def lifespan(app: FastAPI):
    print("🚀 Starting AI Governance Backend...")

    app.state.start_time = datetime.utcnow()
    app.state.cache = {}

    yield

    print("🛑 Shutting down AI Governance Backend...")


app = FastAPI(
    lifespan=lifespan,
    openapi_tags=[
        {
            "name": "handlers",
            "description": "One POST per registered WebSocket `(reqType, reqSubType)`. JSON body = former `reqData`.",
        },
    ],
)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content=jsonable_encoder({
            "detail": exc.errors(),
            "body": exc.body,
        }),
    )


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


@app.post("/api/dispatch")
async def api_dispatch(body: BaseRequest):
    """
    HTTP bridge: same ``reqType`` / ``reqSubType`` / ``reqData`` as the WebSocket JSON body.
    """
    return await dispatch_rest(body)


register_handler_openapi_routes(app)


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket, user_id: Optional[str] = None):
    """
    Central WebSocket entrypoint; all logic goes through ``dispatch_message``.
    """
    client_id = await manager.connect(websocket, user_id)

    emitter = EventEmitter(websocket=websocket)
    await emitter.info("🔌Connected", payload={"client_id": client_id})

    try:
        while True:
            try:
                raw = await websocket.receive_text()
                req = BaseRequest.model_validate_json(raw)

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
                    "message": str(e),
                })

    except Exception as e:
        print(f"WebSocket error: {e}")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8080,
        reload=True,
    )
