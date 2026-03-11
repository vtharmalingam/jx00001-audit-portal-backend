# models/answer.py

from pydantic import BaseModel, Field
from typing import Optional, Literal


class AnswerModel(BaseModel):
    question_id: str
    answer: str

    state: Literal["draft", "submitted", "locked"]
    version: int = Field(ge=1)

    last_updated_at: str
    last_updated_by: str