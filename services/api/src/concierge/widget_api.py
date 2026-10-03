"""Public widget endpoints (visitor side, no login).

Security model:
* The public agent id is not a secret; the *Origin* of the page must match a verified domain
  of the agent's tenant, and the browser (not the visitor) sets that header.
* A short-lived signed session token binds the conversation, tenant, agent and origin.
* The visitor path touches the database only through ``public_resolve_agent`` and then under
  the resolved tenant's row-level security.
"""

import json
from datetime import timedelta
from typing import Annotated, Any

import jwt
from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    Header,
    HTTPException,
    Request,
    Response,
    status,
)
from pydantic import BaseModel, EmailStr, Field, field_validator
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from .config import Settings, get_settings
from .db import SessionLocal, bind_context, get_db
from .mailer import get_mailer
from .models import Conversation, Lead, Message, MessageSource, Tenant, utcnow
from .origins import origin_allowed, parse_origin
from .outbox import enqueue_email, process_outbox
from .ratelimit import RateLimiter
from .responder import Responder, SourceRef, get_responder

router = APIRouter(prefix="/api/v1/public/widget", tags=["widget"])

AI_NOTICE = (
    "You are chatting with an AI assistant, not a person. Your messages are processed to answer "
    "your enquiry and may be stored by the business you are contacting."
)
_session_limiter = RateLimiter(limit=20)
_message_limiter = RateLimiter(limit=30)
_lead_limiter = RateLimiter(limit=5, window_seconds=3600)


def reset_limiters(settings: Settings | None = None) -> None:
    _session_limiter.reset()
    _message_limiter.reset()
    _lead_limiter.reset()
    if settings:
        _message_limiter.limit = settings.widget_rate_per_minute


class SessionRequest(BaseModel):
    agent_id: str = Field(min_length=4, max_length=64)


class SessionResponse(BaseModel):
    session_id: str
    token: str
    expires_in: int
    agent_name: str
    business_name: str
    notice: str
    consent_text: str
    privacy_url: str | None


class EventRequest(BaseModel):
    type: str = Field(pattern="^message$")
    text: str = Field(min_length=1, max_length=1000)


class SourceOut(BaseModel):
    title: str
    url: str


class EventResponse(BaseModel):
    reply: str
    sources: list[SourceOut] = []
    offer_lead_form: bool = False


def consent_text(business: str) -> str:
    return (
        f"I agree that {business} may use these details to contact me about my enquiry. "
        "They are sent to the team by email."
    )


def normalise_phone(raw: str) -> str:
    """Accept UK and international numbers; return +digits. Raises ValueError if implausible."""
    cleaned = "".join(ch for ch in raw if ch.isdigit() or ch == "+")
    if cleaned.startswith("00"):
        cleaned = "+" + cleaned[2:]
    elif cleaned.startswith("0") and len(cleaned) == 11:  # UK national format
        cleaned = "+44" + cleaned[1:]
    elif not cleaned.startswith("+") and len(cleaned) >= 10:
        cleaned = "+" + cleaned
    digits = cleaned.removeprefix("+")
    if cleaned.count("+") > 1 or not digits.isdigit() or not 8 <= len(digits) <= 15:
        raise ValueError("Enter a valid phone number, for example 07700 900123 or +44 7700 900123")
    return "+" + digits


class LeadRequest(BaseModel):
    name: str = Field(min_length=2, max_length=100)
    phone: str = Field(min_length=6, max_length=32)
    email: EmailStr
    consent: bool
    website: str | None = Field(default=None, max_length=200)  # honeypot: humans leave it empty

    @field_validator("name")
    @classmethod
    def clean_name(cls, value: str) -> str:
        value = " ".join(value.split())
        if len(value) < 2 or any(ch in value for ch in "<>") or not any(c.isalpha() for c in value):
            raise ValueError("Enter your name")
        return value

    @field_validator("phone")
    @classmethod
    def clean_phone(cls, value: str) -> str:
        return normalise_phone(value)

    @field_validator("consent")
    @classmethod
    def must_consent(cls, value: bool) -> bool:
        if not value:
            raise ValueError("Please tick the box so we can contact you")
        return value


class LeadResponse(BaseModel):
    status: str


def client_key(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def cors_headers(origin: str | None, allowed: bool) -> dict[str, str]:
    headers = {"Vary": "Origin"}
    if allowed and origin:
        headers["Access-Control-Allow-Origin"] = origin
    return headers


@router.options("/{rest:path}")
def preflight(request: Request) -> Response:
    # Preflight carries no agent, so it cannot be judged here; the real request is checked.
    origin = request.headers.get("origin")
    return Response(
        status_code=204,
        headers={
            "Access-Control-Allow-Origin": origin or "*",
            "Access-Control-Allow-Methods": "POST, OPTIONS",
            "Access-Control-Allow-Headers": "content-type, authorization",
            "Access-Control-Max-Age": "600",
            "Vary": "Origin",
        },
    )


def _is_production(settings: Settings) -> bool:
    return settings.app_env in {"staging", "production"}


@router.post("/session", response_model=SessionResponse, status_code=201)
def start_session(
    payload: SessionRequest,
    request: Request,
    response: Response,
    db: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
    origin: Annotated[str | None, Header()] = None,
) -> SessionResponse:
    if not _session_limiter.allow(client_key(request)):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Too many requests")
    raw = db.scalar(text("SELECT public_resolve_agent(:p)"), {"p": payload.agent_id})
    agent: dict[str, Any] | None = (
        raw if isinstance(raw, dict) else (json.loads(raw) if raw else None)
    )
    # Same answer for unknown, unpublished and disallowed so agents cannot be enumerated.
    if agent is None or not origin_allowed(
        origin, agent["hostnames"], production=_is_production(settings)
    ):
        # The refusal is deliberately generic, so it is safe to let the page read it; without this
        # header the browser hides the 403 and the widget could only show "unavailable".
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "This website is not approved for this agent",
            headers=cors_headers(origin, parse_origin(origin) is not None),
        )
    assert origin is not None  # noqa: S101 - guaranteed by origin_allowed
    parsed = parse_origin(origin)
    assert parsed is not None  # noqa: S101
    origin_value = f"{parsed[0]}://{parsed[1]}"

    bind_context(db, tenant_id=agent["tenant_id"])
    tenant = db.get(Tenant, agent["tenant_id"])
    business = tenant.name if tenant else agent["name"]
    conversation = Conversation(
        tenant_id=agent["tenant_id"], agent_id=agent["agent_id"], origin=origin_value[:255]
    )
    db.add(conversation)
    db.flush()
    expires = timedelta(minutes=settings.widget_session_minutes)
    token = jwt.encode(
        {
            "sid": conversation.id,
            "tid": agent["tenant_id"],
            "aid": agent["agent_id"],
            "name": agent["name"],
            "biz": business,
            "origin": origin_value,
            "exp": utcnow() + expires,
            "iat": utcnow(),
        },
        settings.widget_signing_key,
        algorithm="HS256",
    )
    db.commit()
    for key, value in cors_headers(origin, True).items():
        response.headers[key] = value
    return SessionResponse(
        session_id=conversation.id,
        token=token,
        expires_in=int(expires.total_seconds()),
        agent_name=agent["name"],
        business_name=business,
        notice=AI_NOTICE,
        consent_text=consent_text(business),
        privacy_url=settings.privacy_url,
    )


def _claims(
    session_id: str, authorization: str | None, origin: str | None, settings: Settings
) -> dict[str, Any]:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing session token")
    try:
        claims: dict[str, Any] = jwt.decode(
            authorization[7:].strip(),
            settings.widget_signing_key,
            algorithms=["HS256"],
            options={"require": ["exp", "sid", "tid", "origin"]},
        )
    except jwt.PyJWTError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Session expired or invalid") from exc
    if claims["sid"] != session_id:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Session mismatch")
    if origin is not None and origin != claims["origin"]:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Origin mismatch")
    return claims


@router.post("/session/{session_id}/events", response_model=EventResponse)
def send_event(
    session_id: str,
    payload: EventRequest,
    response: Response,
    db: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
    responder: Annotated[Responder, Depends(get_responder)],
    authorization: Annotated[str | None, Header()] = None,
    origin: Annotated[str | None, Header()] = None,
) -> EventResponse:
    claims = _claims(session_id, authorization, origin, settings)
    if not _message_limiter.allow(session_id):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Too many messages")
    bind_context(db, tenant_id=claims["tid"])
    conversation = db.scalar(select(Conversation).where(Conversation.id == session_id))
    if conversation is None or conversation.status != "active":
        raise HTTPException(status.HTTP_409_CONFLICT, "Conversation has ended")
    answer = responder.reply(
        db=db,
        tenant_id=claims["tid"],
        conversation_id=session_id,
        agent_name=claims.get("name", "Assistant"),
        business_name=claims.get("biz", "the business"),
        visitor_text=payload.text,
    )
    db.add(
        Message(
            tenant_id=claims["tid"],
            conversation_id=session_id,
            role="visitor",
            content=payload.text,
        )
    )
    agent_message = Message(
        tenant_id=claims["tid"], conversation_id=session_id, role="agent", content=answer.text
    )
    db.add(agent_message)
    db.flush()
    for rank, chunk in enumerate(answer.chunks, start=1):
        db.add(
            MessageSource(
                tenant_id=claims["tid"], message_id=agent_message.id, chunk_id=chunk.chunk_id,
                document_url=chunk.url, document_title=chunk.title[:500], rank=rank,
                score=chunk.score,
            )
        )  # fmt: skip
    db.commit()
    for key, value in cors_headers(origin, True).items():
        response.headers[key] = value
    refs: list[SourceRef] = answer.sources
    return EventResponse(
        reply=answer.text,
        sources=[SourceOut(title=r.title, url=r.url) for r in refs],
        offer_lead_form=answer.offer_lead_form,
    )


@router.post("/session/{session_id}/end", status_code=204)
def end_session(
    session_id: str,
    response: Response,
    db: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
    authorization: Annotated[str | None, Header()] = None,
    origin: Annotated[str | None, Header()] = None,
) -> None:
    claims = _claims(session_id, authorization, origin, settings)
    bind_context(db, tenant_id=claims["tid"])
    conversation = db.scalar(select(Conversation).where(Conversation.id == session_id))
    if conversation is not None and conversation.status == "active":
        conversation.status = "ended"
        conversation.ended_at = utcnow()
        db.commit()
    for key, value in cors_headers(origin, True).items():
        response.headers[key] = value


def _transcript(db: Session, conversation_id: str, limit: int = 12) -> str:
    rows = db.execute(
        select(Message.role, Message.content)
        .where(Message.conversation_id == conversation_id)
        .order_by(Message.created_at.desc())
        .limit(limit)
    ).all()
    lines = [
        f"{'Visitor' if r.role == 'visitor' else 'Assistant'}: {' '.join(r.content.split())[:300]}"
        for r in reversed(rows)
    ]
    return "\n".join(lines) or "(no messages)"


def _lead_email(lead: Lead, business: str, transcript: str) -> tuple[str, str]:
    safe_name = "".join(ch for ch in lead.name if ch.isprintable())[:60]
    subject = f"New website enquiry: {safe_name}"
    body = (
        f"A visitor asked to be contacted through the {business} website assistant.\n\n"
        f"Name:  {lead.name}\n"
        f"Phone: {lead.phone}\n"
        f"Email: {lead.email}\n"
        f"Page:  {lead.origin}\n"
        f"Time:  {lead.created_at:%Y-%m-%d %H:%M} UTC\n\n"
        "Consent given at submission:\n"
        f'  "{lead.consent_text}"\n\n'
        "Recent conversation:\n"
        f"{transcript}\n\n"
        "Reply to this email to reach the visitor directly."
    )
    return subject, body


@router.post("/session/{session_id}/lead", response_model=LeadResponse, status_code=201)
def submit_lead(
    session_id: str,
    payload: LeadRequest,
    request: Request,
    response: Response,
    background: BackgroundTasks,
    db: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
    authorization: Annotated[str | None, Header()] = None,
    origin: Annotated[str | None, Header()] = None,
) -> LeadResponse:
    claims = _claims(session_id, authorization, origin, settings)
    for key, value in cors_headers(origin, True).items():
        response.headers[key] = value
    if payload.website:  # honeypot tripped: pretend success, store and send nothing
        return LeadResponse(status="received")
    if not _lead_limiter.allow(client_key(request)):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Too many requests")
    bind_context(db, tenant_id=claims["tid"])
    conversation = db.scalar(select(Conversation).where(Conversation.id == session_id))
    if conversation is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Conversation not found")
    if db.scalar(select(Lead.id).where(Lead.conversation_id == session_id)):
        return LeadResponse(status="already_received")
    business = claims.get("biz", "the business")
    lead = Lead(
        tenant_id=claims["tid"], conversation_id=session_id, name=payload.name,
        phone=payload.phone, email=str(payload.email).lower(), consent_at=utcnow(),
        consent_text=consent_text(business), origin=claims["origin"][:255],
    )  # fmt: skip
    db.add(lead)
    db.flush()
    tenant = db.get(Tenant, claims["tid"])
    if tenant is not None and tenant.notify_email:
        subject, body = _lead_email(lead, business, _transcript(db, session_id))
        enqueue_email(
            db, tenant_id=claims["tid"], to=tenant.notify_email, subject=subject, body=body,
            key=f"lead:{lead.id}", reply_to=lead.email,
        )  # fmt: skip
        background.add_task(process_outbox, SessionLocal, get_mailer(settings))
    db.commit()
    return LeadResponse(status="received")
