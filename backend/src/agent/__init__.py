"""
StockLens LangGraph ReAct Agent.

A conversational finance agent using the ReAct (Reason + Act) loop:
the LLM (DeepSeek V3.1 via Bedrock Converse API) reasons about the
user's question, calls tools to fetch portfolio/market/spending data,
incorporates results, and streams responses via SSE.

Key modules:
    - schemas.py: Pydantic models for agent API
    - repository.py: asyncpg CRUD for conversations + messages
    - tools.py: 16 agent tool definitions with InjectedToolArg
    - graph.py: LangGraph StateGraph definition
    - service.py: AgentService singleton with two-tier persistence
    - router.py: FastAPI endpoints (Round 3)
"""

from __future__ import annotations

from src.agent.service import agent_service

__all__ = ["agent_service"]
