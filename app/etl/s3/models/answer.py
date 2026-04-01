# models/answer.py

from typing import List, Literal, Optional

from pydantic import BaseModel, Field


class AttachmentRef(BaseModel):
    file_name: str
    s3_key: str
    uploaded_at: str


class AnswerModel(BaseModel):
    question_id: str
    answer: str

    state: Literal["draft", "submitted", "locked"]
    version: int = Field(ge=1)

    attachments: List[AttachmentRef] = Field(default_factory=list)

    last_updated_at: str
    last_updated_by: str