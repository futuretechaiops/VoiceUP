import uuid
from datetime import UTC, datetime
from enum import StrEnum

from sqlalchemy import (
    Computed,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base


def new_id() -> str:
    return str(uuid.uuid4())


def utcnow() -> datetime:
    return datetime.now(UTC)


class Role(StrEnum):
    platform_admin = "platform_admin"
    customer_admin = "customer_admin"
    sales_manager = "sales_manager"
    sales_agent = "sales_agent"
    analyst = "analyst"


class Tenant(Base):
    __tablename__ = "tenants"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(30), default="active")
    notify_email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class User(Base):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    identity_subject: Mapped[str] = mapped_column(String(255), unique=True)
    email: Mapped[str] = mapped_column(String(320))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Membership(Base):
    __tablename__ = "memberships"
    __table_args__ = (UniqueConstraint("tenant_id", "user_id"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    role: Mapped[Role] = mapped_column(Enum(Role, name="role", create_type=False))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Agent(Base):
    __tablename__ = "agents"
    __table_args__ = (UniqueConstraint("tenant_id", "name"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    role_description: Mapped[str] = mapped_column(String(200), default="Sales concierge")
    primary_objective: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(30), default="draft")
    public_id: Mapped[str] = mapped_column(
        String(64), unique=True, default=lambda: "agt_" + uuid.uuid4().hex
    )
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class AuditEvent(Base):
    __tablename__ = "audit_events"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    tenant_id: Mapped[str] = mapped_column(String(36), index=True)
    actor_user_id: Mapped[str] = mapped_column(String(36), index=True)
    action: Mapped[str] = mapped_column(String(120))
    target_type: Mapped[str] = mapped_column(String(80))
    target_id: Mapped[str] = mapped_column(String(36))
    outcome: Mapped[str] = mapped_column(String(30), default="success")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Invitation(Base):
    __tablename__ = "invitations"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    email: Mapped[str] = mapped_column(String(320))
    role: Mapped[Role] = mapped_column(Enum(Role, name="role", create_type=False))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    invited_by: Mapped[str] = mapped_column(String(36))
    status: Mapped[str] = mapped_column(String(20), default="pending")
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Domain(Base):
    __tablename__ = "domains"
    __table_args__ = (UniqueConstraint("tenant_id", "hostname"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    hostname: Mapped[str] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(20), default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Conversation(Base):
    __tablename__ = "conversations"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    agent_id: Mapped[str] = mapped_column(ForeignKey("agents.id", ondelete="CASCADE"))
    channel: Mapped[str] = mapped_column(String(20), default="web_text")
    origin: Mapped[str] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(20), default="active")
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Message(Base):
    __tablename__ = "messages"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    conversation_id: Mapped[str] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[str] = mapped_column(String(20))
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class KnowledgeSource(Base):
    __tablename__ = "knowledge_sources"
    __table_args__ = (UniqueConstraint("tenant_id", "url"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    url: Mapped[str] = mapped_column(String(2000))
    status: Mapped[str] = mapped_column(String(20), default="pending")
    page_count: Mapped[int] = mapped_column(Integer, default=0)
    last_crawled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class KnowledgeDocument(Base):
    __tablename__ = "knowledge_documents"
    __table_args__ = (UniqueConstraint("tenant_id", "url"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    source_id: Mapped[str] = mapped_column(ForeignKey("knowledge_sources.id", ondelete="CASCADE"))
    url: Mapped[str] = mapped_column(String(2000))
    title: Mapped[str] = mapped_column(String(500))
    checksum: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(20), default="indexed")
    content_version: Mapped[int] = mapped_column(Integer, default=1)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class KnowledgeChunk(Base):
    __tablename__ = "knowledge_chunks"
    __table_args__ = (UniqueConstraint("tenant_id", "checksum"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    document_id: Mapped[str] = mapped_column(
        ForeignKey("knowledge_documents.id", ondelete="CASCADE")
    )
    ordinal: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)
    checksum: Mapped[str] = mapped_column(String(64))
    tsv: Mapped[str | None] = mapped_column(
        TSVECTOR, Computed("to_tsvector('english', text)", persisted=True), nullable=True
    )


class MessageSource(Base):
    __tablename__ = "message_sources"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    message_id: Mapped[str] = mapped_column(ForeignKey("messages.id", ondelete="CASCADE"))
    chunk_id: Mapped[str] = mapped_column(String(36))
    document_url: Mapped[str] = mapped_column(String(2000))
    document_title: Mapped[str] = mapped_column(String(500))
    rank: Mapped[int] = mapped_column(Integer)
    score: Mapped[float] = mapped_column(Float)


class Lead(Base):
    __tablename__ = "leads"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    conversation_id: Mapped[str] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), unique=True
    )
    name: Mapped[str] = mapped_column(String(120))
    phone: Mapped[str] = mapped_column(String(32))
    email: Mapped[str] = mapped_column(String(320))
    consent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    consent_text: Mapped[str] = mapped_column(Text)
    origin: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class EmailOutbox(Base):
    __tablename__ = "email_outbox"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    to_address: Mapped[str] = mapped_column(String(320))
    reply_to: Mapped[str | None] = mapped_column(String(320), nullable=True)
    subject: Mapped[str] = mapped_column(String(300))
    body: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="pending")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    next_attempt_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    idempotency_key: Mapped[str] = mapped_column(String(100), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
