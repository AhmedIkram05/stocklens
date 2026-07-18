"""
Pydantic models for the agent chat API.

Defines request/response schemas for the SSE-streaming chat endpoint
and conversation history CRUD.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class ChatRequest(BaseModel):
    """Request body for POST /agent/chat."""

    message: str
    conversation_id: UUID | None = None  # None = new conversation


class ToolCallEvent(BaseModel):
    """Emitted when a tool starts executing."""

    tool_name: str
    input: dict


class ToolResultEvent(BaseModel):
    """Emitted when a tool completes execution."""

    tool_name: str
    output_summary: str
    success: bool


class SSEEvent(BaseModel):
    """A single SSE event payload."""

    event: str  # "token" | "tool_start" | "tool_end" | "done" | "error"
    data: str  # JSON-encoded payload


class ConversationSummary(BaseModel):
    """Lightweight summary for the conversation list endpoint."""

    id: UUID
    title: str | None
    message_count: int
    created_at: datetime
    updated_at: datetime


class MessageResponse(BaseModel):
    """A single message in a conversation."""

    role: str
    content: str
    tools_used: dict | None
    reasoning_steps: dict | None
    created_at: datetime


class AgentFeedbackRequest(BaseModel):
    """Request body for POST /agent/feedback (LangSmith feedback)."""

    rating: str  # e.g. "positive" / "negative" → used as the feedback_key
    trace_id: str  # LangSmith trace id to attach feedback to
    comment: str | None = None
