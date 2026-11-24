"""
Pydantic models for the agent chat API.

Defines request/response schemas for the SSE-streaming chat endpoint
and conversation history CRUD.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    """Request body for POST /agent/chat."""

    message: str = Field(..., min_length=1, max_length=8000)
    conversation_id: UUID | None = None  # None = new conversation


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
    trace_id: str | None = None  # LangSmith trace id (optional, falls back to conversation_id)
    conversation_id: UUID | None = None  # Conversation-level feedback when no trace_id
    comment: str | None = None
