from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from .models import Role


class AgentCreate(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    role_description: str = Field(default="Sales concierge", max_length=200)
    primary_objective: str = Field(min_length=5, max_length=1000)


class AgentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    name: str
    role_description: str
    primary_objective: str
    status: str
    public_id: str
    created_at: datetime
    updated_at: datetime


class MeRead(BaseModel):
    user_id: str
    tenant_id: str
    role: str


class AgentPage(BaseModel):
    items: list[AgentRead]
    next_cursor: str | None


class OrganisationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    name: str
    status: str


class MemberRead(BaseModel):
    membership_id: str
    user_id: str
    email: str
    role: Role


class MemberPage(BaseModel):
    items: list[MemberRead]
    next_cursor: str | None


class MemberUpdate(BaseModel):
    role: Role


class InvitationCreate(BaseModel):
    email: EmailStr
    role: Role


class InvitationRead(BaseModel):
    id: str
    email: str
    role: Role
    status: str
    expires_at: datetime


class InvitationCreated(InvitationRead):
    # Returned once; only its hash is stored. Delivered by email in WP8.
    token: str
