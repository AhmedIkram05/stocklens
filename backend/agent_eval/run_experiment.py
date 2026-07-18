"""Run the StockLens agent evaluation experiment against the golden dataset.

Builds the agent graph from the live tool registry, then runs each golden
question through LangSmith ``evaluate`` with LLM-as-judge criteria evaluators
(correctness + relevance). The judge is a Bedrock chat model; evaluators are
plain ``(example, prediction) -> dict`` functions, so no extra ``langchain``
evaluation package is needed.
"""

from __future__ import annotations

import asyncio

from langchain_aws import ChatBedrockConverse
from langchain_core.messages import HumanMessage, SystemMessage
from langsmith import Client
from langsmith.evaluation import aevaluate
from langsmith.schemas import Example

from src.agent.graph import create_agent_graph
from src.agent.service import PERSONA_PROMPT
from src.agent.tools import get_all_tools
from src.config import settings
from src.database.connection import close_pool, init_pool

DATASET_NAME = "stocklens-golden"
EXPERIMENT_PREFIX = "stocklens-agent"


def _build_graph():
    """Compile the agent graph with the full tool registry."""
    tools = get_all_tools()
    return create_agent_graph(tools).compile()


async def _target(inputs: dict) -> dict:
    """Run one question through the agent and return its final response."""
    graph = _build_graph()
    result = await graph.ainvoke(
        {
            # Mirror live traffic: the service layer prepends PERSONA_PROMPT as
            # the system message before invoking the graph, so the eval run
            # exercises the same code path the agent sees in production.
            "messages": [
                SystemMessage(content=PERSONA_PROMPT),
                HumanMessage(content=inputs["question"]),
            ],
            "user_id": "00000000-0000-0000-0000-000000000001",
        }
    )
    return {"response": result["messages"][-1].content}


def _judge() -> ChatBedrockConverse:
    """Lazily build the Bedrock judge model."""
    return ChatBedrockConverse(
        model=settings.AGENT_JUDGE_MODEL_ID,
        max_tokens=settings.AGENT_MAX_TOKENS,
        temperature=0,
        region_name=settings.AWS_REGION,
    )


async def _score_criterion(key: str, criterion: str, example: Example, prediction: dict) -> dict:
    """LLM-as-judge for one criterion. Returns a LangSmith feedback-style dict."""
    question = (example.inputs or {}).get("question", "")
    response = (prediction or {}).get("response", "")
    verdict = await _judge().ainvoke(
        [
            SystemMessage(
                content=(
                    "You are a strict evaluation judge. Score the assistant "
                    "response against the criterion. Reply with only 'YES' or 'NO' "
                    "on the first line, then one short reason.\n\n"
                    f"Criterion: {criterion}"
                )
            ),
            HumanMessage(content=f"Question: {question}\n\nResponse: {response}"),
        ]
    )
    text = verdict.content if isinstance(verdict.content, str) else str(verdict.content)
    score = 1.0 if text.strip().upper().startswith("YES") else 0.0
    return {"key": key, "score": score, "comment": text}


# Plain async functions: evaluate() accepts `(example, prediction) -> dict`
# for function-type targets. No langchain.smith / StringEvaluator needed.
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

_EVALUATORS = [
    lambda example, prediction, _k=key, _c=crit: _score_criterion(_k, _c, example, prediction)
    for key, crit in _CRITERIA
]


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
            evaluators=_EVALUATORS,
            experiment_prefix=EXPERIMENT_PREFIX,
        )
    finally:
        await close_pool()


if __name__ == "__main__":
    asyncio.run(run_experiment())
