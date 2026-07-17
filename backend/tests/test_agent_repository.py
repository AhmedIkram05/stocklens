"""
Tests for agent repository (src.agent.repository).

Uses real database via ``connection_ctx()`` with per-test transaction rollback.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch
from uuid import UUID, uuid4

from src.agent.repository import (
    add_message,
    create_conversation,
    delete_conversation,
    get_conversation,
    get_conversation_messages,
    get_user_conversations,
    update_conversation_metadata,
)
from src.database.connection import connection_ctx

USER_ID = "00000000-0000-0000-0000-000000000001"


class TestCreateConversation:
    async def test_create_basic(self):
        cid = await create_conversation(conn=await connection_ctx().__aenter__(), user_id=USER_ID)
        assert isinstance(cid, UUID)

    async def test_create_with_title(self):
        async with connection_ctx() as conn:
            cid = await create_conversation(conn, user_id=USER_ID, title="My Chat")
            row = await conn.fetchrow("SELECT title FROM conversations WHERE id = $1::uuid", cid)
            assert row["title"] == "My Chat"


class TestGetConversation:
    async def test_get_existing(self):
        async with connection_ctx() as conn:
            cid = await create_conversation(conn, user_id=USER_ID)
            conv = await get_conversation(conn, cid, user_id=USER_ID)
            assert conv is not None
            assert str(conv["id"]) == str(cid)
            assert conv["user_id"] == USER_ID

    async def test_get_not_found(self):
        async with connection_ctx() as conn:
            conv = await get_conversation(conn, uuid4(), user_id=USER_ID)
            assert conv is None

    async def test_get_not_owned(self):
        """A conversation owned by another user should not be visible."""
        async with connection_ctx() as conn:
            cid = await create_conversation(conn, user_id="00000000-0000-0000-0000-000000000002")
            conv = await get_conversation(conn, cid, user_id=USER_ID)
            assert conv is None


class TestAddMessage:
    async def test_add_user_message(self):
        async with connection_ctx() as conn:
            cid = await create_conversation(conn, user_id=USER_ID)
            mid = await add_message(conn, cid, USER_ID, "user", "Hello")
            assert isinstance(mid, int)
            assert mid > 0

    async def test_add_assistant_message_with_tools(self):
        async with connection_ctx() as conn:
            cid = await create_conversation(conn, user_id=USER_ID)
            tools = [{"name": "get_portfolio_summary", "status": "completed"}]
            mid = await add_message(
                conn, cid, USER_ID, "assistant", "Here is your portfolio.", tools_used=tools
            )
            row = await conn.fetchrow(
                "SELECT content, tools_used FROM agent_conversations WHERE id = $1",
                mid,
            )
            assert row["content"] == "Here is your portfolio."
            assert row["tools_used"] == tools


class TestGetMessages:
    async def test_get_empty_conversation(self):
        async with connection_ctx() as conn:
            cid = await create_conversation(conn, user_id=USER_ID)
            msgs = await get_conversation_messages(conn, cid)
            assert msgs == []

    async def test_get_messages_in_order(self):
        async with connection_ctx() as conn:
            cid = await create_conversation(conn, user_id=USER_ID)
            await add_message(conn, cid, USER_ID, "user", "First")
            await add_message(conn, cid, USER_ID, "assistant", "Response")
            await add_message(conn, cid, USER_ID, "user", "Second")

            msgs = await get_conversation_messages(conn, cid)
            assert len(msgs) == 3
            assert msgs[0]["role"] == "user"
            assert msgs[0]["content"] == "First"
            assert msgs[1]["role"] == "assistant"
            assert msgs[1]["content"] == "Response"
            assert msgs[2]["role"] == "user"
            assert msgs[2]["content"] == "Second"


class TestUserConversations:
    async def test_list_user_conversations(self):
        async with connection_ctx() as conn:
            c1 = await create_conversation(conn, USER_ID, title="Chat 1")
            c2 = await create_conversation(conn, USER_ID, title="Chat 2")

            convs = await get_user_conversations(conn, USER_ID)
            ids = {c["id"] for c in convs}
            assert str(c1) in ids
            assert str(c2) in ids

    async def test_pagination(self):
        async with connection_ctx() as conn:
            for i in range(5):
                await create_conversation(conn, USER_ID, title=f"Chat {i}")

            page1 = await get_user_conversations(conn, USER_ID, limit=2, offset=0)
            page2 = await get_user_conversations(conn, USER_ID, limit=2, offset=2)
            assert len(page1) == 2
            assert len(page2) == 2
            # Most recent first — ids should differ between pages
            assert page1[0]["id"] != page2[0]["id"]


class TestUpdateMetadata:
    async def test_update_message_count(self):
        async with connection_ctx() as conn:
            cid = await create_conversation(conn, USER_ID)
            await update_conversation_metadata(conn, cid, message_count=5)
            row = await conn.fetchrow(
                "SELECT message_count FROM conversations WHERE id = $1::uuid", cid
            )
            assert row["message_count"] == 5

    async def test_update_title(self):
        async with connection_ctx() as conn:
            cid = await create_conversation(conn, USER_ID)
            await update_conversation_metadata(conn, cid, title="Renamed Chat")
            row = await conn.fetchrow("SELECT title FROM conversations WHERE id = $1::uuid", cid)
            assert row["title"] == "Renamed Chat"


class TestDeleteConversation:
    async def test_delete_exists(self):
        async with connection_ctx() as conn:
            cid = await create_conversation(conn, USER_ID)
            await add_message(conn, cid, USER_ID, "user", "Hello")
            await delete_conversation(conn, cid)

            conv = await get_conversation(conn, cid, USER_ID)
            assert conv is None

            # Cascade should remove messages too
            msgs = await get_conversation_messages(conn, cid)
            assert msgs == []


class TestIntegration:
    """Full conversation lifecycle."""

    async def test_full_lifecycle(self):
        async with connection_ctx() as conn:
            # Create
            cid = await create_conversation(conn, USER_ID, title="Lifecycle Test")
            assert cid is not None

            # Add messages
            await add_message(conn, cid, USER_ID, "user", "What are my holdings?")
            await add_message(
                conn,
                cid,
                USER_ID,
                "assistant",
                "Here are your holdings...",
                tools_used=[{"name": "get_portfolio_holdings", "status": "completed"}],
            )

            # Read messages
            msgs = await get_conversation_messages(conn, cid)
            assert len(msgs) == 2
            assert msgs[0]["role"] == "user"
            assert msgs[1]["role"] == "assistant"
            assert msgs[1]["tools_used"] is not None

            # Update metadata
            await update_conversation_metadata(conn, cid, message_count=2)

            # Verify in user's list
            convs = await get_user_conversations(conn, USER_ID)
            assert any(str(c["id"]) == str(cid) for c in convs)

            # Delete
            await delete_conversation(conn, cid)
            conv = await get_conversation(conn, cid, USER_ID)
            assert conv is None


class TestRedisRoundtrip:
    """AgentService._load_state Redis roundtrip.

    Verifies that:
    1. When Redis has cached state, _load_state returns it directly.
    2. When Redis is empty, _load_state falls back to RDS.
    """

    @patch("src.agent.service.get_redis")
    async def test_load_from_redis_hit(self, mock_get_redis):
        """_load_state returns cached state deserialized into message objects."""
        from langchain_core.messages import HumanMessage, SystemMessage

        from src.agent.service import AgentService

        svc = AgentService()
        mock_redis = AsyncMock()
        mock_redis.hget.return_value = (
            '[{"role": "system", "content": "prompt"}, {"role": "human", "content": "Hello"}]'
        )
        mock_get_redis.return_value = mock_redis
        cid = "00000000-0000-0000-0000-000000000001"

        state = await svc._load_state(cid, USER_ID)

        # Should return LangChain message objects (not dicts)
        assert isinstance(state, list)
        assert len(state) == 2
        assert isinstance(state[0], SystemMessage)
        assert isinstance(state[1], HumanMessage)
        assert state[1].content == "Hello"
        mock_redis.hget.assert_awaited_once()

    @patch("src.agent.service.get_redis")
    async def test_load_from_redis_assistant_deserializes(self, mock_get_redis):
        """Redis dicts with role='assistant' become AIMessage objects."""
        from langchain_core.messages import AIMessage

        from src.agent.service import AgentService

        svc = AgentService()
        mock_redis = AsyncMock()
        mock_redis.hget.return_value = '[{"role": "assistant", "content": "Hi there"}]'
        mock_get_redis.return_value = mock_redis

        state = await svc._load_state("00000000-0000-0000-0000-000000000001", USER_ID)
        assert len(state) == 1
        assert isinstance(state[0], AIMessage)
        assert state[0].content == "Hi there"

    @patch("src.agent.service.get_redis")
    async def test_load_from_redis_empty_falls_to_rds(self, mock_get_redis):
        """_load_state falls back to RDS when Redis returns None."""
        from src.agent.service import AgentService

        svc = AgentService()
        mock_redis = AsyncMock()
        mock_redis.hget.return_value = None  # Redis miss
        mock_get_redis.return_value = mock_redis

        # Create a conversation + message in real DB so RDS fallback finds data
        async with connection_ctx() as conn:
            cid = await create_conversation(conn, USER_ID)
            await add_message(conn, cid, USER_ID, "user", "Test message")

        state = await svc._load_state(cid, USER_ID)

        # Should return LangChain message objects from RDS (not dicts)
        assert isinstance(state, list)
        assert len(state) >= 1  # SystemMessage + at least one HumanMessage
        # First item should be the persona SystemMessage
        assert hasattr(state[0], "type")
        assert state[0].type == "system"
        # Second item should be the user message from DB
        assert state[-1].type == "human"
        assert state[-1].content == "Test message"
