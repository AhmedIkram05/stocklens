"""
LangGraph StateGraph definition for the StockLens ReAct agent.

Uses manual StateGraph nodes/edges (not ``create_react_agent``).
No checkpointer — state persistence is handled manually via two-tier Redis+RDS.
"""

from __future__ import annotations

from typing import Annotated, NotRequired, Sequence

import structlog
from langchain_aws import ChatBedrockConverse
from langchain_core.messages import BaseMessage
from langgraph.graph import START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode, tools_condition
from typing_extensions import TypedDict

from src.config import settings

logger = structlog.get_logger()


class AgentState(TypedDict):
    """State passed through the agent graph."""

    messages: Annotated[Sequence[BaseMessage], add_messages]
    user_id: str
    # Optional — not set until the user mentions a specific portfolio.
    # Tools that need it will receive an empty string and gracefully report
    # "portfolio not found" rather than crashing the graph.
    portfolio_id: NotRequired[str]


def create_agent_graph(tools: list) -> StateGraph:
    """Build and return the uncompiled agent graph.

    Uses DeepSeek V3.1 (via Bedrock Converse API) — supports tool use.
    No checkpointer: state persistence is handled manually via two-tier Redis+RDS.
    """
    model = ChatBedrockConverse(
        model=settings.AGENT_MODEL_ID,
        max_tokens=settings.AGENT_MAX_TOKENS,
        temperature=settings.AGENT_TEMPERATURE,
        region_name=settings.AWS_REGION,
    ).bind_tools(tools)

    tool_node = ToolNode(tools)

    async def agent_node(state: AgentState) -> dict:
        """Call the LLM with current state."""
        result = await model.ainvoke(state["messages"])
        return {"messages": [result]}

    graph = StateGraph(AgentState)
    graph.add_node("agent", agent_node)
    graph.add_node("tools", tool_node)
    graph.add_conditional_edges(
        "agent",
        tools_condition,  # routes to "tools" if tool_calls present, else END
    )
    graph.add_edge("tools", "agent")
    graph.add_edge(START, "agent")
    return graph


__all__ = ["AgentState", "create_agent_graph"]
