# models/auditor.py

from pydantic import BaseModel
from typing import List


class AuditorModel(BaseModel):
    auditor_id: str
    name: str
    email: str
    region: str

    organizations: List[str]
    enrolled: str