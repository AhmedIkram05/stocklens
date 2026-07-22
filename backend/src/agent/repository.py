"""
Repository layer for agent conversations.

Module-level async functions using raw asyncpg (same pattern as
``market/repository.py`` and ``cash_flows/repository.py``).

Two tables:
    - ``conversations`` — lightweight metadata for the list endpoint
    - ``agent_conversations`` — multi-turn message archive (turns)
"""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4


async def create_conversation(
    conn: Any,
    user_id: str,
    title: str | None = None,
) -> UUID:
    """Insert a new conversation row and return its UUID."""
    conversation_id = uuid4()
    await conn.execute(
        "INSERT INTO conversations (id, user_id, title) VALUES ($1::uuid, $2::uuid, $3)",
        conversation_id,
        user_id,
        title,
    )
    return conversation_id


async def get_user_conversations(
    conn: Any,
    user_id: str,
    limit: int = 20,
    offset: int = 0,
) -> list[dict[str, Any]]:
    """List conversations for a user, most recent first, with pagination."""
    rows = await conn.fetch(
        "SELECT id, user_id, title, message_count, created_at, updated_at "
        "FROM conversations "
        "WHERE user_id = $1::uuid "
        "ORDER BY updated_at DESC "
        "LIMIT $2 OFFSET $3",
        user_id,
        limit,
        offset,
    )
    return [dict(r) for r in rows]


async def get_conversation(
    conn: Any,
    conversation_id: UUID,
    user_id: str,
) -> dict[str, Any] | None:
    """Return a single conversation's metadata, or None if not found / not owned."""
    row = await conn.fetchrow(
        "SELECT id, user_id, title, message_count, created_at, updated_at "
        "FROM conversations "
        "WHERE id = $1::uuid AND user_id = $2::uuid",
        conversation_id,
        user_id,
    )
    return dict(row) if row else None


async def add_message(
    conn: Any,
    conversation_id: UUID,
    user_id: str,
    role: str,
    content: str,
    tools_used: list[dict] | None = None,
) -> int:
    """Insert a message into agent_conversations and return the id (BigInteger).

    *role* is ``"user"`` or ``"assistant"``.
    *tools_used* is a list of {name, status} dicts (JSONB).
    """
    row = await conn.fetchrow(
        "INSERT INTO agent_conversations "
        "(conversation_id, user_id, role, content, tools_used) "
        "VALUES ($1::uuid, $2::uuid, $3, $4, $5::jsonb) "
        "RETURNING id",
        conversation_id,
        user_id,
        role,
        content,
        tools_used,
    )
    return row["id"]


async def get_conversation_messages(
    conn: Any,
    conversation_id: UUID,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Return all messages for a conversation, ordered by created_at ASC."""
    rows = await conn.fetch(
        "SELECT id, conversation_id, role, content, tools_used, "
        "reasoning_steps, created_at "
        "FROM agent_conversations "
        "WHERE conversation_id = $1::uuid "
        "ORDER BY created_at ASC "
        "LIMIT $2",
        conversation_id,
        limit,
    )
    return [dict(r) for r in rows]


async def update_conversation_metadata(
    conn: Any,
    conversation_id: UUID,
    message_count: int | None = None,
    title: str | None = None,
) -> None:
    """Bump conversation metadata after a turn.

    Always sets updated_at = now(). Optionally bumps message_count or
    sets a title (used for first-turn auto-title).
    """
    set_clauses = ["updated_at = now()"]
    params: list[Any] = []
    idx = 1

    if message_count is not None:
        set_clauses.append(f"message_count = ${idx}")
        params.append(message_count)
        idx += 1

    if title is not None:
        set_clauses.append(f"title = ${idx}")
        params.append(title)
        idx += 1

    params.append(conversation_id)

    await conn.execute(
        "UPDATE conversations SET " + ", ".join(set_clauses) + f" WHERE id = ${idx}::uuid",
        *params,
    )


async def get_user_conversations_count(conn: Any, user_id: str) -> int:
    """Return total number of conversations for a user (for pagination)."""
    row = await conn.fetchrow(
        "SELECT COUNT(*) AS cnt FROM conversations WHERE user_id = $1::uuid",
        user_id,
    )
    return row["cnt"] if row else 0


async def set_conversation_feedback(
    conn: Any,
    conversation_id: UUID,
    rating: str,
    comment: str | None = None,
) -> None:
    """Store user feedback (thumbs up/down + optional comment) on a conversation."""
    await conn.execute(
        "UPDATE conversations SET user_rating = $1, user_rating_comment = $2 WHERE id = $3::uuid",
        rating,
        comment,
        conversation_id,
    )


async def delete_conversation(conn: Any, conversation_id: UUID) -> None:
    """Delete a conversation (cascades to messages via FK)."""
    await conn.execute(
        "DELETE FROM conversations WHERE id = $1::uuid",
        conversation_id,
    )
