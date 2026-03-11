'''
No need to manually update imports
Automatically loads every handler module
Ensures decorators always register

'''

import importlib
import pkgutil
from typing import Optional

ROUTES = {}

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
