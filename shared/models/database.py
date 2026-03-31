"""
ARCANE Database Models
SQLAlchemy ORM models for PostgreSQL.
Tables: users, projects, chats, messages, tool_calls, usage_records, memory_entries
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import (
    Boolean, Column, DateTime, Enum as SAEnum, Float, ForeignKey,
    Integer, String, Text, JSON, Index, UniqueConstraint,
    create_engine,
)
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase, relationship, Mapped, mapped_column


class Base(DeclarativeBase):
    """Base class for all ARCANE models."""
    pass


class User(Base):
    """User account."""
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    username: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    email: Mapped[Optional[str]] = mapped_column(String(255), unique=True, nullable=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(20), default="user")  # user, admin
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    model_strategy: Mapped[str] = mapped_column(String(20), default="balance")
    budget_limit: Mapped[float] = mapped_column(Float, default=5.0)
    total_spent: Mapped[float] = mapped_column(Float, default=0.0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    last_login: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    telegram_chat_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    notification_settings: Mapped[Optional[dict]] = mapped_column(
        JSONB, nullable=True,
        default=lambda: {"telegram_enabled": False, "notify_on_complete": True, "notify_on_error": True}
    )

    # Relationships
    projects = relationship("Project", back_populates="user", cascade="all, delete-orphan")
    chats = relationship("Chat", back_populates="user", cascade="all, delete-orphan")


class Project(Base):
    """A project groups related chats and artifacts."""
    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    user_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    project_type: Mapped[str] = mapped_column(String(50), default="general")
    status: Mapped[str] = mapped_column(String(20), default="active")  # active, completed, archived
    model_strategy: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    total_cost: Mapped[float] = mapped_column(Float, default=0.0)
    metadata_json: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    user = relationship("User", back_populates="projects")
    chats = relationship("Chat", back_populates="project", cascade="all, delete-orphan")

    __table_args__ = (
        Index("idx_projects_user_id", "user_id"),
    )


class Chat(Base):
    """A conversation between user and ARCANE agent."""
    __tablename__ = "chats"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    user_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    project_id: Mapped[Optional[str]] = mapped_column(
        UUID(as_uuid=False), ForeignKey("projects.id", ondelete="SET NULL"), nullable=True
    )
    title: Mapped[str] = mapped_column(String(500), default="New Chat")
    status: Mapped[str] = mapped_column(String(20), default="idle")
    # idle, thinking, executing, waiting_user, completed, error
    agent_status: Mapped[str] = mapped_column(String(50), default="idle")
    current_phase: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    total_cost: Mapped[float] = mapped_column(Float, default=0.0)
    total_tokens: Mapped[int] = mapped_column(Integer, default=0)
    model_strategy: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    plan_json: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    scratchpad: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    user = relationship("User", back_populates="chats")
    project = relationship("Project", back_populates="chats")
    messages = relationship("Message", back_populates="chat", cascade="all, delete-orphan",
                            order_by="Message.created_at")

    __table_args__ = (
        Index("idx_chats_user_id", "user_id"),
        Index("idx_chats_project_id", "project_id"),
        # S8: Composite index for list_chats sorted by updated_at (most common query)
        Index("idx_chats_user_updated", "user_id", "updated_at"),
        # S8: Index for status filtering (admin dashboard)
        Index("idx_chats_status", "status"),
    )


class Message(Base):
    """A single message in a chat (user, assistant, system, or tool)."""
    __tablename__ = "messages"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    chat_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("chats.id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    # user, assistant, system, tool
    content: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    tool_calls_json: Mapped[Optional[list]] = mapped_column(JSONB, nullable=True)
    tool_call_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    tool_name: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    model_used: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    tokens_input: Mapped[int] = mapped_column(Integer, default=0)
    tokens_output: Mapped[int] = mapped_column(Integer, default=0)
    cost: Mapped[float] = mapped_column(Float, default=0.0)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    metadata_json: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    # Relationships
    chat = relationship("Chat", back_populates="messages")

    __table_args__ = (
        Index("idx_messages_chat_id", "chat_id"),
        Index("idx_messages_created_at", "created_at"),
        # S8: Composite index for get_messages(chat_id) ordered by created_at
        Index("idx_messages_chat_created", "chat_id", "created_at"),
    )


class ToolExecution(Base):
    """Record of a tool execution by the agent."""
    __tablename__ = "tool_executions"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    chat_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("chats.id", ondelete="CASCADE"), nullable=False
    )
    message_id: Mapped[Optional[str]] = mapped_column(
        UUID(as_uuid=False), ForeignKey("messages.id", ondelete="SET NULL"), nullable=True
    )
    tool_name: Mapped[str] = mapped_column(String(100), nullable=False)
    tool_params: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    result: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="pending")
    # pending, running, success, error
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    worker_used: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        Index("idx_tool_exec_chat_id", "chat_id"),
    )


class UsageRecord(Base):
    """LLM usage tracking for cost management."""
    __tablename__ = "usage_records"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    user_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    chat_id: Mapped[Optional[str]] = mapped_column(
        UUID(as_uuid=False), ForeignKey("chats.id", ondelete="SET NULL"), nullable=True
    )
    provider: Mapped[str] = mapped_column(String(50), nullable=False)  # openai, openrouter
    model: Mapped[str] = mapped_column(String(100), nullable=False)
    role: Mapped[str] = mapped_column(String(50), nullable=False)  # orchestrator, coder, browser...
    tier: Mapped[str] = mapped_column(String(20), nullable=False)  # nano, fast, standard, genius, deep
    tokens_input: Mapped[int] = mapped_column(Integer, default=0)
    tokens_output: Mapped[int] = mapped_column(Integer, default=0)
    cost: Mapped[float] = mapped_column(Float, default=0.0)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    was_escalated: Mapped[bool] = mapped_column(Boolean, default=False)
    was_fallback: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        Index("idx_usage_user_id", "user_id"),
        Index("idx_usage_created_at", "created_at"),
        Index("idx_usage_model", "model"),
    )


class InterruptedTask(Base):
    """Serialized agent state saved on stop for conversation continuity."""
    __tablename__ = "interrupted_tasks"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    chat_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("chats.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    agent_state: Mapped[dict] = mapped_column(JSONB, nullable=False)
    messages_snapshot: Mapped[Optional[list]] = mapped_column(JSONB, nullable=True)
    iteration: Mapped[int] = mapped_column(Integer, default=0)
    total_cost: Mapped[float] = mapped_column(Float, default=0.0)
    budget_remaining: Mapped[float] = mapped_column(Float, default=0.0)
    reason: Mapped[str] = mapped_column(String(50), default="user_stop")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    resumed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    __table_args__ = (
        Index("idx_interrupted_tasks_chat_id", "chat_id"),
        Index("idx_interrupted_tasks_user_id", "user_id"),
    )


class UserPreference(Base):
    """Auto-extracted user preferences from conversations."""
    __tablename__ = "user_preferences"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    user_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    category: Mapped[str] = mapped_column(String(100), nullable=False)
    key: Mapped[str] = mapped_column(String(255), nullable=False)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, default=0.5)
    source: Mapped[str] = mapped_column(String(50), default="auto")
    source_chat_id: Mapped[Optional[str]] = mapped_column(
        UUID(as_uuid=False), nullable=True
    )
    times_confirmed: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("user_id", "category", "key", name="uq_user_pref"),
        Index("idx_user_prefs_user_id", "user_id"),
    )


class Artifact(Base):
    """Files and artifacts produced by the agent."""
    __tablename__ = "artifacts"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    chat_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("chats.id", ondelete="CASCADE"), nullable=False
    )
    project_id: Mapped[Optional[str]] = mapped_column(
        UUID(as_uuid=False), ForeignKey("projects.id", ondelete="SET NULL"), nullable=True
    )
    filename: Mapped[str] = mapped_column(String(500), nullable=False)
    file_type: Mapped[str] = mapped_column(String(50), nullable=False)
    # code, image, document, config, archive, screenshot
    mime_type: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    storage_path: Mapped[str] = mapped_column(String(1000), nullable=False)
    # MinIO path or local path
    version: Mapped[int] = mapped_column(Integer, default=1)
    content_preview: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    metadata_json: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        Index("idx_artifacts_chat_id", "chat_id"),
        Index("idx_artifacts_project_id", "project_id"),
    )


class ChatFeedback(Base):
    """User feedback on agent results."""
    __tablename__ = "chat_feedback"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    chat_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("chats.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    rating: Mapped[int] = mapped_column(Integer, nullable=False)  # 1-5
    comment: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        Index("idx_chat_feedback_chat_id", "chat_id"),
    )


# ─── Database Engine & Session ───────────────────────────────────────────────

_async_engine = None
_async_session_factory = None


def get_async_engine(database_url: str):
    """Get or create async SQLAlchemy engine."""
    global _async_engine
    if _async_engine is None:
        _async_engine = create_async_engine(
            database_url,
            echo=False,
            pool_size=10,
            max_overflow=20,
            pool_pre_ping=True,
        )
    return _async_engine


def get_session_factory(database_url: str) -> async_sessionmaker[AsyncSession]:
    """Get or create async session factory."""
    global _async_session_factory
    if _async_session_factory is None:
        engine = get_async_engine(database_url)
        _async_session_factory = async_sessionmaker(
            engine, class_=AsyncSession, expire_on_commit=False
        )
    return _async_session_factory


async def init_database(database_url: str):
    """Create all tables if they don't exist."""
    engine = get_async_engine(database_url)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def get_db_session(database_url: str) -> AsyncSession:
    """Get a database session (for use in dependency injection)."""
    factory = get_session_factory(database_url)
    async with factory() as session:
        yield session
