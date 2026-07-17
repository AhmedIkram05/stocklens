"""
FastAPI router for the StockLens Agent chat API.

Endpoints:
    - POST   /agent/chat          — send a message (returns full response; SSE streaming in R3)
    - GET    /agent/conversations  — list user conversations
    - GET    /agent/conversations/{id} — get conversation messages
    - DELETE /agent/conversations/{id} — delete a conversation

Note: Full SSE streaming via ``StreamingResponse`` is deferred to Round 3.
The POST endpoint currently consumes the streaming generator internally
and returns a ``ChatResponse`` with the complete text.
"""

from __future__ import annotations

from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query

from src.agent import repository as agent_repo
from src.agent.schemas import ChatRequest, ChatResponse
from src.agent.service import agent_service
from src.auth.dependencies import get_current_user_id
from src.database.connection import connection_ctx

logger = structlog.get_logger()
router = APIRouter(tags=["agent"])


@router.post("/chat", response_model=ChatResponse)
async def chat(
    body: ChatRequest,
    user_id: str = Depends(get_current_user_id),
):
    """Send a message to the agent and receive a response.

    Creates a new conversation when ``conversation_id`` is ``null``.
    Continues an existing one when provided.

    Consumes the streaming process_message generator and returns the
    assembled response text.  Round 3 will upgrade this to true SSE
    streaming via ``StreamingResponse``.
    """
    # Create conversation if needed
    if body.conversation_id is None:
        async with connection_ctx() as conn:
            conversation_id = await agent_repo.create_conversation(conn, user_id)
    else:
        # Verify the conversation exists and belongs to user
        async with connection_ctx() as conn:
            existing = await agent_repo.get_conversation(conn, body.conversation_id, user_id)
            if existing is None:
                raise HTTPException(status_code=404, detail="Conversation not found")
        conversation_id = body.conversation_id

    # Consume the streaming generator to collect the full response
    response_text = ""
    async for event in agent_service.process_message(
        conversation_id,
        user_id,
        body.message,
    ):
        if event["event"] == "token":
            response_text += event["data"]

    if not response_text:
        response_text = "I processed your request but have no specific answer."

    return ChatResponse(
        conversation_id=conversation_id,
        message=response_text,
    )


@router.get("/conversations")
async def list_conversations(
    user_id: str = Depends(get_current_user_id),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    """List the user's conversations, most recent first."""
    conversations = await agent_service.list_conversations(
        user_id,
        limit=limit,
        offset=offset,
    )
    async with connection_ctx() as conn:
        total = await agent_repo.get_user_conversations_count(conn, user_id)
    return {"conversations": conversations, "total": total}


@router.get("/conversations/{conversation_id}")
async def get_conversation_messages(
    conversation_id: UUID,
    user_id: str = Depends(get_current_user_id),
):
    """Get all messages in a conversation."""
    messages = await agent_service.get_messages(user_id, conversation_id)
    if messages is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return {"conversation_id": str(conversation_id), "messages": messages}


@router.delete("/conversations/{conversation_id}", status_code=204)
async def delete_conversation(
    conversation_id: UUID,
    user_id: str = Depends(get_current_user_id),
):
    """Delete a conversation and its messages."""
    deleted = await agent_service.delete_conversation(user_id, conversation_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Conversation not found")
