"""
Tests for AgentService (src.agent.service).

The LangGraph graph is mocked entirely (we never compile/invoke Bedrock), so
``process_message`` is exercised by feeding it a fake async event generator that
emulates ``astream_events`` v2 output. This verifies:
  - title auto-generation on first turn
  - token / tool_start / tool_end / done event emission
  - tool-call tracking into ``tools_used``
  - two-tier persistence (_persist_turn archives user + assistant messages)
  - _load_state Redis-hit deserialization (shared with repository tests)
  - list_conversations / get_messages / delete_conversation delegation
"""

from __future__ import annotations

import os
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from src.agent.repository import add_message, create_conversation
from src.agent.service import AgentService
from src.database.connection import connection_ctx

USER_ID = "00000000-0000-0000-0000-000000000001"
TEST_PORTFOLIO = "11111111-1111-1111-1111-111111111111"


class TestProcessMessage:
    async def _run_with_events(self, svc, conversation_id, user_id, message, events):
        """Drive process_message with a mock graph emitting *events*."""

        async def _fake_stream(*args, **kwargs):
            for ev in events:
                yield ev

        svc.graph = MagicMock()
        svc.graph.astream_events = _fake_stream

        with patch.object(svc, "_run_eval_background", new=AsyncMock()):
            emitted = []
            async for ev in svc.process_message(conversation_id, user_id, message):
                emitted.append(ev)
        return emitted

    async def test_emits_token_and_done(self):
        svc = AgentService()
        cid = uuid4()
        async with connection_ctx() as conn:
            cid = await create_conversation(conn, USER_ID)

        events = [
            {"event": "on_chat_model_stream", "data": {"chunk": MagicMock(content="Hello ")}},
            {"event": "on_chat_model_stream", "data": {"chunk": MagicMock(content="world")}},
            {
                "event": "on_chain_end",
                "name": "LangGraph",
                "data": {"output": {"messages": [AIMessage(content="Hello world")]}},
            },
        ]

        emitted = await self._run_with_events(svc, cid, USER_ID, "hi", events)

        kinds = [e["event"] for e in emitted]
        assert "token" in kinds
        assert emitted[-1]["event"] == "_done"
        # tokens concatenated
        token_data = "".join(e["data"] for e in emitted if e["event"] == "token")
        assert token_data == "Hello world"

    async def test_tool_tracking(self):
        svc = AgentService()
        cid = uuid4()
        async with connection_ctx() as conn:
            cid = await create_conversation(conn, USER_ID)

        events = [
            {"event": "on_tool_start", "name": "get_portfolio_summary", "data": {}},
            {"event": "on_tool_end", "name": "get_portfolio_summary", "data": {}},
            {
                "event": "on_chain_end",
                "name": "LangGraph",
                "data": {"output": {"messages": [AIMessage(content="done")]}},
            },
        ]
        emitted = await self._run_with_events(svc, cid, USER_ID, "summary?", events)
        tool_starts = [e for e in emitted if e["event"] == "tool_start"]
        tool_ends = [e for e in emitted if e["event"] == "tool_end"]
        assert len(tool_starts) == 1
        assert tool_starts[0]["data"] == "get_portfolio_summary"
        assert len(tool_ends) == 1

    async def test_first_turn_title_autogen(self):
        svc = AgentService()
        cid = uuid4()
        async with connection_ctx() as conn:
            cid = await create_conversation(conn, USER_ID)  # no title yet

        events = [
            {
                "event": "on_chain_end",
                "name": "LangGraph",
                "data": {"output": {"messages": [AIMessage(content="ok")]}},
            },
        ]
        await self._run_with_events(svc, cid, USER_ID, "What is my portfolio worth?", events)

        async with connection_ctx() as conn:
            row = await conn.fetchrow("SELECT title FROM conversations WHERE id = $1::uuid", cid)
        # Title = first 50 chars of message; "..." only appended if >50 chars
        assert row["title"].startswith("What is my portfolio worth?")

    async def test_persist_archives_both_messages(self):
        svc = AgentService()
        cid = uuid4()
        async with connection_ctx() as conn:
            cid = await create_conversation(conn, USER_ID)

        events = [
            {"event": "on_tool_start", "name": "get_portfolio_holdings", "data": {}},
            {"event": "on_tool_end", "name": "get_portfolio_holdings", "data": {}},
            {
                "event": "on_chain_end",
                "name": "LangGraph",
                "data": {"output": {"messages": [AIMessage(content="Here are holdings")]}},
            },
        ]
        await self._run_with_events(svc, cid, USER_ID, "show me holdings", events)

        async with connection_ctx() as conn:
            rows = await conn.fetch(
                "SELECT role, content, tools_used FROM agent_conversations "
                "WHERE conversation_id = $1::uuid ORDER BY id",
                cid,
            )
        roles = [r["role"] for r in rows]
        assert "user" in roles
        assert "assistant" in roles
        assistant = [r for r in rows if r["role"] == "assistant"][0]
        assert assistant["content"] == "Here are holdings"
        # tools_used captured for the assistant message
        assert assistant["tools_used"] is not None
        assert assistant["tools_used"][0]["name"] == "get_portfolio_holdings"


class TestLoadState:
    @patch("src.agent.service.get_redis")
    async def test_redis_hit_deserializes_to_objects(self, mock_get_redis):
        svc = AgentService()
        mock_redis = AsyncMock()
        mock_redis.hget.return_value = (
            '[{"role": "system", "content": "p"}, {"role": "human", "content": "hi"}]'
        )
        mock_get_redis.return_value = mock_redis

        state = await svc._load_state(uuid4(), USER_ID)
        assert isinstance(state[0], SystemMessage)
        assert isinstance(state[1], HumanMessage)
        assert state[1].content == "hi"

    @patch("src.agent.service.get_redis")
    async def test_redis_miss_falls_to_rds(self, mock_get_redis):
        svc = AgentService()
        mock_redis = AsyncMock()
        mock_redis.hget.return_value = None
        mock_get_redis.return_value = mock_redis

        async with connection_ctx() as conn:
            cid = await create_conversation(conn, USER_ID)
            await add_message(conn, cid, USER_ID, "user", "cached miss test")

        state = await svc._load_state(cid, USER_ID)
        assert state[0].type == "system"
        assert state[-1].type == "human"
        assert state[-1].content == "cached miss test"


class TestSerializeDeserialize:
    def test_roundtrip(self):
        svc = AgentService()
        msgs = [
            SystemMessage(content="s"),
            HumanMessage(content="h"),
            AIMessage(content="a"),
        ]
        for m in msgs:
            d = svc._serialize_msg(m)
            back = AgentService._deserialize_msg(d)
            assert back.type == m.type
            assert back.content == m.content

    def test_deserialize_unknown_role_defaults_human(self):
        back = AgentService._deserialize_msg({"role": "weird", "content": "x"})
        assert isinstance(back, HumanMessage)


class TestServiceCRUD:
    async def test_list_conversations(self):
        svc = AgentService()
        async with connection_ctx() as conn:
            await create_conversation(conn, USER_ID, title="C1")
            await create_conversation(conn, USER_ID, title="C2")
        convs = await svc.list_conversations(USER_ID)
        titles = {c["title"] for c in convs}
        assert "C1" in titles and "C2" in titles

    async def test_get_messages_none_when_not_owned(self):
        svc = AgentService()
        cid = uuid4()
        # belongs to nobody we can reach
        result = await svc.get_messages(USER_ID, cid)
        assert result is None

    async def test_get_messages_returns_list(self):
        svc = AgentService()
        async with connection_ctx() as conn:
            cid = await create_conversation(conn, USER_ID)
            await add_message(conn, cid, USER_ID, "user", "hello")
        msgs = await svc.get_messages(USER_ID, cid)
        assert msgs is not None
        assert len(msgs) == 1
        assert msgs[0]["content"] == "hello"

    async def test_delete_conversation(self):
        svc = AgentService()
        async with connection_ctx() as conn:
            cid = await create_conversation(conn, USER_ID)
        deleted = await svc.delete_conversation(USER_ID, cid)
        assert deleted is True
        # second delete -> not found
        assert await svc.delete_conversation(USER_ID, cid) is False


class TestEvalSampling:
    async def test_eval_fires_when_sampled(self):
        svc = AgentService()
        cid = uuid4()
        async with connection_ctx() as conn:
            cid = await create_conversation(conn, USER_ID)

        async def _fake_stream(*args, **kwargs):
            yield {
                "event": "on_chain_end",
                "name": "LangGraph",
                "data": {"output": {"messages": [AIMessage(content="x")]}},
            }

        svc.graph = MagicMock()
        svc.graph.astream_events = _fake_stream

        with (
            patch.object(svc, "_run_eval_background", new=AsyncMock()) as mock_eval,
            patch("src.agent.service.random.random", return_value=0.0),
        ):  # < sample rate
            async for _ in svc.process_message(cid, USER_ID, "hi"):
                pass

        mock_eval.assert_awaited_once()


class TestLangSmithInit:
    """Verify LangSmith env vars are set correctly during initialize()."""

    def test_sets_env_vars(self):
        svc = AgentService()
        for k in ("LANGCHAIN_TRACING_V2", "LANGCHAIN_PROJECT", "LANGCHAIN_API_KEY"):
            os.environ.pop(k, None)

        with patch.object(svc, "graph", None):
            svc.initialize()

        assert os.environ["LANGCHAIN_TRACING_V2"] == "true"
        assert os.environ["LANGCHAIN_PROJECT"] == "stocklens-agent"
        # API key is empty by default — should not be set
        assert "LANGCHAIN_API_KEY" not in os.environ

    def test_initialize_does_not_overwrite_existing_env(self):
        svc = AgentService()
        os.environ["LANGCHAIN_PROJECT"] = "custom-project"
        with patch.object(svc, "graph", None):
            svc.initialize()
        assert os.environ["LANGCHAIN_PROJECT"] == "custom-project"

    def test_initialize_sets_api_key_when_configured(self):
        svc = AgentService()
        for k in ("LANGCHAIN_TRACING_V2", "LANGCHAIN_PROJECT", "LANGCHAIN_API_KEY"):
            os.environ.pop(k, None)
        with (
            patch.object(svc, "graph", None),
            patch("src.agent.service.settings.LANGCHAIN_API_KEY", "sk-abc123"),
        ):
            svc.initialize()
        assert os.environ.get("LANGCHAIN_API_KEY") == "sk-abc123"


class TestSummarization:
    """Tests for _summarize_old_messages and its trigger in _load_state."""

    async def test_summarize_success(self):
        svc = AgentService()
        messages = [SystemMessage(content="prompt")]
        for i in range(15):
            messages.append(HumanMessage(content=f"q{i}"))
            messages.append(AIMessage(content=f"a{i}"))

        with patch("langchain_aws.ChatBedrockConverse") as mock_bedrock:
            mock_instance = AsyncMock()
            mock_instance.ainvoke.return_value = MagicMock(
                content="Summary of earlier conversation"
            )
            mock_bedrock.return_value = mock_instance

            result = await svc._summarize_old_messages(messages, keep_last=4)

        # Should have: SystemMessage(summary) + 4 recent messages
        assert len(result) == 5
        assert isinstance(result[0], SystemMessage)
        assert "Summary of earlier conversation" in result[0].content
        assert result[-1].content == "a14"  # last AIMessage kept (15 pairs, keep_last=4)

    async def test_summarize_fallback_on_failure(self):
        svc = AgentService()
        messages = [SystemMessage(content="prompt")]
        for i in range(15):
            messages.append(HumanMessage(content=f"q{i}"))
            messages.append(AIMessage(content=f"a{i}"))

        with patch("langchain_aws.ChatBedrockConverse") as mock_bedrock:
            mock_instance = AsyncMock()
            mock_instance.ainvoke.side_effect = RuntimeError("Bedrock down")
            mock_bedrock.return_value = mock_instance

            result = await svc._summarize_old_messages(messages, keep_last=4)

        # Fallback: drops oldest, keeps recent + prompt with omission notice
        assert len(result) == 5
        assert isinstance(result[0], SystemMessage)
        assert "dropped" in result[0].content

    async def test_load_state_triggers_summarization(self):
        """_load_state should summarise when RDS returns more than AGENT_MAX_HISTORY_TURNS."""
        svc = AgentService()
        async with connection_ctx() as conn:
            cid = await create_conversation(conn, USER_ID)
            # Insert 15 turns (30 messages) — exceeds AGENT_MAX_HISTORY_TURNS=20,
            # and is under the 2× limit (40) now passed to get_conversation_messages
            for i in range(15):
                await add_message(conn, cid, USER_ID, "user", f"q{i}")
                await add_message(conn, cid, USER_ID, "assistant", f"a{i}")

        with (
            patch("src.agent.service.get_redis") as mock_get_redis,
            patch.object(AgentService, "_summarize_old_messages") as mock_summarize,
        ):
            mock_redis = AsyncMock()
            mock_redis.hget.return_value = None  # Redis miss → RDS fallback
            mock_get_redis.return_value = mock_redis
            mock_summarize.return_value = [SystemMessage(content="summarised")]

            state = await svc._load_state(cid, USER_ID)

        mock_summarize.assert_awaited_once()
        assert len(state) == 1


class TestSystemPrompt:
    """Verify PERSONA_PROMPT contains key directives."""

    def test_contains_core_rules(self):
        from src.agent.service import PERSONA_PROMPT

        assert "Answer ONLY from the data" in PERSONA_PROMPT
        assert "Never execute trades" in PERSONA_PROMPT
        assert "round to 2 decimal places" in PERSONA_PROMPT
        assert "call them one at a time" in PERSONA_PROMPT
        assert "politely decline" in PERSONA_PROMPT

    def test_contains_examples(self):
        from src.agent.service import PERSONA_PROMPT

        assert "get_portfolio_summary" in PERSONA_PROMPT
        assert "get_lstm_forecast" in PERSONA_PROMPT
        assert "I cannot execute trades" in PERSONA_PROMPT
