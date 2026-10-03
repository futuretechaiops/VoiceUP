import asyncio
import logging
import time
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Query, Request, status
from fastapi.responses import FileResponse
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from . import domains, organisations, widget_api
from .audit import record_audit
from .auth import Principal, PrincipalDep, require_roles
from .config import get_settings
from .db import SessionLocal, get_db
from .logging_config import configure_logging
from .mailer import get_mailer
from .models import Agent, Role, utcnow
from .outbox import process_outbox
from .problems import install_problem_handlers
from .schemas import AgentCreate, AgentPage, AgentRead, MeRead
from .tenancy import TenantDbDep

configure_logging(get_settings().log_level)
access_log = logging.getLogger("concierge.access")

log = logging.getLogger("concierge.app")


async def _outbox_loop() -> None:
    settings = get_settings()
    mailer = get_mailer(settings)
    while True:
        try:
            await asyncio.to_thread(process_outbox, SessionLocal, mailer)
        except Exception:  # noqa: BLE001 - the worker must survive a bad cycle
            log.exception("outbox cycle failed")
        await asyncio.sleep(settings.outbox_interval_seconds)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    task = asyncio.create_task(_outbox_loop()) if get_settings().outbox_worker_enabled else None
    yield
    if task:
        task.cancel()


_settings = get_settings()
app = FastAPI(
    title="VoiceUP AI Sales Concierge API",
    version="0.3.0",
    docs_url="/docs" if _settings.admin_api_enabled else None,
    openapi_url="/api/v1/openapi.json" if _settings.admin_api_enabled else None,
    lifespan=lifespan,
)
install_problem_handlers(app)
admin = APIRouter()
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


@admin.get("/api/v1/me", response_model=MeRead, tags=["identity"])
def me(principal: PrincipalDep) -> MeRead:
    return MeRead(
        user_id=principal.user_id, tenant_id=principal.tenant_id, role=principal.role.value
    )


@admin.get("/api/v1/agents", response_model=AgentPage, tags=["agents"])
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


@admin.post("/api/v1/agents", response_model=AgentRead, status_code=201, tags=["agents"])
def create_agent(payload: AgentCreate, principal: AdminPrincipal, db: TenantDbDep) -> Agent:
    agent = Agent(tenant_id=principal.tenant_id, **payload.model_dump())
    db.add(agent)
    db.flush()
    record_audit(db, principal, "agent.created", "agent", agent.id)
    db.commit()
    db.refresh(agent)  # new transaction: tenant context is re-applied by the session hook
    return agent


@admin.post("/api/v1/agents/{agent_id}/publish", response_model=AgentRead, tags=["agents"])
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


@admin.get("/api/v1/agents/{agent_id}", response_model=AgentRead, tags=["agents"])
def get_agent(agent_id: str, principal: PrincipalDep, db: TenantDbDep) -> Agent:
    agent = db.scalar(
        select(Agent).where(Agent.id == agent_id, Agent.tenant_id == principal.tenant_id)
    )
    if agent is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Agent not found")
    return agent


if _settings.admin_api_enabled:
    app.include_router(admin)
    app.include_router(organisations.router)
    app.include_router(domains.router)


@app.get("/widget.js", include_in_schema=False)
def widget_script() -> FileResponse:
    path = Path(get_settings().widget_js_path)
    if not path.is_file():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Widget bundle not built")
    return FileResponse(
        path, media_type="application/javascript", headers={"Cache-Control": "public, max-age=300"}
    )
