from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import User
from ..rag import MAX_HISTORY_TURNS, answer_question
from ..security import current_user
from ..services import Services, get_services

router = APIRouter(tags=["chat"])


class Turn(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(max_length=4000)


class ChatIn(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    # Prior turns, kept by the client. Only used to resolve follow-ups; retrieval
    # is still ACL-filtered for the signed-in user regardless of what is in here.
    history: list[Turn] = Field(default_factory=list, max_length=20)


@router.post("/chat")
def chat(
    body: ChatIn,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
    svc: Services = Depends(get_services),
):
    history = [t.model_dump() for t in body.history[-MAX_HISTORY_TURNS:]]
    return answer_question(db, svc, user, body.question.strip(), history)
