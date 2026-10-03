"""Request-scoped tenant binding for row-level security."""

from typing import Annotated

from fastapi import Depends
from sqlalchemy.orm import Session

from .auth import PrincipalDep
from .db import bind_context, get_db

DbDep = Annotated[Session, Depends(get_db)]


def tenant_session(principal: PrincipalDep, db: DbDep) -> Session:
    """Bind the verified tenant (and user) to this session's transactions."""
    bind_context(db, user_id=principal.user_id, tenant_id=principal.tenant_id)
    return db


TenantDbDep = Annotated[Session, Depends(tenant_session)]
