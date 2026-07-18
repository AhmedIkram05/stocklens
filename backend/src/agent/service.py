"""
AgentService — orchestrates the LangGraph ReAct agent with two-tier persistence.

Tier 1 — Redis: stores active session state (configurable TTL per settings).
Tier 2 — PostgreSQL: persists every user/assistant message to the
``agent_conversations`` table for long-term history.
"""

from __future__ import annotations

import asyncio
import json
import random
from collections.abc import AsyncGenerator
from uuid import UUID

import structlog
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from src.agent import repository as agent_repo
from src.agent.graph import create_agent_graph
from src.agent.tools import get_all_tools
from src.cache.redis import get_redis
from src.config import settings
from src.database.connection import connection_ctx

logger = structlog.get_logger()

# ── Persona prompt ────────────────────────────────────────────────────────

PERSONA_PROMPT = """\
You are a professional financial analysis assistant. You help users understand
their portfolio, spending, and market data.

Rules:
1. Answer ONLY from the data returned by your tools. Never invent numbers, prices, or ticker data.
2. If a tool fails or returns no data, say so clearly and provide whatever partial answer you can.
3. Cite your sources where possible (e.g., "According to your portfolio data...").
4. If asked about something outside your capabilities, explain what you cannot do.
5. Never execute trades or modify portfolios. Analyze only — no actions on the user's behalf.
6. Keep responses concise and professional. Use bullet points for multiple data points.
7. If the user asks about a ticker or portfolio you don't have access to, say so.
"""


class AgentService:
    """Manages agent lifecycle, invocation, and persistence."""

    def __init__(self) -> None:
        self.graph = None  # Compiled graph — set by initialize()
        self._eval_tasks: set[asyncio.Task] = set()  # Strong refs to prevent GC

    # ── Initialisation ──────────────────────────────────────────────────

    def initialize(self) -> None:
        """Load tools, compile graph. Called once at app startup (sync)."""
        if self.graph is not None:
            return
        tools = get_all_tools()
        graph = create_agent_graph(tools)
        # No checkpointer — custom two-tier persistence handles state
        self.graph = graph.compile()
        logger.info("agent_graph_compiled", tool_count=len(tools))

    # ── State management ─────────────────────────────────────────────────

    async def _load_state(self, conversation_id: UUID, user_id: str) -> list:
        """Load conversation state — try Redis (hot), fall back to RDS (cold).

        Returns list of BaseMessage-compatible objects for graph input.
        """
        redis_key = f"{settings.AGENT_REDIS_KEY_PREFIX}{conversation_id}"

        # Tier 1: Redis (hot)
        try:
            redis = await get_redis()
            state_json = await redis.hget(redis_key, "state")
            if state_json:
                raw = json.loads(state_json)
                # Normalize stored dicts back into BaseMessage objects so
                # downstream code can rely on .type / .content consistently.
                return [self._deserialize_msg(m) if isinstance(m, dict) else m for m in raw]
        except Exception:
            pass  # Fall through to RDS

        # Tier 2: RDS (cold) — build from archived messages
        async with connection_ctx() as conn:
            rows = await agent_repo.get_conversation_messages(
                conn,
                conversation_id,
                settings.AGENT_MAX_HISTORY_TURNS,
            )

        state: list = [SystemMessage(content=PERSONA_PROMPT)]
        for row in rows:
            if row["role"] == "user":
                state.append(HumanMessage(content=row["content"]))
            elif row["role"] == "assistant":
                state.append(AIMessage(content=row["content"]))

        # Seed Redis with loaded state
        try:
            redis = await get_redis()
            serialized = [self._serialize_msg(m) for m in state]
            await redis.hset(
                redis_key,
                mapping={
                    "state": json.dumps(serialized),
                    "user_id": str(user_id),
                    "message_count": len(rows),
                    "updated_at": "now",
                },
            )
            await redis.expire(redis_key, settings.AGENT_REDIS_TTL)
        except Exception:
            pass  # Non-critical — state works from RDS alone

        return state

    def _serialize_msg(self, msg) -> dict:
        """Serialize a LangChain BaseMessage for JSON storage."""
        return {"role": msg.type, "content": msg.content}

    @staticmethod
    def _deserialize_msg(d: dict):
        """Rebuild a LangChain BaseMessage from a stored dict.

        Accepts both LangChain's internal ``.type`` values (``human`` /
        ``ai`` / ``system``) and the canonical API roles (``user`` /
        ``assistant`` / ``system``) so the roundtrip is lossless regardless
        of which form ``_serialize_msg`` stored.
        """
        role = (d.get("role") or "").lower()
        content = d.get("content", "")
        if role in ("user", "human"):
            return HumanMessage(content=content)
        if role in ("assistant", "ai"):
            return AIMessage(content=content)
        if role == "system":
            return SystemMessage(content=content)
        return HumanMessage(content=content)

    async def _persist_turn(
        self,
        conversation_id: UUID,
        user_id: str,
        user_message: str,
        final_state: dict,
        tools_used: list | None = None,
    ) -> None:
        """After graph completes: persist to both tiers.

        Tier 1 (Redis) — update active session state, refresh TTL.
        Tier 2 (RDS) — archive user message + assistant response.
        """
        redis_key = f"{settings.AGENT_REDIS_KEY_PREFIX}{conversation_id}"

        async with connection_ctx() as conn:
            # Archive user message
            await agent_repo.add_message(
                conn,
                conversation_id,
                user_id,
                "user",
                user_message,
            )

            # Extract final assistant response
            last_msg = final_state.get("messages", [None])[-1]
            if last_msg:
                response_text = last_msg.content if hasattr(last_msg, "content") else str(last_msg)
                await agent_repo.add_message(
                    conn,
                    conversation_id,
                    user_id,
                    "assistant",
                    response_text,
                    tools_used=tools_used,
                )

            # Update conversation metadata
            await agent_repo.update_conversation_metadata(conn, conversation_id)

        # Refresh Redis state
        try:
            redis = await get_redis()
            async with connection_ctx() as conn:
                rows = await agent_repo.get_conversation_messages(
                    conn,
                    conversation_id,
                    settings.AGENT_MAX_HISTORY_TURNS,
                )
            state: list = [SystemMessage(content=PERSONA_PROMPT)]
            for row in rows:
                if row["role"] == "user":
                    state.append(HumanMessage(content=row["content"]))
                elif row["role"] == "assistant":
                    state.append(AIMessage(content=row["content"]))

            serialized = [self._serialize_msg(m) for m in state]
            await redis.hset(
                redis_key,
                mapping={
                    "state": json.dumps(serialized),
                    "user_id": str(user_id),
                    "message_count": len(rows),
                    "updated_at": "now",
                },
            )
            await redis.expire(redis_key, settings.AGENT_REDIS_TTL)
        except Exception:
            pass  # Redis miss is OK — next turn loads from RDS

    # ── Evaluation ───────────────────────────────────────────────────────

    async def _run_eval_background(
        self,
        conversation_id: UUID,
        user_id: str,
        question: str,
        response_text: str,
        tools_used: list | None = None,
    ) -> None:
        """Fire-and-forget LLM-as-Judge evaluation. Stub — evaluator created in R5."""
        try:
            from src.agent.evaluator import run_evaluation  # noqa: PLC0415
        except ImportError:
            return  # Evaluator module not available until R5

        task = asyncio.create_task(
            run_evaluation(conversation_id, user_id, question, response_text, tools_used),
        )
        self._eval_tasks.add(task)
        task.add_done_callback(self._eval_tasks.discard)

    # ── Chat ─────────────────────────────────────────────────────────────

    async def process_message(
        self,
        conversation_id: UUID,
        user_id: str,
        message: str,
    ) -> AsyncGenerator[dict, None]:
        """Run the agent graph with two-tier state management.

        Yields SSE-compatible event dicts for the router::

            {"event": "token",      "data": "partial text"}
            {"event": "tool_start", "data": "tool_name"}
            {"event": "tool_end",   "data": "tool_name"}
            {"event": "done",       "data": ""}
        """
        # Load state (Redis -> RDS fallback)
        state = await self._load_state(conversation_id, user_id)

        # Title auto-generation on first turn
        if len(state) == 1:  # only system prompt — first message
            async with connection_ctx() as conn:
                conv = await agent_repo.get_conversation(conn, conversation_id, user_id)
                if conv and conv.get("title") is None:
                    title = message[:50] + ("..." if len(message) > 50 else "")
                    await agent_repo.update_conversation_metadata(
                        conn,
                        conversation_id,
                        title=title,
                    )

        # Append current message
        state.append(HumanMessage(content=message))

        # Build graph input
        graph_input = {"messages": state, "user_id": user_id}
        config = {"configurable": {"thread_id": str(conversation_id)}}

        # Track tool calls for persistence
        tools_used: list[dict] = []

        async for event in self.graph.astream_events(
            graph_input,
            config,
            version="v2",
        ):
            kind = event["event"]
            if kind == "on_chat_model_stream":
                chunk = event["data"]["chunk"]
                if hasattr(chunk, "content") and chunk.content:
                    yield {"event": "token", "data": chunk.content}
            elif kind == "on_tool_start":
                tools_used.append(
                    {
                        "name": event.get("name", "unknown"),
                        "status": "started",
                    }
                )
                yield {"event": "tool_start", "data": event.get("name", "unknown")}
            elif kind == "on_tool_end":
                for t in tools_used:
                    if t.get("name") == event.get("name") and t.get("status") == "started":
                        t["status"] = "completed"
                yield {"event": "tool_end", "data": event.get("name", "unknown")}
            elif kind == "on_chain_end" and event.get("name") == "LangGraph":
                final_state = event["data"]["output"]
                await self._persist_turn(
                    conversation_id,
                    user_id,
                    message,
                    final_state,
                    tools_used,
                )
                # Fire-and-forget evaluation sampling
                if random.random() < settings.AGENT_EVAL_SAMPLE_RATE:
                    last_content = ""
                    if final_state.get("messages"):
                        last_msg = final_state["messages"][-1]
                        if hasattr(last_msg, "content"):
                            last_content = last_msg.content
                    await self._run_eval_background(
                        conversation_id,
                        user_id,
                        message,
                        last_content,
                        tools_used,
                    )

    # ── Conversation CRUD (shared with router) ──────────────────────────

    async def list_conversations(
        self,
        user_id: str,
        limit: int = 20,
        offset: int = 0,
    ) -> list[dict]:
        """Return the user's conversation list."""
        async with connection_ctx() as conn:
            return await agent_repo.get_user_conversations(conn, user_id, limit, offset)

    async def get_messages(
        self,
        user_id: str,
        conversation_id: UUID,
    ) -> list[dict] | None:
        """Return messages for a conversation (None = not found/not owned)."""
        async with connection_ctx() as conn:
            conv = await agent_repo.get_conversation(conn, conversation_id, user_id)
            if conv is None:
                return None
            return await agent_repo.get_conversation_messages(conn, conversation_id)

    async def delete_conversation(
        self,
        user_id: str,
        conversation_id: UUID,
    ) -> bool:
        """Delete a conversation. Returns True if deleted, False if not found."""
        async with connection_ctx() as conn:
            existing = await agent_repo.get_conversation(conn, conversation_id, user_id)
            if existing is None:
                return False
            await agent_repo.delete_conversation(conn, conversation_id)
            return True


# ── Singleton ─────────────────────────────────────────────────────────────

agent_service: AgentService = AgentService()
