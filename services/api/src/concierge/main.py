import logging
import time
import uuid
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Query, Request, status
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from . import domains, organisations, widget_api
from .audit import record_audit
from .auth import Principal, PrincipalDep, require_roles
from .config import get_settings
from .db import get_db
from .logging_config import configure_logging
from .models import Agent, Role, utcnow
from .problems import install_problem_handlers
from .schemas import AgentCreate, AgentPage, AgentRead, MeRead
from .tenancy import TenantDbDep

configure_logging(get_settings().log_level)
access_log = logging.getLogger("concierge.access")

app = FastAPI(
    title="VoiceUP AI Sales Concierge API",
    version="0.2.0",
    docs_url="/docs",
    openapi_url="/api/v1/openapi.json",
)
install_problem_handlers(app)
app.include_router(organisations.router)
app.include_router(domains.router)
app.include_router(widget_api.router)

DbDep = Annotated[Session, Depends(get_db)]
AdminPrincipal = Annotated[
    Principal,
    Depends(require_roles(Role.platform_admin, Role.customer_admin)),
]


@app.middleware("http")
async def request_context_middleware(request: Request, call_next):  # type: ignore[no-untyped-def]
    request_id = request.headers.get("X-Request-Id") or str(uuid.uuid4())
    request.state.request_id = request_id
    started = time.perf_counter()
    response = await call_next(request)
    response.headers["X-Request-Id"] = request_id
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    access_log.info(
        "request",
        extra={
            "request_id": request_id,
            "method": request.method,
            "path": request.url.path,
            "status": response.status_code,
            "duration_ms": round((time.perf_counter() - started) * 1000, 1),
        },
    )
    return response


@app.get("/health/live", tags=["health"])
def live() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/health/ready", tags=["health"])
def ready(db: DbDep) -> dict[str, str]:
    db.execute(text("SELECT 1"))
    return {"status": "ready"}


@app.get("/api/v1/me", response_model=MeRead, tags=["identity"])
def me(principal: PrincipalDep) -> MeRead:
    return MeRead(
        user_id=principal.user_id, tenant_id=principal.tenant_id, role=principal.role.value
    )


@app.get("/api/v1/agents", response_model=AgentPage, tags=["agents"])
def list_agents(
    principal: PrincipalDep,
    db: TenantDbDep,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    cursor: str | None = None,
) -> AgentPage:
    query = (
        select(Agent)
        .where(Agent.tenant_id == principal.tenant_id)
        .order_by(Agent.id)
        .limit(limit + 1)
    )
    if cursor:
        query = query.where(Agent.id > cursor)
    rows = list(db.scalars(query))
    page, extra = rows[:limit], rows[limit:]
    return AgentPage(
        items=[AgentRead.model_validate(a) for a in page],
        next_cursor=page[-1].id if extra else None,
    )


@app.post("/api/v1/agents", response_model=AgentRead, status_code=201, tags=["agents"])
def create_agent(payload: AgentCreate, principal: AdminPrincipal, db: TenantDbDep) -> Agent:
    agent = Agent(tenant_id=principal.tenant_id, **payload.model_dump())
    db.add(agent)
    db.flush()
    record_audit(db, principal, "agent.created", "agent", agent.id)
    db.commit()
    db.refresh(agent)  # new transaction: tenant context is re-applied by the session hook
    return agent


@app.post("/api/v1/agents/{agent_id}/publish", response_model=AgentRead, tags=["agents"])
def publish_agent(agent_id: str, principal: AdminPrincipal, db: TenantDbDep) -> Agent:
    # Immutable versions arrive in WP2; for now publishing marks the agent live for the widget.
    agent = db.scalar(
        select(Agent).where(Agent.id == agent_id, Agent.tenant_id == principal.tenant_id)
    )
    if agent is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Agent not found")
    agent.status = "published"
    agent.published_at = utcnow()
    record_audit(db, principal, "agent.published", "agent", agent.id)
    db.commit()
    db.refresh(agent)
    return agent


@app.get("/api/v1/agents/{agent_id}", response_model=AgentRead, tags=["agents"])
def get_agent(agent_id: str, principal: PrincipalDep, db: TenantDbDep) -> Agent:
    agent = db.scalar(
        select(Agent).where(Agent.id == agent_id, Agent.tenant_id == principal.tenant_id)
    )
    if agent is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Agent not found")
    return agent
