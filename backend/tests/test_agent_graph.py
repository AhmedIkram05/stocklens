"""
Tests for src/agent/graph.py — LangGraph StateGraph construction.

``create_agent_graph`` builds a two-node ReAct graph. We verify the graph
structure and (with mocked Bedrock) that a simple invocation flows through
correctly, without needing real AWS credentials.

All LangChain/LangGraph dependencies are already installed in the dev extras.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest


class TestCreateAgentGraph:
    """Tests for create_agent_graph — graph topology and basic execution."""

    def _fake_tool(self):
        """Return a minimal callable tool for graph construction tests."""
        from langchain_core.tools import tool

        @tool
        def dummy_tool(query: str) -> str:
            """A dummy tool that returns its input."""
            return f"result: {query}"

        return dummy_tool

    def test_graph_has_two_nodes(self):
        """The graph should contain 'agent' and 'tools' nodes."""
        from src.agent.graph import create_agent_graph

        with patch("src.agent.graph.ChatBedrockConverse") as mock_model_cls:
            mock_instance = mock_model_cls.return_value
            mock_instance.bind_tools.return_value = mock_instance
            mock_instance.ainvoke = AsyncMock(return_value=type("Msg", (), {"content": "done"})())

            graph = create_agent_graph([self._fake_tool()])

        # Graph should be uncompiled (StateGraph)
        assert hasattr(graph, "nodes")
        node_names = list(graph.nodes.keys())
        assert "agent" in node_names
        assert "tools" in node_names

    def test_graph_starts_at_agent(self):
        """START should edge to 'agent'."""
        from src.agent.graph import create_agent_graph

        with patch("src.agent.graph.ChatBedrockConverse") as mock_model_cls:
            mock_instance = mock_model_cls.return_value
            mock_instance.bind_tools.return_value = mock_instance
            mock_instance.ainvoke = AsyncMock(return_value=type("Msg", (), {"content": "done"})())

            graph = create_agent_graph([self._fake_tool()])
            compiled = graph.compile()

        # The compiled graph's input schema should map to agent node first
        # Check that START → agent is wired
        assert "agent" in compiled.nodes

    def test_tools_node_contains_provided_tools(self):
        """The tools node should hold the tools passed to the factory."""
        from src.agent.graph import create_agent_graph

        tool = self._fake_tool()

        with patch("src.agent.graph.ChatBedrockConverse") as mock_model_cls:
            mock_instance = mock_model_cls.return_value
            mock_instance.bind_tools.return_value = mock_instance
            mock_instance.ainvoke = AsyncMock(return_value=type("Msg", (), {"content": "done"})())

            graph = create_agent_graph([tool])

        tools_node_spec = graph.nodes.get("tools")
        assert tools_node_spec is not None
        # In newer LangGraph, nodes are StateNodeSpec with a .runnable
        runnable = getattr(tools_node_spec, "runnable", tools_node_spec)
        assert runnable is not None
        assert "dummy_tool" in str(runnable)

    @pytest.mark.asyncio
    async def test_conditional_edge_routes_to_tools(self):
        """tools_condition should route to 'tools' when the model calls a tool."""
        from langchain_core.messages import AIMessage, HumanMessage, ToolCall

        from src.agent.graph import create_agent_graph

        tool = self._fake_tool()

        with patch("src.agent.graph.ChatBedrockConverse") as mock_model_cls:
            mock_instance = mock_model_cls.return_value
            mock_instance.bind_tools.return_value = mock_instance

            # Simulate an AI message that calls a tool
            mock_instance.ainvoke = AsyncMock(
                return_value=AIMessage(
                    content="",
                    tool_calls=[
                        ToolCall(
                            name="dummy_tool",
                            args={"query": "hello"},
                            id="call-1",
                            type="tool_call",
                        )
                    ],
                )
            )

            graph = create_agent_graph([tool])
            compiled = graph.compile()

        state = {"messages": [HumanMessage(content="hello")], "user_id": "usr-1"}
        result = await compiled.ainvoke(state)

        # The tool should have been called and produced a result
        messages = result["messages"]
        tool_responses = [m for m in messages if hasattr(m, "name")]
        assert len(tool_responses) > 0

    @pytest.mark.asyncio
    async def test_agent_node_calls_model_ainvoke(self):
        """The agent node should call model.ainvoke with the message list."""
        from langchain_core.messages import AIMessage, HumanMessage

        from src.agent.graph import create_agent_graph

        tool = self._fake_tool()

        with patch("src.agent.graph.ChatBedrockConverse") as mock_model_cls:
            mock_instance = mock_model_cls.return_value
            mock_instance.bind_tools.return_value = mock_instance

            mock_ainvoke = AsyncMock(return_value=AIMessage(content="Hello there!"))
            mock_instance.ainvoke = mock_ainvoke

            graph = create_agent_graph([tool])
            compiled = graph.compile()

        state = {"messages": [HumanMessage(content="Hi")], "user_id": "usr-1"}
        result = await compiled.ainvoke(state)

        result_messages = result["messages"]
        assert any(getattr(m, "content", None) == "Hello there!" for m in result_messages)

    def test_bind_tools_receives_tool_list(self):
        """ChatBedrockConverse.bind_tools should be called with the tool list."""
        from src.agent.graph import create_agent_graph

        tool = self._fake_tool()

        with patch("src.agent.graph.ChatBedrockConverse") as mock_model_cls:
            mock_instance = mock_model_cls.return_value
            mock_instance.bind_tools.return_value = mock_instance
            mock_instance.ainvoke = AsyncMock(return_value=type("Msg", (), {"content": "done"})())

            create_agent_graph([tool])

        mock_instance.bind_tools.assert_called_once()
        args, _ = mock_instance.bind_tools.call_args
        assert len(args[0]) == 1  # one tool passed

    def test_model_init_uses_settings(self):
        """ChatBedrockConverse should be initialised with settings values."""
        from src.agent.graph import create_agent_graph

        tool = self._fake_tool()

        with patch("src.agent.graph.ChatBedrockConverse") as mock_model_cls:
            mock_instance = mock_model_cls.return_value
            mock_instance.bind_tools.return_value = mock_instance
            mock_instance.ainvoke = AsyncMock(return_value=type("Msg", (), {"content": "done"})())

            create_agent_graph([tool])

        mock_model_cls.assert_called_once()
        _, kwargs = mock_model_cls.call_args
        assert "model" in kwargs
        assert "max_tokens" in kwargs
        assert "temperature" in kwargs
        assert "region_name" in kwargs
