from typing import Any, Dict, Optional

from pydantic import BaseModel


class BaseRequest(BaseModel):
    reqType: str
    reqSubType: str
    reqData: Optional[Dict[str, Any]] = {}
