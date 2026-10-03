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
from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from .config import Settings, get_settings
from .db import bind_context, get_db
from .models import Conversation, Message, utcnow
from .origins import origin_allowed, parse_origin
from .ratelimit import RateLimiter
from .responder import Responder, get_responder

router = APIRouter(prefix="/api/v1/public/widget", tags=["widget"])

AI_NOTICE = (
    "You are chatting with an AI assistant, not a person. Your messages are processed to answer "
    "your enquiry and may be stored by the business you are contacting."
)
_session_limiter = RateLimiter(limit=20)
_message_limiter = RateLimiter(limit=30)


def reset_limiters(settings: Settings | None = None) -> None:
    _session_limiter.reset()
    _message_limiter.reset()
    if settings:
        _message_limiter.limit = settings.widget_rate_per_minute


class SessionRequest(BaseModel):
    agent_id: str = Field(min_length=4, max_length=64)


class SessionResponse(BaseModel):
    session_id: str
    token: str
    expires_in: int
    agent_name: str
    notice: str


class EventRequest(BaseModel):
    type: str = Field(pattern="^message$")
    text: str = Field(min_length=1, max_length=1000)


class EventResponse(BaseModel):
    reply: str


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
        notice=AI_NOTICE,
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
    reply = responder.reply(agent_name=claims.get("name", "Assistant"), visitor_text=payload.text)
    db.add(
        Message(
            tenant_id=claims["tid"],
            conversation_id=session_id,
            role="visitor",
            content=payload.text,
        )
    )
    db.add(
        Message(tenant_id=claims["tid"], conversation_id=session_id, role="agent", content=reply)
    )
    db.commit()
    for key, value in cors_headers(origin, True).items():
        response.headers[key] = value
    return EventResponse(reply=reply)


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
