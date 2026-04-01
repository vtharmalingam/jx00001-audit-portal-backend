'''
No need to manually update imports
Automatically loads every handler module
Ensures decorators always register

'''

import importlib
import pkgutil
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from pydantic import BaseModel

from app.connection_manager import ConnectionManager
from app.engine.schemas import BaseRequest, ROUTE_OPENAPI_BODIES

if TYPE_CHECKING:
    from fastapi import FastAPI

ROUTES = {}


class CollectingWebSocket:
    """Stand-in WebSocket that records ``send_json`` payloads from ``EventEmitter``."""

    __slots__ = ("messages",)

    def __init__(self) -> None:
        self.messages: List[Dict[str, Any]] = []

    async def send_json(self, data: Dict[str, Any]) -> None:
        self.messages.append(data)

def route(req_type, req_subtype):
    """Decorator used by handler functions to register routes."""
    def wrapper(func):
        ROUTES[(req_type, req_subtype)] = func
        return func
    return wrapper


def auto_load_handlers():
    """
    Dynamically loads ALL modules under supportwiz.handlers.*
    so that decorator registration occurs automatically.
    """
    package_name = "app.handlers"

    package = importlib.import_module(package_name)

    for _, module_name, _ in pkgutil.iter_modules(package.__path__):
        full_module = f"{package_name}.{module_name}"
        importlib.import_module(full_module)


    print(f"[DEBUG]------------- Handler Routes: {ROUTES}")


# request: will have request.reqType, request.reqSubType, request.reqData (Optional)
async def dispatch_message(websocket, client_id, 
                           request, 
                           manager, 
                          #  llm_client,
                          #  mcp_client,
                          #  chat_store,
                          #  support_client: Optional[SupportDataClient] = None
                           ):
            
    key = (request.reqType, request.reqSubType)
    handler = ROUTES.get(key)

    print(f"-------------{key}// {handler}")

    if handler is None:
        return {
            "status": "error",
            "message": f"Unknown route: {key}"
        }

    return await handler(websocket, client_id, request, manager, 
      # llm_client, mcp_client, chat_store, support_client
      )


async def dispatch_rest(request: BaseRequest) -> Dict[str, Any]:
    """
    Run the same handler as the WebSocket path, but collect ``emitter`` JSON events
    instead of pushing them to a live socket. Handlers that only emit (typical) populate
    ``emitted``; router-level errors and rare explicit returns show up in ``returned``.
    """
    collecting = CollectingWebSocket()
    manager = ConnectionManager()
    returned = await dispatch_message(
        collecting,
        "rest",
        request,
        manager,
    )
    return {"returned": returned, "emitted": collecting.messages}


def _slug_route_segment(label: str) -> str:
    return label.strip().lower().replace("_", "-")


def register_handler_openapi_routes(app: "FastAPI") -> None:
    """Register one POST per ``ROUTES`` entry; bodies from ``ROUTE_OPENAPI_BODIES``."""
    auto_load_handlers()

    def _make_typed_endpoint(
        req_type: str, req_subtype: str, BodyModel: type[BaseModel]
    ):
        async def _endpoint(body: BodyModel):
            request = BaseRequest(
                reqType=req_type,
                reqSubType=req_subtype,
                reqData=body.model_dump(mode="json", exclude_none=True),
            )
            return await dispatch_rest(request)

        _endpoint.__name__ = (
            f"rpc_{_slug_route_segment(req_type)}_{_slug_route_segment(req_subtype)}"
        )
        _endpoint.__doc__ = (
            f"HTTP alias for WebSocket RPC: `reqType={req_type!r}`, "
            f"`reqSubType={req_subtype!r}`."
        )
        return _endpoint

    for req_type, req_subtype in list(ROUTES.keys()):
        path = (
            f"/api/handlers/{_slug_route_segment(req_type)}"
            f"/{_slug_route_segment(req_subtype)}"
        )
        body_model = ROUTE_OPENAPI_BODIES.get((req_type, req_subtype))
        if body_model is None:
            raise KeyError(
                "Add `(reqType, reqSubType)` to `ROUTE_OPENAPI_BODIES` in "
                f"app/engine/schemas.py: missing {(req_type, req_subtype)!r}"
            )
        route_handler = _make_typed_endpoint(req_type, req_subtype, body_model)
        route_description = (
            f"Same handler as WebSocket when `reqType` is `{req_type}` and "
            f"`reqSubType` is `{req_subtype}`. JSON body = former `reqData` "
            "(see schema for required fields)."
        )
        app.add_api_route(
            path,
            route_handler,
            methods=["POST"],
            tags=["handlers", req_type],
            summary=req_subtype,
            description=route_description,
        )
