import json
import logging
from typing import Literal

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import User
from ..rag import MAX_HISTORY_TURNS, NO_ACCESS, SYSTEM, answer_question, cited_numbers, prepare
from ..ratelimit import limit_chat
from ..services import Services, get_services

router = APIRouter(tags=["chat"])
log = logging.getLogger(__name__)


class Turn(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(max_length=4000)


class ChatIn(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    # Prior turns, kept by the client. Only used to resolve follow-ups; retrieval
    # is still ACL-filtered for the signed-in user regardless of what is in here.
    history: list[Turn] = Field(default_factory=list, max_length=20)


def _history(body: ChatIn) -> list[dict]:
    return [t.model_dump() for t in body.history[-MAX_HISTORY_TURNS:]]


@router.post("/chat")
def chat(
    body: ChatIn,
    db: Session = Depends(get_db),
    user: User = Depends(limit_chat),
    svc: Services = Depends(get_services),
):
    return answer_question(db, svc, user, body.question.strip(), _history(body))


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


@router.post("/chat/stream")
def chat_stream(
    body: ChatIn,
    db: Session = Depends(get_db),
    user: User = Depends(limit_chat),
    svc: Services = Depends(get_services),
):
    """Server-sent events: `meta` (sources, sent before any text), many `token`s, then `done`
    (which source numbers the answer actually cited) or `error`."""
    p = prepare(db, svc, user, body.question.strip(), _history(body))  # all DB work finishes here

    def events():
        yield _sse("meta", {"search_query": p.search_query, "citations": [{**d, "cited": False} for d in p.docs]})
        if p.prompt is None:
            yield _sse("token", {"text": NO_ACCESS})
            yield _sse("done", {"cited": []})
            return
        parts: list[str] = []
        try:
            for piece in svc.llm.generate_stream(SYSTEM, p.prompt):
                parts.append(piece)
                yield _sse("token", {"text": piece})
        except Exception:
            log.exception("answer stream failed")
            yield _sse("error", {"message": "The answer service is busy or unavailable. Please try again."})
            return
        yield _sse("done", {"cited": sorted(cited_numbers("".join(parts)))})

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"},
    )
