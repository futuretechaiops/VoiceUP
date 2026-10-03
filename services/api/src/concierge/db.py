from collections.abc import Generator

from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import DeclarativeBase, Session, SessionTransaction, sessionmaker

from .config import get_settings


class Base(DeclarativeBase):
    pass


settings = get_settings()
engine = create_engine(settings.database_url, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


@event.listens_for(Session, "after_begin")
def _apply_request_context(
    session: Session, transaction: SessionTransaction, connection: object
) -> None:
    """Re-apply tenant and user context at the start of every transaction.

    ``set_config(..., true)`` is transaction-local, so a commit would otherwise drop the tenant
    and row-level security would hide the caller's own rows (see ADR 0003). With no context set,
    policies match nothing: the system fails closed.
    """
    info = session.info
    if tenant_id := info.get("tenant_id"):
        connection.execute(  # type: ignore[attr-defined]
            text("SELECT set_config('app.tenant_id', :v, true)"), {"v": tenant_id}
        )
    if user_id := info.get("user_id"):
        connection.execute(  # type: ignore[attr-defined]
            text("SELECT set_config('app.user_id', :v, true)"), {"v": user_id}
        )


def bind_context(
    session: Session, *, user_id: str | None = None, tenant_id: str | None = None
) -> None:
    """Record the verified context and apply it to the transaction already in progress."""
    if user_id:
        session.info["user_id"] = user_id
        session.execute(text("SELECT set_config('app.user_id', :v, true)"), {"v": user_id})
    if tenant_id:
        session.info["tenant_id"] = tenant_id
        session.execute(text("SELECT set_config('app.tenant_id', :v, true)"), {"v": tenant_id})


def get_db() -> Generator[Session, None, None]:
    with SessionLocal() as session:
        yield session
