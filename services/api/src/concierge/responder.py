"""Conversation responder: retrieve website evidence, then answer with Claude or, when no model is
available or the daily cap is reached, with a clearly extractive answer from the best page."""

import logging
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Protocol

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .config import get_settings
from .knowledge import Retrieved, retrieve
from .llm import AnthropicLlm, LlmClient, LlmError
from .models import Message
from .prompt import MAX_HISTORY, build_messages, build_system

log = logging.getLogger("concierge.responder")

LEAD_WORDS = (
    "call me", "call back", "callback", "contact me", "get in touch", "speak to", "talk to",
    "someone", "human", "quote", "pricing", "price", "cost", "demo", "book", "appointment",
    "meeting", "consultation", "interested", "enquiry", "enquire", "hire", "engage", "proposal",
)  # fmt: skip
GREETING = re.compile(
    r"^\s*(hi|hello|hey|good (morning|afternoon|evening)|thanks|thank you)\b[\s!.?]*$", re.I
)
NO_INFO = (
    "I couldn't find that on the website, and I don't want to guess. "
    "If you'd like, use “Request a call back” and the team will get in touch."
)


@dataclass
class SourceRef:
    title: str
    url: str


@dataclass
class Answer:
    text: str
    sources: list[SourceRef] = field(default_factory=list)
    offer_lead_form: bool = False
    chunks: list[Retrieved] = field(default_factory=list)
    used_llm: bool = False


class Responder(Protocol):
    def reply(
        self,
        *,
        db: Session,
        tenant_id: str,
        conversation_id: str,
        agent_name: str,
        business_name: str,
        visitor_text: str,
    ) -> Answer: ...


def wants_contact(text: str) -> bool:
    lowered = text.lower()
    return any(word in lowered for word in LEAD_WORDS)


def dedupe_sources(chunks: list[Retrieved], limit: int = 3) -> list[SourceRef]:
    seen: dict[str, SourceRef] = {}
    for chunk in chunks:
        seen.setdefault(chunk.url, SourceRef(chunk.title, chunk.url))
    return list(seen.values())[:limit]


def extractive_answer(chunks: list[Retrieved]) -> str:
    body = chunks[0].text.split("\n", 1)[-1].strip()
    if len(body) > 600:
        body = body[:600].rsplit(" ", 1)[0] + "…"
    return f"Here's what the website says:\n\n{body}"


class RagResponder:
    def __init__(self, llm: LlmClient | None, daily_cap: int) -> None:
        self._llm = llm
        self._cap = daily_cap

    def _under_cap(self, db: Session, tenant_id: str) -> bool:
        start = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
        count = db.scalar(
            select(func.count())
            .select_from(Message)
            .where(
                Message.tenant_id == tenant_id, Message.role == "agent", Message.created_at >= start
            )
        )
        return (count or 0) < self._cap

    def reply(
        self,
        *,
        db: Session,
        tenant_id: str,
        conversation_id: str,
        agent_name: str,
        business_name: str,
        visitor_text: str,
    ) -> Answer:
        offer = wants_contact(visitor_text)
        if GREETING.match(visitor_text):
            return Answer(
                f"Hello! I'm {agent_name}, an AI assistant for {business_name}. "
                "Ask me anything about what the company does.",
                offer_lead_form=False,
            )
        history_rows = db.execute(
            select(Message.role, Message.content)
            .where(Message.conversation_id == conversation_id)
            .order_by(Message.created_at.desc())
            .limit(MAX_HISTORY)
        ).all()
        history = [(r.role, r.content) for r in reversed(history_rows)]
        query = visitor_text
        if (
            len(visitor_text.split()) < 4
        ):  # short follow-up: borrow context from the previous question
            previous = [c for r, c in history if r == "visitor"]
            if previous:
                query = f"{previous[-1]} {visitor_text}"
        chunks = retrieve(db, tenant_id, query)
        if not chunks:
            return Answer(NO_INFO, offer_lead_form=True)
        sources = dedupe_sources(chunks)
        if self._llm is not None and self._under_cap(db, tenant_id):
            try:
                text = self._llm.complete(
                    system=build_system(agent_name, business_name),
                    messages=build_messages(history, visitor_text, chunks),
                    max_tokens=400,
                )
                return Answer(text, sources, offer, chunks, used_llm=True)
            except LlmError as exc:
                log.warning("LLM unavailable (%s); using extractive answer", exc)
        return Answer(extractive_answer(chunks), sources, offer, chunks)


def get_responder() -> Responder:
    settings = get_settings()
    llm = (
        AnthropicLlm(settings.anthropic_api_key, settings.llm_model)
        if settings.anthropic_api_key
        else None
    )
    return RagResponder(llm, settings.daily_ai_message_cap)
