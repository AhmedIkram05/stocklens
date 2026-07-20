"""Run the StockLens agent evaluation experiment against the golden dataset.

Builds the agent graph from the live tool registry, then runs each golden
question through LangSmith ``aevaluate`` with LLM-as-judge criteria
evaluators (correctness + relevance). The judge is a Bedrock chat model.

The graph and judge model are built once at module level and reused across
all questions to avoid redundant compilation and Bedrock client creation.
"""

from __future__ import annotations

import asyncio
import re

from langchain_aws import ChatBedrockConverse
from langchain_core.messages import HumanMessage, SystemMessage
from langsmith import Client
from langsmith.evaluation import aevaluate
from langsmith.schemas import Example, Run

from src.agent.graph import create_agent_graph
from src.agent.service import PERSONA_PROMPT
from src.agent.tools import get_all_tools
from src.config import settings
from src.database.connection import close_pool, init_pool

DATASET_NAME = "stocklens-golden"
# Include models in the experiment name so LangSmith runs are distinguishable
# without opening each one.
_AGENT_SLUG = settings.AGENT_MODEL_ID.replace(".", "-").replace(":", "-")
_JUDGE_SLUG = settings.AGENT_JUDGE_MODEL_ID.replace(".", "-").replace(":", "-")
EXPERIMENT_PREFIX = f"stocklens-agent-{_AGENT_SLUG}__judge-{_JUDGE_SLUG}"

_CRITERIA = [
    (
        "correctness",
        "Is the response factually correct and grounded in the tools/data the agent had access to?",
    ),
    (
        "relevance",
        "Does the response directly address the user's question and stay on the "
        "finance/investing topic?",
    ),
]

# ── Build once, reuse for all questions ──────────────────────────────
_GRAPH = create_agent_graph(get_all_tools()).compile()
_JUDGE_MODEL = ChatBedrockConverse(
    model=settings.AGENT_JUDGE_MODEL_ID,
    max_tokens=settings.AGENT_MAX_TOKENS,
    temperature=0,
    region_name=settings.AWS_REGION,
)


async def _target(inputs: dict) -> dict:
    """Run one question through the agent and return its final response."""
    result = await _GRAPH.ainvoke(
        {
            "messages": [
                SystemMessage(content=PERSONA_PROMPT),
                HumanMessage(content=inputs["question"]),
            ],
            "user_id": "00000000-0000-0000-0000-000000000001",
        }
    )
    return {"response": result["messages"][-1].content}


async def _score_criteria(run: Run, example: Example) -> dict:
    """LLM-as-judge for all criteria in a single Bedrock call.

    LangSmith evaluators receive ``(Run, Example)`` — the run holds the
    target's outputs, the example holds the dataset question.
    Returns ``EvaluationResults``-compatible dict with both correctness and
    relevance scores, halving the judge latency vs one call per criterion.
    """
    question = (example.inputs or {}).get("question", "")
    response = (run.outputs or {}).get("response", "")
    verdict = await _JUDGE_MODEL.ainvoke(
        [
            SystemMessage(
                content=(
                    "You are a strict evaluation judge. Score the assistant "
                    "response against each criterion. Reply with exactly one "
                    "line per criterion:\n"
                    "correctness: YES (or NO) — reason\n"
                    "relevance: YES (or NO) — reason\n\n"
                    "Criteria:\n"
                    f"- correctness: {_CRITERIA[0][1]}\n"
                    f"- relevance: {_CRITERIA[1][1]}"
                )
            ),
            HumanMessage(content=f"Question: {question}\n\nResponse: {response}"),
        ]
    )
    text = verdict.content if isinstance(verdict.content, str) else str(verdict.content)
    results: list[dict] = []
    for key, _ in _CRITERIA:
        match = re.search(rf"^{key}:\s*(YES|NO)", text.strip(), re.MULTILINE | re.IGNORECASE)
        score = 1.0 if (match and match.group(1).upper() == "YES") else 0.0
        results.append({"key": key, "score": score, "comment": text[:300]})
    return {"results": results}


async def run_experiment(client: Client | None = None) -> None:
    """Execute the evaluation experiment on LangSmith."""
    # The eval runs outside FastAPI, so init the DB pool manually.
    await init_pool(settings.DATABASE_URL)
    try:
        client = client or Client()
        try:
            dataset = next(client.list_datasets(dataset_name=DATASET_NAME))
        except StopIteration:
            raise RuntimeError(
                f"Dataset '{DATASET_NAME}' not found. Run `python -m agent_eval.upload_dataset` first."  # noqa: E501
            ) from None
        await aevaluate(
            _target,
            data=dataset,
            evaluators=[_score_criteria],
            experiment_prefix=EXPERIMENT_PREFIX,
            # Default is 0 (no concurrency) — 41 questions × ~1min each = 40+ min.
            # None removes the limit so questions run in parallel via asyncio.
            max_concurrency=None,
        )
    finally:
        await close_pool()


if __name__ == "__main__":
    asyncio.run(run_experiment())
