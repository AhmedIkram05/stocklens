"""
Tests for the LangSmith-native evaluation harness (src.agent_eval).

Covers dataset upload, experiment target, the agent feedback route, and the
fire-and-forget feedback logging in AgentService. All LangSmith network calls
are mocked so the suite runs offline.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent_eval.run_experiment import _target
from agent_eval.upload_dataset import upload_dataset
from src.agent.service import agent_service

# ── Dataset upload ───────────────────────────────────────────────────────────


def test_upload_dataset_idempotent():
    """Re-running upload deletes the dataset then recreates it."""
    fake_client = MagicMock()
    fake_dataset = MagicMock()
    fake_dataset.id = "ds-123"
    fake_client.has_dataset.return_value = True
    fake_client.create_dataset.return_value = fake_dataset

    upload_dataset(client=fake_client)

    fake_client.has_dataset.assert_called_once()
    fake_client.delete_dataset.assert_called_once_with(dataset_name="stocklens-golden")
    fake_client.create_dataset.assert_called_once()
    # 22 questions in golden_dataset.json -> 22 create_examples inputs
    inputs = fake_client.create_examples.call_args.kwargs["inputs"]
    assert len(inputs) == 41
    assert all("question" in row for row in inputs)


def test_upload_dataset_first_run():
    """First run (dataset doesn't exist) skips delete_dataset."""
    fake_client = MagicMock()
    fake_dataset = MagicMock()
    fake_dataset.id = "ds-0"
    fake_client.has_dataset.return_value = False
    fake_client.create_dataset.return_value = fake_dataset

    upload_dataset(client=fake_client)

    fake_client.has_dataset.assert_called_once()
    fake_client.delete_dataset.assert_not_called()
    fake_client.create_dataset.assert_called_once_with(
        dataset_name="stocklens-golden",
        description="StockLens agent golden evaluation questions",
    )
    assert fake_client.create_examples.call_args.kwargs["inputs"]


# ── Experiment target ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_run_experiment_target():
    """_target runs a question through the graph and returns the last message."""
    last_msg = MagicMock()
    last_msg.content = "Your portfolio is up 2.3% today."
    fake_result = {"messages": [MagicMock(content="ignored"), last_msg]}
    fake_graph = MagicMock()
    fake_graph.ainvoke = AsyncMock(return_value=fake_result)

    with patch("agent_eval.run_experiment._build_graph", return_value=fake_graph):
        out = await _target({"question": "How is my portfolio doing?"})

    assert out == {"response": "Your portfolio is up 2.3% today."}
    # graph was invoked with the fixed eval UUID (changed from "eval")
    args, _ = fake_graph.ainvoke.call_args
    assert args[0]["user_id"] == "00000000-0000-0000-0000-000000000001"
    from langchain_core.messages import HumanMessage, SystemMessage

    assert isinstance(args[0]["messages"][0], SystemMessage)
    assert isinstance(args[0]["messages"][1], HumanMessage)
    assert args[0]["messages"][1].content == "How is my portfolio doing?"


@pytest.mark.asyncio
async def test_run_agent_builds_messages():
    """_target prepends PERSONA_PROMPT as a SystemMessage, then the question."""
    captured = {}

    async def _fake_ainvoke(state):
        captured.update(state)
        last = MagicMock()
        last.content = "ok"
        return {"messages": [last]}

    fake_graph = MagicMock()
    fake_graph.ainvoke.side_effect = _fake_ainvoke

    with patch("agent_eval.run_experiment._build_graph", return_value=fake_graph):
        await _target({"question": "What is the price of AAPL?"})

    from langchain_core.messages import HumanMessage, SystemMessage

    assert len(captured["messages"]) == 2
    assert isinstance(captured["messages"][0], SystemMessage)
    assert isinstance(captured["messages"][1], HumanMessage)
    assert captured["messages"][1].content == "What is the price of AAPL?"


# ── Feedback route ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_feedback_route(monkeypatch):
    """POST /agent/feedback pushes a feedback point to LangSmith."""
    from src.agent.router import submit_feedback
    from src.agent.schemas import AgentFeedbackRequest
    from src.config import settings

    monkeypatch.setattr(settings, "LANGCHAIN_API_KEY", "test-key")
    fake_user = MagicMock()
    fake_user.id = "user-9"

    with patch("src.agent.router.Client") as client_cls:
        resp = await submit_feedback(
            AgentFeedbackRequest(rating="positive", trace_id="trace-abc"),
            current_user=fake_user,
        )

    assert resp == {"status": "ok"}
    client_cls.return_value.create_feedback.assert_called_once_with(
        feedback_key="positive",
        trace_id="trace-abc",
        comment="user=user-9",
        feedback_source_type="app",
        source_metadata={"user_id": "user-9"},
    )


@pytest.mark.asyncio
async def test_feedback_route_skipped_without_key(monkeypatch):
    """Without a LangSmith key the route is a no-op."""
    from src.agent.router import submit_feedback
    from src.agent.schemas import AgentFeedbackRequest
    from src.config import settings

    monkeypatch.setattr(settings, "LANGCHAIN_API_KEY", "")
    fake_user = MagicMock()
    fake_user.id = "user-9"

    with patch("src.agent.router.Client") as client_cls:
        resp = await submit_feedback(
            AgentFeedbackRequest(rating="positive", trace_id="trace-abc"),
            current_user=fake_user,
        )

    assert resp == {"status": "skipped", "reason": "langsmith_disabled"}
    client_cls.assert_not_called()


# ── Background eval logging ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_eval_background_logs_feedback(monkeypatch):
    """_run_eval_background logs a sampled_eval feedback point via LangSmith."""
    from src.config import settings

    monkeypatch.setattr(settings, "LANGCHAIN_API_KEY", "test-key")

    fake_create = MagicMock()
    with patch("src.agent.service.Client", return_value=MagicMock()) as client_cls:
        client_cls.return_value.create_feedback = fake_create
        await agent_service._run_eval_background(
            conversation_id=__import__("uuid").uuid4(),
            user_id="user-1",
            question="hi",
            response_text="hello",
            tools_used=["get_quote"],
        )
        # _run_eval_background schedules the log as a fire-and-forget task; await it
        # while the Client mock is still active.
        assert agent_service._eval_tasks
        await asyncio.gather(*list(agent_service._eval_tasks))

    assert fake_create.called
    _, kwargs = fake_create.call_args
    assert kwargs["feedback_key"] == "sampled_eval"
    assert kwargs["score"] == 1.0
    assert "user=user-1" in kwargs["comment"]
    assert "tools=['get_quote']" in kwargs["comment"]
    assert "conversation_id" in kwargs["source_metadata"]


# ── Dataset integrity ─────────────────────────────────────────────────────────


def test_golden_dataset_tool_names_valid():
    """Every expected_tools entry references a real tool function in tools.py."""
    from agent_eval.upload_dataset import load_questions
    from src.agent.tools import _AGENT_TOOLS

    questions = load_questions()
    real_tools = {t.name for t in _AGENT_TOOLS}

    all_valid = True
    bad_entries: list[str] = []
    for q in questions:
        for tool_name in q.get("expected_tools", []):
            if tool_name not in real_tools:
                bad_entries.append(f"  '{tool_name}' (referenced by: {q['question'][:60]}...)")
                all_valid = False

    assert all_valid, "expected_tools not found in tools.py:\n" + "\n".join(bad_entries)


def test_golden_dataset_structure():
    """All golden dataset entries have required fields with correct types."""
    from agent_eval.upload_dataset import load_questions

    questions = load_questions()
    assert len(questions) >= 1

    for i, q in enumerate(questions):
        assert "question" in q, f"Entry {i} missing 'question'"
        assert isinstance(q["question"], str), f"Entry {i} 'question' must be str"
        assert q["question"], f"Entry {i} 'question' must not be empty"

        assert "expected_tools" in q, f"Entry {i} missing 'expected_tools'"
        assert isinstance(q["expected_tools"], list), f"Entry {i} 'expected_tools' must be list"

        assert "expected_response_contains" in q, f"Entry {i} missing 'expected_response_contains'"
        assert isinstance(q["expected_response_contains"], list), (
            f"Entry {i} 'expected_response_contains' must be list"
        )

        assert "difficulty" in q, f"Entry {i} missing 'difficulty'"
        assert q["difficulty"] in ("easy", "medium", "hard"), (
            f"Entry {i} difficulty must be easy/medium/hard, got {q['difficulty']!r}"
        )

        assert "category" in q, f"Entry {i} missing 'category'"
        assert isinstance(q["category"], str), f"Entry {i} 'category' must be str"
