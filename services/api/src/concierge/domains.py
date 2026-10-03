"""Approved embedding domains (admin API)."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, field_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from .audit import record_audit
from .auth import Principal, require_roles
from .config import get_settings
from .models import Domain, Role
from .origins import normalise_hostname
from .tenancy import TenantDbDep

router = APIRouter(prefix="/api/v1/domains", tags=["domains"])
Admin = Annotated[Principal, Depends(require_roles(Role.platform_admin, Role.customer_admin))]


class DomainCreate(BaseModel):
    hostname: str

    @field_validator("hostname")
    @classmethod
    def valid_hostname(cls, value: str) -> str:
        return normalise_hostname(value)


class DomainRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    hostname: str
    status: str


@router.get("", response_model=list[DomainRead])
def list_domains(principal: Admin, db: TenantDbDep) -> list[Domain]:
    return list(db.scalars(select(Domain).order_by(Domain.hostname)))


@router.post("", response_model=DomainRead, status_code=201)
def add_domain(payload: DomainCreate, principal: Admin, db: TenantDbDep) -> Domain:
    domain = Domain(tenant_id=principal.tenant_id, hostname=payload.hostname)
    db.add(domain)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "Domain already added") from exc
    record_audit(db, principal, "domain.added", "domain", domain.id)
    db.commit()
    db.refresh(domain)
    return domain


@router.post("/{domain_id}/verify", response_model=DomainRead)
def verify_domain(domain_id: str, principal: Admin, db: TenantDbDep) -> Domain:
    if not get_settings().allow_manual_domain_verification:
        raise HTTPException(
            status.HTTP_501_NOT_IMPLEMENTED, "DNS verification is not available yet"
        )
    domain = db.scalar(select(Domain).where(Domain.id == domain_id))
    if domain is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Domain not found")
    domain.status = "verified"
    record_audit(db, principal, "domain.verified_manually", "domain", domain.id)
    db.commit()
    db.refresh(domain)
    return domain
