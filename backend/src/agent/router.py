"""
FastAPI router for the StockLens Agent chat API.

Endpoints:
    - POST   /agent/chat               — streaming chat (SSE)
    - GET    /agent/conversations       — list user conversations
    - GET    /agent/conversations/{id}  — get conversation messages
    - DELETE /agent/conversations/{id}  — delete a conversation

SSE event types emitted by POST /agent/chat:

    | Event        | Data                               | Description                      |
    | ------------ | ---------------------------------- | -------------------------------- |
    | token        | string                             | A text chunk of the response     |
    | tool_start   | string                             | Tool name that started executing |
    | tool_end     | string                             | Tool name that completed         |
    | done         | {conversation_id, full_response}   | Stream complete                  |
    | error        | {error}                            | An error occurred                |
"""

from __future__ import annotations

import json
from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from langsmith import Client

from src.agent import repository as agent_repo
from src.agent.schemas import AgentFeedbackRequest, ChatRequest
from src.agent.service import agent_service
from src.auth.dependencies import get_current_user
from src.auth.schemas import UserInDB
from src.config import settings
from src.database.connection import connection_ctx
from src.limiter import limiter

logger = structlog.get_logger()
router = APIRouter(tags=["agent"])


@router.post("/chat")
@limiter.limit(settings.RATE_LIMIT_AGENT)
async def chat(
    request: Request,
    body: ChatRequest,
    current_user: UserInDB = Depends(get_current_user),
):
    """Streaming chat endpoint. Returns SSE events.

    Two-tier state management:
    1. conversation_id provided → load from Redis (hot) or RDS (cold)
    2. No conversation_id → create new conversation row in RDS
    """
    # Resolve or create conversation
    conversation_id = body.conversation_id
    async with connection_ctx() as conn:
        if conversation_id:
            conv = await agent_repo.get_conversation(conn, conversation_id, current_user.id)
            if not conv:
                raise HTTPException(status_code=404, detail="Conversation not found")
        else:
            conversation_id = await agent_repo.create_conversation(conn, current_user.id)

    async def event_generator():
        try:
            full_response = ""
            trace_id = ""
            async for event in agent_service.process_message(
                conversation_id,
                current_user.id,
                body.message,
            ):
                if event["event"] == "token":
                    full_response += event["data"]
                elif event["event"] == "_done":
                    # Internal signal from service — capture trace_id, don't emit
                    if isinstance(event["data"], dict):
                        trace_id = event["data"].get("trace_id", "")
                    continue
                yield f"event: {event['event']}\ndata: {json.dumps(event['data'])}\n\n"

            done_payload = json.dumps(
                {
                    "conversation_id": str(conversation_id),
                    "full_response": full_response,
                    "trace_id": trace_id,
                }
            )
            yield f"event: done\ndata: {done_payload}\n\n"
        except Exception as e:
            logger.exception("chat_stream_error", error=str(e))
            yield f"event: error\ndata: {json.dumps({'error': str(e)})}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/conversations")
async def list_conversations(
    request: Request,
    current_user: UserInDB = Depends(get_current_user),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    """List user's conversations (lightweight — no message bodies)."""
    async with connection_ctx() as conn:
        conversations = await agent_repo.get_user_conversations(
            conn,
            current_user.id,
            limit,
            offset,
        )
        total = await agent_repo.get_user_conversations_count(conn, current_user.id)
    return {"conversations": conversations, "total": total}


@router.get("/conversations/{conversation_id}")
async def get_conversation(
    request: Request,
    conversation_id: UUID,
    current_user: UserInDB = Depends(get_current_user),
):
    """Get full message history for a conversation."""
    async with connection_ctx() as conn:
        conv = await agent_repo.get_conversation(conn, conversation_id, current_user.id)
        if not conv:
            raise HTTPException(status_code=404, detail="Conversation not found")
        messages = await agent_repo.get_conversation_messages(conn, conversation_id)
    return {"conversation": conv, "messages": messages}


@router.delete("/conversations/{conversation_id}", status_code=204)
async def delete_conversation(
    request: Request,
    conversation_id: UUID,
    current_user: UserInDB = Depends(get_current_user),
):
    """Delete a conversation and all its messages (cascaded via FK)."""
    async with connection_ctx() as conn:
        conv = await agent_repo.get_conversation(conn, conversation_id, current_user.id)
        if not conv:
            raise HTTPException(status_code=404, detail="Conversation not found")
        await agent_repo.delete_conversation(conn, conversation_id)


@router.post("/feedback")
async def submit_feedback(
    body: AgentFeedbackRequest,
    current_user: UserInDB = Depends(get_current_user),
):
    """Record user feedback against a LangSmith trace."""
    if not settings.LANGCHAIN_API_KEY:
        return {"status": "skipped", "reason": "langsmith_disabled"}

    client = Client()
    client.create_feedback(
        feedback_key=body.rating,
        trace_id=body.trace_id,
        comment=body.comment or f"user={current_user.id}",
        feedback_source_type="app",
        source_metadata={"user_id": str(current_user.id)},
    )
    return {"status": "ok"}
