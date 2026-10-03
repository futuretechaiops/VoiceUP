"""Organisation, member and invitation endpoints (spec section 9)."""

import hashlib
import secrets
from datetime import timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select

from .audit import record_audit
from .auth import Principal, require_roles
from .models import Invitation, Membership, Role, Tenant, User, utcnow
from .schemas import (
    InvitationCreate,
    InvitationCreated,
    MemberPage,
    MemberRead,
    MemberUpdate,
    OrganisationRead,
)
from .tenancy import TenantDbDep

router = APIRouter(prefix="/api/v1/organisations", tags=["organisations"])

Admin = Annotated[Principal, Depends(require_roles(Role.platform_admin, Role.customer_admin))]
ASSIGNABLE = {Role.customer_admin, Role.sales_manager, Role.sales_agent, Role.analyst}
INVITATION_TTL = timedelta(days=7)


def _own_org(organisation_id: str, principal: Principal) -> None:
    # Cross-tenant resources return 404 so their existence is not revealed (ADR 0002).
    if organisation_id != principal.tenant_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Organisation not found")


@router.get("/{organisation_id}", response_model=OrganisationRead)
def get_organisation(organisation_id: str, principal: Admin, db: TenantDbDep) -> Tenant:
    _own_org(organisation_id, principal)
    tenant = db.get(Tenant, organisation_id)
    if tenant is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Organisation not found")
    return tenant


@router.get("/{organisation_id}/members", response_model=MemberPage)
def list_members(
    organisation_id: str,
    principal: Admin,
    db: TenantDbDep,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    cursor: str | None = None,
) -> MemberPage:
    _own_org(organisation_id, principal)
    query = (
        select(Membership, User.email)
        .join(User, User.id == Membership.user_id)
        .where(Membership.tenant_id == principal.tenant_id)
        .order_by(Membership.id)
        .limit(limit + 1)
    )
    if cursor:
        query = query.where(Membership.id > cursor)
    rows = db.execute(query).all()
    page, extra = rows[:limit], rows[limit:]
    return MemberPage(
        items=[
            MemberRead(membership_id=m.id, user_id=m.user_id, email=email, role=m.role)
            for m, email in page
        ],
        next_cursor=page[-1][0].id if extra else None,
    )


@router.post("/{organisation_id}/invitations", response_model=InvitationCreated, status_code=201)
def invite(
    organisation_id: str, payload: InvitationCreate, principal: Admin, db: TenantDbDep
) -> InvitationCreated:
    _own_org(organisation_id, principal)
    if payload.role not in ASSIGNABLE:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Role cannot be invited")
    token = secrets.token_urlsafe(32)
    invitation = Invitation(
        tenant_id=principal.tenant_id,
        email=str(payload.email).lower(),
        role=payload.role,
        token_hash=hashlib.sha256(token.encode()).hexdigest(),
        invited_by=principal.user_id,
        expires_at=utcnow() + INVITATION_TTL,
    )
    db.add(invitation)
    db.flush()
    record_audit(db, principal, "invitation.created", "invitation", invitation.id)
    db.commit()
    return InvitationCreated(
        id=invitation.id,
        email=invitation.email,
        role=invitation.role,
        status=invitation.status,
        expires_at=invitation.expires_at,
        token=token,
    )


@router.patch("/{organisation_id}/members/{membership_id}", response_model=MemberRead)
def change_role(
    organisation_id: str,
    membership_id: str,
    payload: MemberUpdate,
    principal: Admin,
    db: TenantDbDep,
) -> MemberRead:
    _own_org(organisation_id, principal)
    if payload.role not in ASSIGNABLE:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Role cannot be assigned")
    membership = db.scalar(
        select(Membership)
        .where(Membership.id == membership_id, Membership.tenant_id == principal.tenant_id)
        .with_for_update()
    )
    if membership is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Member not found")
    if membership.role == Role.customer_admin and payload.role != Role.customer_admin:
        admins = db.scalar(
            select(func.count())
            .select_from(Membership)
            .where(
                Membership.tenant_id == principal.tenant_id,
                Membership.role == Role.customer_admin,
            )
        )
        if admins is not None and admins <= 1:
            raise HTTPException(
                status.HTTP_409_CONFLICT, "The last administrator cannot be demoted"
            )
    membership.role = payload.role
    record_audit(db, principal, "membership.role_changed", "membership", membership.id)
    email = db.scalar(select(User.email).where(User.id == membership.user_id)) or ""
    db.commit()
    return MemberRead(
        membership_id=membership.id, user_id=membership.user_id, email=email, role=membership.role
    )
