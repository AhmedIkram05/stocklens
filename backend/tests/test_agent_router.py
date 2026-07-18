"""
Tests for the agent router (src.agent.router).

* POST   /agent/chat               — SSE streaming
* GET    /agent/conversations       — conversation list
* GET    /agent/conversations/{id}  — conversation details
* DELETE /agent/conversations/{id}  — conversation deletion

``agent_service.process_message`` is patched with a fake event generator to
keep tests fast and avoid compiling the LangGraph graph.  All DB operations
run inside the per-test transaction from ``conftest._test_db``.
"""

from __future__ import annotations

import json
from unittest.mock import patch

import httpx
import jwt as pyjwt

from src.agent import repository as agent_repo
from src.agent.service import agent_service
from src.database.connection import connection_ctx

# ── Helpers ─────────────────────────────────────────────────────────────────


def _user_id_from_token(auth_headers: dict[str, str]) -> str:
    """Extract the ``sub`` claim (user_id) from the Bearer token."""
    token = auth_headers["Authorization"].replace("Bearer ", "")
    payload = pyjwt.decode(token, options={"verify_signature": False})
    return payload["sub"]


def _parse_sse(text: str) -> list[dict]:
    """Parse a raw SSE response body into ``[{event, data}, ...]``."""
    results: list[dict] = []
    for block in text.strip().split("\n\n"):
        block = block.strip()
        if not block:
            continue
        event = ""
        data = ""
        for line in block.split("\n"):
            if line.startswith("event: "):
                event = line[7:]
            elif line.startswith("data: "):
                data = line[6:]
        if event or data:
            results.append({"event": event, "data": data})
    return results


def _fake_generator(events: list[dict]):
    """Return an async generator function that yields *events*."""

    async def _fake(
        conversation_id,  # noqa: ANN401
        user_id,  # noqa: ANN401
        message,  # noqa: ANN401
    ):
        for ev in events:
            yield ev

    return _fake


# ── POST /agent/chat ────────────────────────────────────────────────────────


class TestChatEndpoint:
    """POST /agent/chat — SSE streaming."""

    # ------------------------------------------------------------------
    # Happy path — new conversation
    # ------------------------------------------------------------------

    async def test_new_conversation_emits_sse_events(
        self,
        client: httpx.AsyncClient,
        auth_headers: dict[str, str],
    ):
        events = [
            {"event": "token", "data": "Hello "},
            {"event": "token", "data": "world"},
        ]
        fake = _fake_generator(events)

        with patch.object(agent_service, "process_message", fake):
            resp = await client.post(
                "/agent/chat",
                json={"message": "Hi"},
                headers=auth_headers,
            )

        assert resp.status_code == 200
        assert resp.headers.get("content-type", "").startswith("text/event-stream")

        sse = _parse_sse(resp.text)
        # process_message yields 2 events (token, token).
        # The router then yields its own done with conversation_id + full_response.
        assert len(sse) == 3

        assert sse[0]["event"] == "token"
        assert json.loads(sse[0]["data"]) == "Hello "
        assert sse[1]["event"] == "token"
        assert json.loads(sse[1]["data"]) == "world"

        assert sse[2]["event"] == "done"  # router-level done (enriched)
        done_data = json.loads(sse[2]["data"])
        assert "conversation_id" in done_data
        assert done_data["full_response"] == "Hello world"

    async def test_new_conversation_creates_db_row(
        self,
        client: httpx.AsyncClient,
        auth_headers: dict[str, str],
    ):
        """Verify a new conversation row is created in the DB."""
        fake = _fake_generator(
            [
                {"event": "token", "data": "hi"},
                {"event": "done", "data": ""},
            ]
        )
        with patch.object(agent_service, "process_message", fake):
            resp = await client.post(
                "/agent/chat",
                json={"message": "First chat"},
                headers=auth_headers,
            )

        sse = _parse_sse(resp.text)
        done_data = json.loads(sse[-1]["data"])
        cid = done_data["conversation_id"]

        uid = _user_id_from_token(auth_headers)
        async with connection_ctx() as conn:
            conv = await agent_repo.get_conversation(conn, cid, uid)
        assert conv is not None, "Conversation should exist in DB"

    # ------------------------------------------------------------------
    # Happy path — existing conversation
    # ------------------------------------------------------------------

    async def test_existing_conversation_resumes(
        self,
        client: httpx.AsyncClient,
        auth_headers: dict[str, str],
    ):
        """Sending a message to an existing conversation returns 200."""
        fake = _fake_generator(
            [
                {"event": "token", "data": "First"},
                {"event": "done", "data": ""},
            ]
        )
        with patch.object(agent_service, "process_message", fake):
            resp1 = await client.post(
                "/agent/chat",
                json={"message": "First"},
                headers=auth_headers,
            )
        cid = json.loads(_parse_sse(resp1.text)[-1]["data"])["conversation_id"]

        fake2 = _fake_generator(
            [
                {"event": "token", "data": "Second"},
                {"event": "done", "data": ""},
            ]
        )
        with patch.object(agent_service, "process_message", fake2):
            resp2 = await client.post(
                "/agent/chat",
                json={"message": "Second", "conversation_id": cid},
                headers=auth_headers,
            )

        assert resp2.status_code == 200
        done2 = json.loads(_parse_sse(resp2.text)[-1]["data"])
        assert done2["conversation_id"] == cid
        assert done2["full_response"] == "Second"

    # ------------------------------------------------------------------
    # Error cases
    # ------------------------------------------------------------------

    async def test_nonexistent_conversation_404(
        self,
        client: httpx.AsyncClient,
        auth_headers: dict[str, str],
    ):
        resp = await client.post(
            "/agent/chat",
            json={
                "message": "Hi",
                "conversation_id": "00000000-0000-0000-0000-000000000000",
            },
            headers=auth_headers,
        )
        assert resp.status_code == 404
        assert "not found" in resp.text.lower()

    async def test_no_auth_401(
        self,
        client: httpx.AsyncClient,
    ):
        resp = await client.post(
            "/agent/chat",
            json={"message": "Hi"},
        )
        assert resp.status_code == 401

    # ------------------------------------------------------------------
    # SSE event types
    # ------------------------------------------------------------------

    async def test_tool_start_end_events(
        self,
        client: httpx.AsyncClient,
        auth_headers: dict[str, str],
    ):
        events = [
            {"event": "tool_start", "data": "get_portfolio_summary"},
            {"event": "tool_end", "data": "get_portfolio_summary"},
            {"event": "token", "data": "Here is your portfolio."},
        ]
        fake = _fake_generator(events)
        with patch.object(agent_service, "process_message", fake):
            resp = await client.post(
                "/agent/chat",
                json={"message": "Portfolio?"},
                headers=auth_headers,
            )

        sse = _parse_sse(resp.text)
        # 3 from service (tool_start, tool_end, token) + 1 from router (done)
        assert len(sse) == 4
        assert sse[0]["event"] == "tool_start"
        assert json.loads(sse[0]["data"]) == "get_portfolio_summary"
        assert sse[1]["event"] == "tool_end"
        assert json.loads(sse[1]["data"]) == "get_portfolio_summary"
        assert sse[3]["event"] == "done"
        assert "conversation_id" in json.loads(sse[3]["data"])

    async def test_stream_error_emits_error_event(
        self,
        client: httpx.AsyncClient,
        auth_headers: dict[str, str],
    ):
        """When the generator raises, the router yields an 'error' event."""

        async def _crashy_gen(conversation_id, user_id, message):
            yield {"event": "token", "data": "partial "}
            raise RuntimeError("simulated crash")

        with patch.object(agent_service, "process_message", _crashy_gen):
            resp = await client.post(
                "/agent/chat",
                json={"message": "crash me"},
                headers=auth_headers,
            )

        assert resp.status_code == 200  # SSE always returns 200
        sse = _parse_sse(resp.text)
        assert sse[-1]["event"] == "error"
        err_data = json.loads(sse[-1]["data"])
        assert "error" in err_data

    async def test_headers_are_correct(
        self,
        client: httpx.AsyncClient,
        auth_headers: dict[str, str],
    ):
        fake = _fake_generator([{"event": "done", "data": ""}])
        with patch.object(agent_service, "process_message", fake):
            resp = await client.post(
                "/agent/chat",
                json={"message": "headers test"},
                headers=auth_headers,
            )

        assert resp.headers.get("cache-control") == "no-cache"
        assert resp.headers.get("x-accel-buffering") == "no"


# ── GET /agent/conversations ────────────────────────────────────────────────


class TestListConversations:
    """GET /agent/conversations."""

    async def test_empty(
        self,
        client: httpx.AsyncClient,
        auth_headers: dict[str, str],
    ):
        resp = await client.get("/agent/conversations", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json() == {"conversations": [], "total": 0}

    async def test_returns_user_conversations(
        self,
        client: httpx.AsyncClient,
        auth_headers: dict[str, str],
    ):
        uid = _user_id_from_token(auth_headers)
        async with connection_ctx() as conn:
            await agent_repo.create_conversation(conn, uid, title="Chat A")
            await agent_repo.create_conversation(conn, uid, title="Chat B")

        resp = await client.get("/agent/conversations", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["conversations"]) == 2
        assert data["total"] == 2
        titles = {c["title"] for c in data["conversations"]}
        assert titles == {"Chat A", "Chat B"}

    async def test_pagination(
        self,
        client: httpx.AsyncClient,
        auth_headers: dict[str, str],
    ):
        uid = _user_id_from_token(auth_headers)
        async with connection_ctx() as conn:
            for i in range(5):
                await agent_repo.create_conversation(conn, uid, title=f"Chat {i}")

        resp = await client.get(
            "/agent/conversations?limit=2&offset=0",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["conversations"]) == 2
        assert data["total"] == 5

    async def test_other_user_not_visible(
        self,
        client: httpx.AsyncClient,
        auth_headers: dict[str, str],
    ):
        """Conversations belonging to another user are not returned."""
        uid = _user_id_from_token(auth_headers)
        async with connection_ctx() as conn:
            await agent_repo.create_conversation(conn, uid, title="Mine")

        # Register a second user
        reg = await client.post(
            "/auth/register",
            json={
                "email": "other-list@test.com",
                "password": "OtherPass123!",
                "full_name": "Other",
            },
        )
        other_headers = {"Authorization": f"Bearer {reg.json()['tokens']['access_token']}"}

        resp = await client.get("/agent/conversations", headers=other_headers)
        assert resp.status_code == 200
        assert resp.json() == {"conversations": [], "total": 0}

    async def test_no_auth_401(
        self,
        client: httpx.AsyncClient,
    ):
        resp = await client.get("/agent/conversations")
        assert resp.status_code == 401

    async def test_default_limit_offset(
        self,
        client: httpx.AsyncClient,
        auth_headers: dict[str, str],
    ):
        """Default limit and offset should be 20 and 0."""
        uid = _user_id_from_token(auth_headers)
        async with connection_ctx() as conn:
            await agent_repo.create_conversation(conn, uid, title="Default")

        resp = await client.get("/agent/conversations", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["conversations"]) == 1


# ── GET /agent/conversations/{id} ───────────────────────────────────────────


class TestGetConversation:
    """GET /agent/conversations/{conversation_id}."""

    async def _setup(self, auth_headers: dict[str, str]):
        """Create a conversation with 2 messages for the authenticated user.
        Returns the UUID.
        """
        uid = _user_id_from_token(auth_headers)
        async with connection_ctx() as conn:
            cid = await agent_repo.create_conversation(conn, uid, title="Detail")
            await agent_repo.add_message(conn, cid, uid, "user", "Hello")
            await agent_repo.add_message(conn, cid, uid, "assistant", "World")
        return cid

    async def test_returns_conversation_and_messages(
        self,
        client: httpx.AsyncClient,
        auth_headers: dict[str, str],
    ):
        cid = await self._setup(auth_headers)
        resp = await client.get(f"/agent/conversations/{cid}", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["conversation"]["title"] == "Detail"
        assert len(data["messages"]) == 2
        assert data["messages"][0]["role"] == "user"
        assert data["messages"][0]["content"] == "Hello"
        assert data["messages"][1]["role"] == "assistant"
        assert data["messages"][1]["content"] == "World"

    async def test_not_found_404(
        self,
        client: httpx.AsyncClient,
        auth_headers: dict[str, str],
    ):
        resp = await client.get(
            "/agent/conversations/00000000-0000-0000-0000-000000000000",
            headers=auth_headers,
        )
        assert resp.status_code == 404

    async def test_other_user_404(
        self,
        client: httpx.AsyncClient,
        auth_headers: dict[str, str],
    ):
        cid = await self._setup(auth_headers)

        reg = await client.post(
            "/auth/register",
            json={
                "email": "other-get@test.com",
                "password": "OtherPass123!",
                "full_name": "Other",
            },
        )
        other_headers = {"Authorization": f"Bearer {reg.json()['tokens']['access_token']}"}

        resp = await client.get(f"/agent/conversations/{cid}", headers=other_headers)
        assert resp.status_code == 404

    async def test_no_auth_401(
        self,
        client: httpx.AsyncClient,
    ):
        resp = await client.get(
            "/agent/conversations/00000000-0000-0000-0000-000000000000",
        )
        assert resp.status_code == 401


# ── DELETE /agent/conversations/{id} ────────────────────────────────────────


class TestDeleteConversation:
    """DELETE /agent/conversations/{conversation_id}."""

    async def _setup(self, auth_headers: dict[str, str]):
        """Create a conversation with 1 message for the authenticated user.
        Returns the UUID.
        """
        uid = _user_id_from_token(auth_headers)
        async with connection_ctx() as conn:
            cid = await agent_repo.create_conversation(conn, uid, title="Remove")
            await agent_repo.add_message(conn, cid, uid, "user", "bye")
        return cid

    async def test_delete_204(
        self,
        client: httpx.AsyncClient,
        auth_headers: dict[str, str],
    ):
        cid = await self._setup(auth_headers)
        resp = await client.delete(
            f"/agent/conversations/{cid}",
            headers=auth_headers,
        )
        assert resp.status_code == 204

        # Verify it is gone
        uid = _user_id_from_token(auth_headers)
        async with connection_ctx() as conn:
            assert await agent_repo.get_conversation(conn, cid, uid) is None

    async def test_delete_not_found_404(
        self,
        client: httpx.AsyncClient,
        auth_headers: dict[str, str],
    ):
        resp = await client.delete(
            "/agent/conversations/00000000-0000-0000-0000-000000000000",
            headers=auth_headers,
        )
        assert resp.status_code == 404

    async def test_delete_other_user_404(
        self,
        client: httpx.AsyncClient,
        auth_headers: dict[str, str],
    ):
        cid = await self._setup(auth_headers)

        reg = await client.post(
            "/auth/register",
            json={
                "email": "other-del@test.com",
                "password": "OtherPass123!",
                "full_name": "Other",
            },
        )
        other_headers = {"Authorization": f"Bearer {reg.json()['tokens']['access_token']}"}

        resp = await client.delete(
            f"/agent/conversations/{cid}",
            headers=other_headers,
        )
        assert resp.status_code == 404

    async def test_no_auth_401(
        self,
        client: httpx.AsyncClient,
    ):
        resp = await client.delete(
            "/agent/conversations/00000000-0000-0000-0000-000000000000",
        )
        assert resp.status_code == 401

    async def test_delete_cascades_messages(
        self,
        client: httpx.AsyncClient,
        auth_headers: dict[str, str],
    ):
        """Messages should be removed when the conversation is deleted."""
        uid = _user_id_from_token(auth_headers)
        async with connection_ctx() as conn:
            cid = await agent_repo.create_conversation(conn, uid, title="Cascade")
            await agent_repo.add_message(conn, cid, uid, "user", "msg1")
            await agent_repo.add_message(conn, cid, uid, "assistant", "msg2")

        await client.delete(f"/agent/conversations/{cid}", headers=auth_headers)

        async with connection_ctx() as conn:
            msgs = await agent_repo.get_conversation_messages(conn, cid)
        assert msgs == []
