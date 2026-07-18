# Phase 6 — LangGraph Conversational Finance Agent

> **Status:** Draft (pending review)
> **Last updated:** 2026-07-13
> **Depends on:** Phase 5 R1–R5 (ECS Fargate deployed), Phase 4 MLOps (drift monitoring, prediction pipeline)
> **Target audience:** AI coding agents (each round is a self-contained, chronological unit of work)
> **ReAct agent:** This agent uses the ReAct (Reason + Act) loop — the LLM reasons about the user's question, calls tools to fetch data, incorporates the results, and reasons again until a complete answer is ready. Powered by LangGraph's StateGraph + ToolNode.
> **Architecture decisions:** Locked in grilling session — see `docs/adr/` for ADR references

---

## Table of Contents

1. [Overview](#overview)
2. [Architecture (Target End State)](#architecture-target-end-state)
3. [Modules Touched](#modules-touched)
4. [Implementation Rounds](#implementation-rounds)
   - [Round 1 — Foundation: Dependencies, DB Schema, Config](#round-1--foundation-dependencies-db-schema-config)
   - [Round 2 — Agent Graph Engine](#round-2--agent-graph-engine)
   - [Round 3 — Agent API Endpoints](#round-3--agent-api-endpoints)
   - [Round 4 — New Tool Endpoints](#round-4--new-tool-endpoints)
   - [Round 5 — Backend Evaluation Module](#round-5--backend-evaluation-module)
   - [Round 6 — Frontend Chat UI](#round-6--frontend-chat-ui)
5. [Testing Strategy](#testing-strategy)
6. [Success Criteria](#success-criteria)
7. [Risks & Mitigations](#risks--mitigations)
8. [Verification Checklist](#verification-checklist)

---

## Overview

Phase 6 adds a **LangGraph ReAct agent** to StockLens. Users can ask natural-language questions about their portfolio, spending, market data, and forecasts — the agent uses the **ReAct (Reason + Act)** loop to call the right tools, incorporate results, and stream the final response back via SSE. Built with **LangGraph StateGraph + ToolNode** for precise control flow.

The agent is **analytical only** — it answers questions and provides insights but never executes trades or modifies user data autonomously.

---

## Architecture (Target End State)

```
Frontend (React Native)                          Backend (FastAPI)
┌─────────────────────────┐        SSE/Streaming        ┌──────────────────────────────────┐
│                         │ ◄══════════════════════════ │                                  │
│  PortfolioListScreen    │    POST /agent/chat         │  agent/router.py                  │
│    ├── AI Chat button   │    (Bearer JWT)             │    ├── POST /chat                 │
│    └── AgentChatScreen  │                             │    ├── GET /conversations          │
│         (Modal)         │                             │    └── GET /conversation/{id}     │
│                         │                             │                                  │
│  agentService.ts        │                             │  agent/service.py — TWO-TIER MEM  │
│    ├── sendMessage()    │                             │    ├── AgentService (singleton)    │
│    └── SSE stream parse │                             │    ├── graph.compile()             │
└─────────────────────────┘                             │    ├── astream_events()            │
                                                        │    └── _persist_turn()             │
                                                        │         │                         │
                                                        │    ┌────▼──────────────┐         │
                                                        │    │   Tier 1: Redis   │         │
                                                        │    │ agent:session:{id}│ ← JSON  │
                                                        │    │   TTL: 7 days     │  state  │
                                                        │    └───────────────────┘         │
                                                        │    ┌────▼──────────────┐         │
                                                        │    │  Tier 2: RDS      │         │
                                                        │    │   conversations   │ ← list  │
                                                        │    │ agent_conversations│ ← turns │
                                                        │    └───────────────────┘         │
                                                        │                                  │
                                                        │  agent/graph.py                   │
                                                        │    ├── StateGraph (no checkpointer│
                                                        │    ├── agent_node                  │
                                                        │    ├── tools_node                  │
                                                        │    └── should_continue             │
                                                        │                                  │
                                                        │  agent/tools.py                    │
                                                        │    ├── 7 new endpoints             │
                                                        │    └── 9 existing wraps           │
                                                        │                                  │
│  agent_eval/ (LangSmith-native)   │
│    ├── run_experiment.py          │
│    ├── upload_dataset.py          │
│    └── golden_dataset.json        │
└──────────────────────────────────┘
```

### LangGraph Graph Structure (ReAct Loop)

This is the **ReAct (Reason + Act)** pattern: the agent LLM reasons about the user's question, calls tools when it needs data, incorporates tool results, and repeats until it can produce a complete answer. Each cycle is visible in the SSE stream (`tool_start` / `tool_end` events).

```
                    ┌──────────┐
                    │   START   │
                    └────┬─────┘
                         │
                    ┌────▼─────┐
                    │  agent   │  LLM reasons & acts (ReAct)
                    └────┬─────┘
                         │
                    ┌────▼─────────┐
                    │ should_continue│
                    │ (conditional) │
                    └────┬─────────┘
                         │
              ┌──────────┴──────────┐
              │                     │
         has tool_calls         no tool_calls
           (act needed)        (answer ready)
              │                     │
        ┌─────▼──────┐        ┌────▼────┐
        │   tools    │        │   END   │
        │  (ToolNode)│        └─────────┘
        └─────┬──────┘
              │
              └─────────► back to agent (reason)
                           with new data
```

---

## Modules Touched

### New Backend Files

| File                                                                        | Purpose                                                                    |
| --------------------------------------------------------------------------- | -------------------------------------------------------------------------- |
| `backend/src/agent/__init__.py`                                             | Module docstring                                                           |
| `backend/src/agent/schemas.py`                                              | Pydantic models for agent API                                              |
| `backend/src/agent/graph.py`                                                | LangGraph StateGraph definition                                            |
| `backend/src/agent/tools.py`                                                | All tool definitions (16 tools — existing wraps + new)                     |
| `backend/src/agent/service.py`                                              | AgentService singleton (loads graph, runs inference)                       |
| `backend/src/agent/router.py`                                               | FastAPI endpoints for chat + history (+ `POST /agent/feedback` in Round 5) |
| `backend/src/agent/repository.py`                                           | asyncpg queries for agent DB tables                                        |
| `backend/agent_eval/__init__.py`                                            | LangSmith-native eval package marker                                       |
| `backend/agent_eval/run_experiment.py`                                      | LangSmith `evaluate()` experiment runner                                   |
| `backend/agent_eval/upload_dataset.py`                                      | Idempotent golden dataset upload                                           |
| `backend/agent_eval/golden_dataset.json`                                    | 20–30 curated test cases                                                   |
| `backend/tests/test_agent_eval.py`                                          | Unit tests for eval pipeline + feedback route                              |
| `backend/pyproject.toml`                                                    | Add `langsmith>=0.3.0` dependency (Round 5)                                |
| `.github/workflows/eval.yml`                                                | MANDATORY CI workflow running LangSmith experiments                        |
| `backend/alembic/versions/0009_add_spending_category_id_to_transactions.py` | Migration: add `spending_category_id` to `transactions`                    |
| `backend/alembic/versions/0010_agent_conversations_refactor.py`             | Migration for new agent schema                                             |

### New Frontend Files

| File                                             | Purpose                               |
| ------------------------------------------------ | ------------------------------------- |
| `frontend/src/services/agent.ts`                 | Agent chat service with SSE streaming |
| `frontend/src/screens/AgentChatScreen.tsx`       | Chat UI modal                         |
| `frontend/src/components/chat/MessageBubble.tsx` | Single message bubble component       |
| `frontend/src/components/chat/ToolIndicator.tsx` | "Using tool X..." indicator           |

### Modified Files

| File                                                     | Change                                                                                                                        |
| -------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------- |
| `backend/pyproject.toml`                                 | Add `langgraph`, `langchain-core` deps                                                                                        |
| `backend/src/config.py`                                  | Add agent config values                                                                                                       |
| `backend/src/main.py`                                    | Register agent router, init AgentService                                                                                      |
| `backend/src/database/schema.py`                         | Add `conversations` table, refactor `agent_conversations` for multi-turn; add `spending_category_id` column to `transactions` |
| `frontend/src/screens/portfolio/PortfolioListScreen.tsx` | Add AI chat header button                                                                                                     |
| `docs/CONTEXT.md`                                        | Phase 6 terms (already added in grilling)                                                                                     |

---

## Implementation Rounds

### Round 1 — Foundation: Dependencies, DB Schema, Config

**Goal:** All prerequisites ready before agent code is written.

#### 1.1 Add Python dependencies

**File:** `backend/pyproject.toml`

Add to `[project]` dependencies:

```toml
langgraph>=1.0.0
langchain-core>=0.3.0
```

`langchain-aws>=1.6.0` already exists for Bedrock integration. No new provider packages needed — all three models are accessed via Bedrock's Converse API through `ChatBedrockConverse`.

**Model allocation:**

| Model            | Bedrock Model ID                           | Purpose                               |
| ---------------- | ------------------------------------------ | ------------------------------------- |
| Claude Haiku 4.5 | `anthropic.claude-haiku-4-5-20251001-v1:0` | NLP pipeline (`BEDROCK_MODEL_ID`)     |
| DeepSeek V3.1    | `deepseek.v3-v1:0`                         | Agent inference (`AGENT_MODEL_ID`)    |
| GPT 5.4          | `openai.gpt-5.4`                           | LLM-as-Judge (`AGENT_JUDGE_MODEL_ID`) |

**Verification:** `uv sync --dev` succeeds. `python -c "import langgraph" && python -c "import langchain_core"` works.

**Risk:** Low. Standard dependency addition.

#### 1.2 Add `spending_category_id` to transactions table

**File:** `backend/src/database/schema.py`

The `categorize_tool` and `get_spending_analysis` tool join `transactions` with `spending_categories` via `spending_category_id`. This column does not yet exist on the `transactions` table — it must be added before agent tools can use it.

Add to the `transactions` Table definition (after `notes` column, before `created_at`):

```python
Column(
    "spending_category_id",
    UUID(as_uuid=True),
    ForeignKey("spending_categories.id", ondelete="SET NULL"),
    nullable=True,
),
```

**Verification:** Query confirms column exists: `SELECT spending_category_id FROM transactions LIMIT 1`. Alembic autogenerate detects no drift.

**Note:** The nullable FK uses `SET NULL` on delete so deleting a category does not lose transaction history.

**Risk:** Low. New nullable column — no impact on existing data or queries.

#### 1.3 Refactor agent database tables

**File:** `backend/src/database/schema.py`

The existing `agent_conversations` table is single-turn and never had data written (agent was never deployed). Replace it with a two-tier compatible schema:

**New `conversations` table** — lightweight metadata for list endpoint:

```python
conversations = Table(
    "conversations",
    target_metadata,
    Column("id", UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")),
    Column("user_id", UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
    Column("title", Text(), nullable=True),  # auto-generated from first user message
    Column("message_count", Integer(), server_default=text("0"), nullable=False),
    Column("created_at", DateTime(timezone=True), server_default=func.now(), nullable=False),
    Column("updated_at", DateTime(timezone=True), server_default=func.now(), nullable=False),
)
```

**Replacement `agent_conversations` table** — multi-turn message archive:

```python
agent_conversations = Table(
    "agent_conversations",
    target_metadata,
    Column("id", BigInteger(), primary_key=True, autoincrement=True),
    Column("conversation_id", UUID(as_uuid=True), ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False),
    Column("user_id", UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
    Column("role", String(20), nullable=False),  # "user" | "assistant"
    Column("content", Text(), nullable=False),
    Column("tools_used", JSONB(), nullable=True),
    Column("reasoning_steps", JSONB(), nullable=True),
    Column("created_at", DateTime(timezone=True), server_default=func.now(), nullable=False),
)
```

Add indexes:

```python
Index("idx_conversations_user", conversations.c.user_id)
Index("idx_agent_conversations_cid", agent_conversations.c.conversation_id)
```

**Why two tables instead of one:** `conversations` is lightweight for the list endpoint (avoids full message scan). `agent_conversations` stores the actual turns. The `conversation_id` joins them — same UUID used as the LangGraph `thread_id` and the Redis key.

**Dependencies:** Requires alembic env setup (already exists).
**Risk:** Low. Table has zero rows in production.

#### 1.4 Create migration 0009 — add `spending_category_id` to transactions

**File:** `backend/alembic/versions/0009_add_spending_category_id_to_transactions.py`

Manual migration since the plan predates this column. Adding a new nullable FK column:

```python
"""add spending_category_id to transactions table

Revision ID: 0009
Revises: 0008
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "0009"
down_revision = "0008"

def upgrade() -> None:
    op.add_column(
        "transactions",
        sa.Column(
            "spending_category_id",
            UUID(as_uuid=True),
            sa.ForeignKey("spending_categories.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index(
        "idx_transactions_spending_category",
        "transactions",
        ["spending_category_id"],
    )

def downgrade() -> None:
    op.drop_index("idx_transactions_spending_category", "transactions")
    op.drop_column("transactions", "spending_category_id")
```

**Verification:** `alembic upgrade head` succeeds. `SELECT spending_category_id FROM transactions LIMIT 1` returns no error. `alembic downgrade -1` removes the column.

**Risk:** Low. Nullable column with no data dependency.

#### 1.5 Create migration 0010 — agent conversations refactor (was 0009)

**File:** `backend/alembic/versions/0010_agent_conversations_refactor.py`

Manual migration (following existing pattern). Since `agent_conversations` has zero rows, we drop and recreate:

```python
"""refactor agent_conversations into multi-turn schema

Revision ID: 0010
Revises: 0009
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

revision = "0010"
down_revision = "0009"

def upgrade() -> None:
    # 1. Create conversations table (lightweight metadata)
    op.create_table(
        "conversations",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("message_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("idx_conversations_user", "conversations", ["user_id"])

    # 2. Drop old agent_conversations (zero rows — safe to recreate)
    op.drop_table("agent_conversations")

    # 3. Recreate as multi-turn archive
    op.create_table(
        "agent_conversations",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("conversation_id", UUID(as_uuid=True), sa.ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("tools_used", JSONB(), nullable=True),
        sa.Column("reasoning_steps", JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("idx_agent_conversations_cid", "agent_conversations", ["conversation_id"])

def downgrade() -> None:
    # Reverse: drop new, restore old
    op.drop_index("idx_agent_conversations_cid", "agent_conversations")
    op.drop_table("agent_conversations")
    op.create_table(
        "agent_conversations",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("response", sa.Text(), nullable=True),
        sa.Column("tools_used", JSONB(), nullable=True),
        sa.Column("reasoning_steps", JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.drop_index("idx_conversations_user", "conversations")
    op.drop_table("conversations")
```

**Verification:** `alembic upgrade head` succeeds (after migration 0009). `alembic downgrade -1` succeeds. Check `conversations` and `agent_conversations` tables exist with correct schema in PostgreSQL.

**Risk:** Low. Table has zero rows in production — no data loss possible.

#### 1.6 Add config values

**File:** `backend/src/config.py`

Add to `Settings` class:

```python
# Agent
AGENT_MODEL_ID: str = "deepseek.v3-v1:0"              # DeepSeek V3.1 — agent inference
AGENT_JUDGE_MODEL_ID: str = "openai.gpt-5.4"           # GPT 5.4 — LLM-as-Judge
NLP_MODEL_ID: str = "anthropic.claude-haiku-4-5-20251001-v1:0"  # Claude Haiku 4.5 — NLP pipeline
AGENT_MAX_TOKENS: int = 4096
AGENT_TEMPERATURE: float = 0.1
AGENT_EVAL_SAMPLE_RATE: float = 0.1
AGENT_MAX_HISTORY_TURNS: int = 20
AGENT_REDIS_TTL: int = 604800          # 7 days — active session state TTL
AGENT_REDIS_KEY_PREFIX: str = "agent:session:"  # Redis key prefix
RATE_LIMIT_AGENT: str = "30/minute"    # Rate limit for agent chat endpoint
```

**Also update existing `BEDROCK_MODEL_ID`** (used by the NLP prediction pipeline) from Claude 3 Haiku to Claude Haiku 4.5:

```python
BEDROCK_MODEL_ID: str = "anthropic.claude-haiku-4-5-20251001-v1:0"  # NLP pipeline
```

**Verification:** `python -c "from src.config import settings; print(settings.AGENT_MODEL_ID)"` works. Also verify Redis connectivity: `python -c "from src.cache.redis import get_redis; import asyncio; asyncio.run(get_redis())"` succeeds.

**Risk:** Low.

---

### Round 2 — Agent Graph Engine

**Goal:** Working LangGraph graph with tool definitions that can be tested standalone.

#### 2.1 Create agent module structure

**Files:**

- `backend/src/agent/__init__.py` — docstring
- `backend/src/agent/schemas.py` — request/response models
- `backend/src/agent/repository.py` — asyncpg CRUD for sessions + messages
- `backend/src/agent/tools.py` — all agent tools
- `backend/src/agent/graph.py` — StateGraph definition
- `backend/src/agent/service.py` — AgentService singleton
- `backend/src/agent/router.py` — FastAPI endpoints (Round 3)

#### 2.2 Define agent schemas

**File:** `backend/src/agent/schemas.py`

```python
from __future__ import annotations
from datetime import datetime
from uuid import UUID
from pydantic import BaseModel, ConfigDict

class ChatRequest(BaseModel):
    message: str
    conversation_id: UUID | None = None  # None = new conversation

class ChatResponse(BaseModel):
    conversation_id: UUID
    message: str  # full response text

class ToolCallEvent(BaseModel):
    tool_name: str
    input: dict

class ToolResultEvent(BaseModel):
    tool_name: str
    output_summary: str
    success: bool

class SSEEvent(BaseModel):
    event: str  # "token" | "tool_start" | "tool_end" | "done" | "error"
    data: str   # JSON-encoded payload

class ConversationSummary(BaseModel):
    id: UUID
    title: str | None
    message_count: int
    created_at: datetime
    updated_at: datetime

class MessageResponse(BaseModel):
    role: str
    content: str
    tools_used: dict | None
    reasoning_steps: dict | None
    created_at: datetime
```

#### 2.3 Implement agent repository

**File:** `backend/src/agent/repository.py`

Module-level async functions following existing pattern:

**RDS functions:**

- `create_conversation(conn, user_id, title=None) -> UUID` — INSERT into `conversations`, returns id
- `get_user_conversations(conn, user_id, limit=20, offset=0) -> list[dict]` — list with pagination
- `get_conversation(conn, conversation_id, user_id) -> dict | None` — single conversation metadata
- `add_message(conn, conversation_id, user_id, role, content, tools_used=None) -> int` — INSERT into `agent_conversations`
- `get_conversation_messages(conn, conversation_id, limit=50) -> list[dict]` — ordered by created_at ASC
- `update_conversation_metadata(conn, conversation_id, message_count=None, title=None)` — bump counts
  - **Title auto-generation:** Set during the first turn in `process_message()` — uses first 50 characters of the user's first message. Logic: after creating the conversation, if `title` is still None, set `title = user_message[:50] + ("..." if len(user_message) > 50 else "")`.
- `delete_conversation(conn, conversation_id)` — cascades to messages via FK

**Redis helpers (core logic in `agent/service.py`):**

- Redis stores active session state as JSON hash: `agent:session:{conversation_id}`
- Keys: `state` (JSON-serialized LangGraph state), `user_id`, `message_count`, `updated_at`
- TTL: 7 days (refreshed on each turn — `AGENT_REDIS_TTL`)

**Data flow per turn:**

```
1. Router receives POST /agent/chat { message, conversation_id? }
2. No conversation_id → create conversation row (RDS)
3. If new conversation → auto-generate title from first 50 chars of user message
4. Try Redis GET agent:session:{id} for active state
5. On Redis miss → build state from RDS history
6. Run LangGraph astream_events with loaded state
7. After stream completes → _persist_turn():
   a. INSERT into agent_conversations (user message)
   b. INSERT into agent_conversations (assistant response + tools_used)
   c. UPDATE conversations (message_count, updated_at)
   d. SET agent:session:{id} in Redis with 7-day TTL refresh
```

**Verification:** Write a quick test that creates a conversation + adds messages + reads them back. Test Redis roundtrip.

**Risk:** Low. Standard CRUD + Redis pattern.

#### 2.4 Define agent tools

**File:** `backend/src/agent/tools.py`

16 tools organized by category (reduced from 19 after review — see `docs/goal_tool_review.md` for rationale). Each tool is a LangGraph `@tool` decorated async function. Tools call existing repository/provider functions or new endpoint logic.

**Critical: `user_id` injection via `InjectedToolArg`** — the LLM cannot know the user's ID. Mark `user_id` as runtime-injected so `ToolNode` skips it during schema extraction. `ToolNode` auto-populates injected args from the agent state when the state schema includes a matching key — `AgentState` has `user_id: str`, so no explicit `tool.bind()` is needed.

**Pattern:**

```python
from langchain_core.tools import tool
from typing import Annotated
from langgraph.prebuilt import InjectedToolArg

@tool
async def get_portfolio_holdings(
    portfolio_id: str,
    user_id: Annotated[str, InjectedToolArg],
) -> str:
    """Fetch current holdings for a portfolio. Use this when the user asks about what they own, their positions, or portfolio composition.
    Args:
        portfolio_id: UUID of the portfolio
    Returns:
        JSON string with holdings data"""
    # Call existing repository
    async with connection_ctx() as conn:
        rows = await holdings_repo.get_holdings(conn, portfolio_id, user_id)
    return json.dumps(rows, default=str)
```

**Tool inventory (16 tools — see `docs/goal_tool_review.md` for cuts/merges rationale):**

| #   | Tool                                  | Category    | Data Source                   | Notes                                                               |
| --- | ------------------------------------- | ----------- | ----------------------------- | ------------------------------------------------------------------- |
| 1   | `get_portfolio_summary`               | Portfolio   | `portfolios` repo             | Existing wrap                                                       |
| 2   | `get_portfolio_holdings`              | Portfolio   | `holdings` repo               | Existing wrap                                                       |
| 3   | `get_portfolio_performance`           | Performance | `performance` repo            | **Merged** with `get_portfolio_history` via `include_history` param |
| 4   | `compare_to_benchmark`                | Performance | `performance` repo            | Existing wrap                                                       |
| 5   | `get_sector_exposure`                 | Portfolio   | NEW — sector aggregation      | New endpoint                                                        |
| 6   | `get_portfolio_diversification_score` | Analysis    | NEW — HHI diversification     | New endpoint — **top differentiator**                               |
| 7   | `get_market_ohlcv`                    | Market Data | `market` repo                 | Existing wrap                                                       |
| 8   | `get_market_quote`                    | Market Data | `market` provider             | Existing wrap                                                       |
| 9   | `get_ticker_info`                     | Market Data | NEW — yfinance profile        | New endpoint                                                        |
| 10  | `get_market_news`                     | Market Data | NEW — yfinance news           | New endpoint — ⚠️ yfinance news is limited/stale                    |
| 11  | `get_lstm_forecast`                   | Forecasting | `prediction` service          | Existing wrap                                                       |
| 12  | `get_spending_analysis`               | Spending    | NEW — transaction aggregation | New endpoint — **strong diff**                                      |
| 13  | `get_recent_transactions`             | Spending    | `transactions` repo           | Existing wrap                                                       |
| 14  | `get_cash_flow_summary`               | Spending    | `cash_flows` repo             | ❓ Check if redundant with `get_portfolio_summary` cash balance     |
| 15  | `compare_tickers_side_by_side`        | Analysis    | NEW — multi-ticker comparison | New endpoint                                                        |
| 16  | `get_dividend_insights`               | Insights    | NEW — dividend data           | New endpoint                                                        |

**Cut from v1 (see `docs/goal_tool_review.md`):**

- `get_ticker_screening` — yfinance cannot screen tickers; requires third-party data API
- `get_drift_metrics` — MLOps metric, no user will ask about it
- `get_portfolio_history` — merged into `get_portfolio_performance(include_history=True)`

**Tool description template** (critical for correct LLM tool selection — follow this exactly for every tool):

```python
from langchain_core.tools import tool
from typing import Annotated
from langgraph.prebuilt import InjectedToolArg

@tool
async def tool_name(
    user_provided_param1: str,
    user_provided_param2: int,
    user_id: Annotated[str, InjectedToolArg],  # Injected by service, not by LLM
) -> str:
    """One-line: what this tool does.

    Use this when: {specific user question patterns the LLM should match against}.
    Returns: {what the response contains — be explicit about fields}.
    Limitations: {what it does NOT do, data staleness expectations, edge cases}.

    Complementary tools: {related tools the LLM should consider for related questions}.
    """
    ...
```

The **Complementary tools** field is non-standard for LangGraph tools but essential here — three portfolio tools (`get_portfolio_summary`, `get_portfolio_performance`, `get_recent_transactions`) have overlapping surfaces. Cross-referencing helps the LLM disambiguate:

```
get_portfolio_summary:
  Use this when: "How's my portfolio?" "What's my portfolio worth?"
  Complementary tools: get_portfolio_performance (for return percentages over time)

get_portfolio_performance:
  Use this when: "What's my return?" "How did I perform last quarter?"
  Does NOT include: current value snapshot (use get_portfolio_summary).
```

**Risk:** Medium. Tool descriptions are the primary mechanism for correct tool selection. Precision here directly drives eval scores. Iterate based on eval results.

#### 2.5 Build agent graph

**File:** `backend/src/agent/graph.py`

```python
from typing import Annotated, Sequence, Literal
from typing_extensions import TypedDict
from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode, tools_condition, InjectedToolArg
from langchain_core.messages import BaseMessage, SystemMessage, HumanMessage
from langchain_aws import ChatBedrockConverse
from src.config import settings

class AgentState(TypedDict):
    messages: Annotated[Sequence[BaseMessage], add_messages]
    user_id: str

def create_agent_graph(tools: list) -> StateGraph:
    """Build and return the compiled agent graph.

    Uses DeepSeek V3.1 (via Bedrock Converse API) — supports tool use.
    No checkpointer: state persistence is handled manually via two-tier Redis+RDS.
    """
    model = ChatBedrockConverse(
        model=settings.AGENT_MODEL_ID,  # deepseek.v3-v1:0
        max_tokens=settings.AGENT_MAX_TOKENS,
        temperature=settings.AGENT_TEMPERATURE,
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
        tools_condition,  # built-in: routes to "tools" if tool_calls present, else END
    )
    graph.add_edge("tools", "agent")
    graph.add_edge(START, "agent")
    return graph
```

**Why this approach:**

- Uses `bind_tools()` on `ChatBedrockConverse` (supported by langchain-aws for Claude models)
- Uses `ToolNode` from langgraph.prebuilt for tool execution
- Uses `tools_condition` for the conditional edge (built-in, reduces boilerplate)
- Function returns the graph, compile happens in service.py

**Note on state schema:** Using `TypedDict` with `Annotated` for the `add_messages` reducer — this is the recommended pattern for LangGraph chat agents.

#### 2.6 Build agent service — Two-tier persistence

**File:** `backend/src/agent/service.py`

Key difference from standard LangGraph patterns: **no `MemorySaver` or `AsyncPostgresSaver`**. State persistence is handled manually via custom Redis (hot) + RDS (cold) tiers.

```python
import json
import asyncio
from uuid import UUID
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage
from src.config import settings
from src.agent.graph import create_agent_graph
from src.agent.tools import get_all_tools
from src.agent import repository as agent_repo
from src.database.connection import connection_ctx
from src.cache.redis import get_redis

# Persona prompt
PERSONA_PROMPT = """You are a professional financial analysis assistant. You help users understand their portfolio, spending, and market data.

Rules:
1. Answer ONLY from the data returned by your tools. Never invent numbers, prices, or ticker data.
2. If a tool fails or returns no data, say so clearly and provide whatever partial answer you can.
3. Cite your sources where possible (e.g., "According to your portfolio data...").
4. If asked about something outside your capabilities, explain what you cannot do.
5. Never execute trades, modify portfolios, or take any action on the user's behalf — you analyze only.
6. Keep responses concise and professional. Use bullet points for multiple data points.
7. If the user asks about a ticker or portfolio you don't have access to, say so."""

class AgentService:
    """Singleton agent service. Compiled graph + two-tier persistence reused across all conversations."""

    def __init__(self):
        self.graph = None  # No checkpointer — manual persistence
        self._eval_tasks: set[asyncio.Task] = set()  # Strong refs to prevent GC of eval tasks

    def initialize(self):
        """Load tools and compile graph. Called at app startup."""
        tools = get_all_tools()
        graph = create_agent_graph(tools)
        self.graph = graph.compile()  # No checkpointer arg — thread_id in config is vestigial

    async def _load_state(self, conversation_id: UUID, user_id: str) -> list:
        """Load conversation state — try Redis (hot), fall back to RDS (cold).

        Returns list of BaseMessage-compatible dicts for graph input.
        """
        redis_key = f"{settings.AGENT_REDIS_KEY_PREFIX}{conversation_id}"

        # Tier 1: Redis (hot)
        try:
            redis = await get_redis()
            state_json = await redis.hget(redis_key, "state")
            if state_json:
                return json.loads(state_json)
        except Exception:
            pass  # Fall through to RDS

        # Tier 2: RDS (cold) — build from archived messages
        async with connection_ctx() as conn:
            rows = await agent_repo.get_conversation_messages(
                conn, conversation_id, settings.AGENT_MAX_HISTORY_TURNS
            )

        state = [SystemMessage(content=PERSONA_PROMPT)]
        for row in rows:
            if row["role"] == "user":
                state.append(HumanMessage(content=row["content"]))
            elif row["role"] == "assistant":
                state.append(AIMessage(content=row["content"]))

        # Seed Redis with loaded state
        try:
            redis = await get_redis()
            serialized = [self._serialize_msg(m) for m in state]
            await redis.hset(redis_key, mapping={
                "state": json.dumps(serialized),
                "user_id": str(user_id),
                "message_count": len(rows),
                "updated_at": "now",  # Overwritten on first refresh
            })
            await redis.expire(redis_key, settings.AGENT_REDIS_TTL)
        except Exception:
            pass  # Non-critical — state works from RDS alone

        return state

    def _serialize_msg(self, msg) -> dict:
        """Serialize a LangChain BaseMessage for JSON storage."""
        return {"role": msg.type, "content": msg.content}

    async def _persist_turn(
        self,
        conversation_id: UUID,
        user_id: str,
        user_message: str,
        final_state: dict,
        tools_used: list | None = None,
    ):
        """After graph completes: persist to both tiers.

        Tier 1 (Redis) — update active session state, refresh TTL.
        Tier 2 (RDS) — archive user message + assistant response.
        """
        redis_key = f"{settings.AGENT_REDIS_KEY_PREFIX}{conversation_id}"

        async with connection_ctx() as conn:
            # Archive user message
            await agent_repo.add_message(
                conn, conversation_id, user_id, "user", user_message
            )

            # Extract final assistant response
            last_msg = final_state.get("messages", [None])[-1]
            if last_msg:
                response_text = last_msg.content if hasattr(last_msg, "content") else str(last_msg)
                await agent_repo.add_message(
                    conn, conversation_id, user_id, "assistant", response_text,
                    tools_used=tools_used,
                )

            # Update conversation metadata
            await agent_repo.update_conversation_metadata(conn, conversation_id)

        # Refresh Redis state
        try:
            redis = await get_redis()
            # Load fresh state from RDS (avoids serialization issues with LangChain objects)
            async with connection_ctx() as conn:
                rows = await agent_repo.get_conversation_messages(
                    conn, conversation_id, settings.AGENT_MAX_HISTORY_TURNS
                )
            state = [SystemMessage(content=PERSONA_PROMPT)]
            for row in rows:
                if row["role"] == "user":
                    state.append(HumanMessage(content=row["content"]))
                elif row["role"] == "assistant":
                    state.append(AIMessage(content=row["content"]))

            serialized = [self._serialize_msg(m) for m in state]
            await redis.hset(redis_key, mapping={
                "state": json.dumps(serialized),
                "user_id": str(user_id),
                "updated_at": "now",
            })
            await redis.expire(redis_key, settings.AGENT_REDIS_TTL)
        except Exception:
            pass  # Redis miss is OK — next turn loads from RDS

    async def _run_eval_background(
        self,
        conversation_id: UUID,
        user_id: str,
        question: str,
        response_text: str,
        tools_used: list | None = None,
    ):
        """Fire-and-forget LLM-as-Judge evaluation. Holds strong ref in _eval_tasks to prevent GC."""
        task = asyncio.create_task(
            run_evaluation(conversation_id, user_id, question, response_text, tools_used)
        )
        self._eval_tasks.add(task)
        task.add_done_callback(self._eval_tasks.discard)

    async def process_message(
        self,
        conversation_id: UUID,
        user_id: str,
        message: str,
    ):
        """Run the agent graph with two-tier state management.

        Yields SSE-compatible event dicts for the router.
        Tools receive user_id via InjectedToolArg — ToolNode auto-injects from AgentState.
        """
        # Load state (Redis → RDS fallback)
        state = await self._load_state(conversation_id, user_id)

        # Append current message
        state.append(HumanMessage(content=message))

        # Build graph input
        graph_input = {"messages": state, "user_id": user_id}
        config = {"configurable": {"thread_id": str(conversation_id)}}  # thread_id is vestigial — no checkpointer

        # Track tool calls for persistence
        tools_used = []

        async for event in self.graph.astream_events(
            graph_input,
            config,
            version="v2",
        ):
            kind = event["event"]
            if kind == "on_chat_model_stream":
                chunk = event["data"]["chunk"]
                if hasattr(chunk, "content"):
                    yield {"event": "token", "data": chunk.content}
            elif kind == "on_tool_start":
                tools_used.append({"name": event["name"], "status": "started"})
                yield {"event": "tool_start", "data": event["name"]}
            elif kind == "on_tool_end":
                # Update status on completion
                for t in tools_used:
                    if t["name"] == event["name"] and t["status"] == "started":
                        t["status"] = "completed"
                yield {"event": "tool_end", "data": event["name"]}
            elif kind == "on_chain_end" and event["name"] == "LangGraph":
                final_state = event["data"]["output"]
                # Async persist to both tiers
                await self._persist_turn(
                    conversation_id, user_id, message, final_state, tools_used
                )
                # Fire-and-forget evaluation (with strong ref to prevent GC)
                if random.random() < settings.AGENT_EVAL_SAMPLE_RATE:
                    await self._run_eval_background(
                        conversation_id, user_id, message,
                        final_state.get("messages", [None])[-1].content if final_state.get("messages") else "",
                        tools_used,
                    )

# Module-level singleton — imported by router
agent_service = AgentService()
```

**Why not MemorySaver?** LangGraph's built-in checkpointer keeps state in process memory or Postgres. Process memory dies on restart. Postgres (via `AsyncPostgresSaver`) creates its own opaque tables — we already have `conversations` + `agent_conversations` for user-facing history. Two-tier gives us:

- Redis: fast session resume across ECS tasks sharing ElastiCache
- RDS: permanent archive queryable by the user-facing history endpoint
- No dependency on `langgraph-checkpoint-postgres` (one less dependency)
- Clean separation: Redis for active state, RDS for permanent records

**CV story:** _"LangGraph's MemorySaver keeps state in process memory — works for a demo, dies on restart. I designed a two-tier persistence layer: Redis for fast session resume across ECS tasks sharing ElastiCache, RDS for permanent conversation history. Active conversations survive container restarts, and every message is durably archived."_

#### 2.7 Wire AgentService into app startup

**File:** `backend/src/main.py`

In the app lifespan, after prediction service loads:

```python
from src.agent.service import agent_service  # Module-level singleton
agent_service.initialize()  # Compiles graph once at startup
```

The singleton `agent_service` is defined at module level in `backend/src/agent/service.py` — this is what `router.py` imports.

Also register the agent router:

```python
from src.agent.router import router as agent_router
app.include_router(agent_router, prefix="/agent", tags=["agent"])
```

---

### Round 3 — Agent API Endpoints

**Goal:** Working chat endpoint with SSE streaming, plus history APIs.

#### 3.1 Chat streaming endpoint

**File:** `backend/src/agent/router.py`

```python
import json
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from src.auth.dependencies import get_current_user
from src.auth.schemas import UserInDB
from src.limiter import limiter
from src.agent.service import agent_service  # Module-level singleton (compiled at startup)
from src.agent.schemas import ChatRequest
from src.agent import repository as agent_repo
from src.database.connection import connection_ctx

router = APIRouter()

@router.post("/chat")
@limiter.limit(settings.RATE_LIMIT_AGENT)  # "30/minute" — defined in config.py
async def chat(
    request: Request,
    body: ChatRequest,
    current_user: UserInDB = Depends(get_current_user),
):
    """Streaming chat endpoint. Returns SSE events.

    Two-tier state management:
    1. conversation_id provided → load from Redis (hot) or RDS (cold)
    2. No conversation_id → create new conversation row in RDS
    """

    # Resolve or create conversation
    conversation_id = body.conversation_id
    async with connection_ctx() as conn:
        if conversation_id:
            conv = await agent_repo.get_conversation(conn, conversation_id, current_user.id)
            if not conv:
                raise HTTPException(status_code=404, detail="Conversation not found")
        else:
            conversation_id = await agent_repo.create_conversation(conn, current_user.id)

    async def event_generator():
        try:
            full_response = ""
            async for event in agent_service.process_message(conversation_id, current_user.id, body.message):
                if event["event"] == "token":
                    full_response += event["data"]
                yield f"event: {event['event']}\ndata: {json.dumps(event['data'])}\n\n"

            yield f"event: done\ndata: {json.dumps({'conversation_id': str(conversation_id), 'full_response': full_response})}\n\n"
        except Exception as e:
            yield f"event: error\ndata: {json.dumps({'error': str(e)})}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
```

**SSE event types:**

| Event        | Data                               | Description                      |
| ------------ | ---------------------------------- | -------------------------------- |
| `token`      | `string`                           | A text chunk of the response     |
| `tool_start` | `string`                           | Tool name that started executing |
| `tool_end`   | `string`                           | Tool name that completed         |
| `done`       | `{conversation_id, full_response}` | Stream complete                  |
| `error`      | `{error}`                          | An error occurred                |

#### 3.2 Conversation history endpoints

**File:** `backend/src/agent/router.py` (same file)

```python
@router.get("/conversations")
async def list_conversations(
    request: Request,
    current_user: UserInDB = Depends(get_current_user),
    limit: int = 20,
    offset: int = 0,
):
    """List user's conversations (lightweight — no message bodies)."""
    async with connection_ctx() as conn:
        conversations = await agent_repo.get_user_conversations(conn, current_user.id, limit, offset)
    return {"conversations": conversations}

@router.get("/conversations/{conversation_id}")
async def get_conversation(
    request: Request,
    conversation_id: UUID,
    current_user: UserInDB = Depends(get_current_user),
):
    """Get full message history for a conversation."""
    async with connection_ctx() as conn:
        conv = await agent_repo.get_conversation(conn, conversation_id, current_user.id)
        if not conv:
            raise HTTPException(status_code=404, detail="Conversation not found")
        messages = await agent_repo.get_conversation_messages(conn, conversation_id)
    return {"conversation": conv, "messages": messages}

@router.delete("/conversations/{conversation_id}", status_code=204)
async def delete_conversation(
    request: Request,
    conversation_id: UUID,
    current_user: UserInDB = Depends(get_current_user),
):
    """Delete a conversation and all its messages (cascaded via FK)."""
    async with connection_ctx() as conn:
        conv = await agent_repo.get_conversation(conn, conversation_id, current_user.id)
        if not conv:
            raise HTTPException(status_code=404, detail="Conversation not found")
        await agent_repo.delete_conversation(conn, conversation_id)
```

**Note:** Redis state (`agent:session:{id}`) naturally expires via TTL when conversations are deleted. No explicit Redis cleanup needed.

**Verification:** curl the `/agent/chat` endpoint with a Bearer token. Verify SSE stream with token events. Test conversation CRUD.

**Risk:** Medium. SSE streaming on Fargate needs proper configuration (already existing from Phase 5 ALB setup — verify no buffering issues).

---

### Round 4 — New Tool Endpoints

**Goal:** 7 new dedicated backend endpoints for agent tools that don't have existing equivalents (ticker_screening cut from v1 — see `docs/goal_tool_review.md`).

Each endpoint follows existing module pattern. Putting them inside `src/agent/` keeps things simple (no need to create new module directories).

**File:** `backend/src/agent/tool_endpoints.py`

#### 4.1 `GET /agent/spending-analysis/{portfolio_id}`

Aggregate transactions by category over a date range. Returns:

- Total spend per category
- Category breakdown with percentages
- Month-over-month change
- Top spending categories

Data source: `transactions` table, grouped by `spending_category_id` → `spending_categories`.

```python
async def get_spending_analysis(conn, portfolio_id, user_id, months=6):
    """Aggregate transaction spending by category for a portfolio."""
    query = """
        SELECT
            sc.name as category,
            sc.id as category_id,
            COUNT(t.id) as transaction_count,
            SUM(t.total_amount) as total_spend
        FROM transactions t
        LEFT JOIN spending_categories sc ON t.spending_category_id = sc.id
        JOIN portfolios p ON t.portfolio_id = p.id
        WHERE t.portfolio_id = $1 AND p.user_id = $2
          AND t.transaction_date >= NOW() - ($3 || ' months')::INTERVAL
        GROUP BY sc.name, sc.id
        ORDER BY total_spend DESC
    """
    rows = await conn.fetch(query, portfolio_id, user_id, str(months))
    return [dict(r) for r in rows]
```

**Verification:** Test with known portfolio transactions. Confirm SQL correctness.

#### 4.2 `GET /agent/ticker-info/{ticker}`

Company profile, fundamentals, sector/industry. Uses yfinance `Ticker.info`.
Wraps existing market provider pattern.

**Verification:** `curl /agent/ticker-info/AAPL` returns JSON with company name, sector, industry, market cap, PE ratio, dividend yield, 52-week high/low.

#### 4.3 `GET /agent/market-news?tickers=AAPL,MSFT`

Recent news headlines for given tickers. Uses yfinance `Ticker.news`.
Returns: title, publisher, link, summary, timestamp per article.

**Verification:** `curl /agent/market-news?tickers=AAPL` returns 3-5 recent news items.

#### 4.4 `GET /agent/sector-exposure/{portfolio_id}`

Sector allocation of portfolio holdings. Maps each holding's ticker to a sector (via yfinance info), then aggregates by sector.

Returns: sector name, total value, percentage of portfolio.

**Verification:** Compare with sector breakdown on PortfolioDetailScreen.

#### 4.5 `GET /agent/diversification-score/{portfolio_id}`

Computes a diversification score (0-100) based on:

- Number of holdings (20%)
- Sector concentration via Herfindahl-Hirschman Index (40%)
- Top holding weight (20%)
- Correlation between top holdings (20%) — simplified: use sector diversity as proxy

Returns: overall score, breakdown by factor, recommendations.

**Verification:** Single-holding portfolio scores low (~20). Well-diversified portfolio scores high (~80+).

#### 4.6 `GET /agent/dividend-insights/{ticker}`

Dividend data for a ticker: yield, payout ratio, dividend growth rate, ex-dividend date, payment date. Uses yfinance.

**Verification:** Compare with known dividend stocks (e.g., KO, JNJ).

#### 4.7 `POST /agent/compare-tickers`

Side-by-side comparison:

```json
{
  "tickers": ["AAPL", "MSFT", "GOOGL"],
  "metrics": ["pe_ratio", "market_cap", "dividend_yield", "revenue_growth"]
}
```

Returns a matrix of ticker × metric.

---

### Round 5 — LangSmith-Native Evaluation (replaces custom evaluator)

**Goal:** LLM-as-Judge evaluation using LangSmith's built-in datasets, evaluators, and experiment runner. No custom DB table, no migration, no custom eval prompt — LangSmith stores scores per trace natively.

**Why LangSmith over custom RDS:**

- Built-in A/B comparison UI (compare DeepSeek vs GPT runs)
- Dataset management UI (golden questions, no admin panel)
- Built-in LLM-as-Judge evaluators (correctness, relevance)
- Auto-run experiments on every deploy
- Feedback API for user thumbs up/down from chat UI

**Prerequisites (must already exist — see Round 4 verification):**

- `langchain-aws`, `langgraph`, `langchain-core` are installed and the graph compiles via `create_agent_graph(tools).compile()` in `agent/graph.py`.
- `PERSONA_PROMPT` is defined in `src/agent/service.py` (imported, not re-declared, in the runner).
- `AgentState` carries `user_id` (so the non-streaming eval run executes identically to live traffic).
- `config.py` exposes `LANGCHAIN_TRACING_V2`, `LANGCHAIN_API_KEY`, `LANGCHAIN_PROJECT`, and `AGENT_EVAL_SAMPLE_RATE`.
- `secrets.LANGSMITH_API_KEY` exists in GitHub (reused by `eval.yml` — see Round 5.6).

**File changes:**

- **NEW:** `backend/agent_eval/__init__.py` — package marker
- **NEW:** `backend/agent_eval/run_experiment.py` — experiment runner script (LangSmith `evaluate()` + built-in LLM-as-Judge evaluators)
- **NEW:** `backend/agent_eval/golden_dataset.json` — 20–30 test cases
- **NEW:** `backend/agent_eval/upload_dataset.py` — idempotent dataset upload (`get_or_create_dataset`)
- **MODIFIED:** `backend/src/agent/service.py` — replace `_run_eval_background` body with LangSmith feedback logging (delete the dangling `src.agent.evaluator` import)
- **MODIFIED:** `backend/src/agent/router.py` — add `POST /agent/feedback` route (user thumbs up/down)
- **NEW:** `backend/tests/test_agent_eval.py` — unit tests for the eval pipeline + feedback route
- **NEW:** `backend/pyproject.toml` — add `langsmith>=0.3.0` to dependencies
- **NEW:** `.github/workflows/eval.yml` — CI workflow to run experiments (MANDATORY — runs on push to `main`)

#### 5.1 Create golden dataset

**File:** `backend/agent_eval/golden_dataset.json`

A JSON array of test cases. Each entry:

```json
{
  "question": "What's my portfolio worth?",
  "expected_tools": ["get_portfolio_summary"],
  "expected_response_contains": ["market value", "total"],
  "difficulty": "easy",
  "category": "portfolio"
}
```

Coverage: 20–30 entries across categories (portfolio, performance, market data, spending, forecasting, edge cases).

#### 5.2 Upload dataset to LangSmith (idempotent)

**File:** `backend/agent_eval/upload_dataset.py`

Runs one-time or via CI on dataset change. Uses `get_or_create_dataset` so re-runs are idempotent (no duplicate examples):

```python
"""Idempotently upload the golden dataset to LangSmith.

Usage:
    python -m agent_eval.upload_dataset
"""
import json
from pathlib import Path

from langsmith import Client

DATASET_NAME = "stocklens-golden"
DATASET_PATH = Path(__file__).parent / "golden_dataset.json"


def main() -> None:
    client = Client()
    dataset = client.get_or_create_dataset(
        dataset_name=DATASET_NAME,
        description="Golden eval set for StockLens agent",
    )
    questions = json.loads(DATASET_PATH.read_text())["questions"]
    # Idempotent: recreate examples fresh each upload (dataset is small).
    client.delete_examples(dataset_id=dataset.id)
    client.create_examples(
        dataset_id=dataset.id,
        inputs=[{"question": q["question"]} for q in questions],
    )
    print(f"Uploaded {len(questions)} examples to dataset '{DATASET_NAME}'")


if __name__ == "__main__":
    main()
```

#### 5.3 Create experiment runner

**File:** `backend/agent_eval/run_experiment.py`

A script that:

1. Loads the golden dataset from LangSmith
2. For each test case: runs the agent graph with the question (no streaming, no persistence)
3. Posts results back to LangSmith as an experiment run
4. Triggers LangSmith's built-in evaluators (correctness, relevance)

**Key difference from custom eval:** No need to score manually. LangSmith's evaluators score automatically. The script just runs the agent and records responses.

```python
"""Run the golden dataset through the agent and record results in LangSmith.

Usage:
    python -m agent_eval.run_experiment

Requires LANGCHAIN_API_KEY, LANGCHAIN_TRACING_V2=true, LANGCHAIN_PROJECT set.
"""
import asyncio

from langchain_core.messages import HumanMessage, SystemMessage
from langsmith import Client, evaluate
from langsmith.evaluation.evaluator import LangChainStringEvaluator

from src.agent.graph import create_agent_graph
from src.agent.service import PERSONA_PROMPT
from src.agent.tools import get_all_tools


async def run_agent(graph, inputs):
    """Run agent synchronously (no streaming) and return final response."""
    messages = [
        SystemMessage(content=PERSONA_PROMPT),
        HumanMessage(content=inputs["question"]),
    ]
    result = await graph.ainvoke({"messages": messages, "user_id": "eval"})
    return {"response": result["messages"][-1].content}


def target(inputs):
    tools = get_all_tools()
    graph = create_agent_graph(tools).compile()
    return asyncio.run(run_agent(graph, inputs))


def main():
    client = Client()
    ds = client.list_datasets(dataset_name="stocklens-golden")[0]

    # LangSmith's built-in LLM-as-Judge evaluators score each run automatically.
    evaluators = [
        LangChainStringEvaluator("criteria", config={"criteria": "correctness"}),
        LangChainStringEvaluator("criteria", config={"criteria": "relevance"}),
    ]

    results = evaluate(
        target,
        data=ds,
        evaluators=evaluators,
        experiment_prefix="stocklens-agent",
    )
    print(f"Experiment {results.experiment_id} complete")


if __name__ == "__main__":
    main()
```

> **Note:** An empty `evaluators=[]` (as in the prior draft) would run the agent but produce no scores. The built-in LLM-as-Judge evaluators must be passed explicitly — here `correctness` and `relevance` via `LangChainStringEvaluator`.

#### 5.4 User feedback integration (live-traffic sampling)

**File:** `backend/src/agent/service.py`

`_run_eval_background` already exists (it imports the non-existent `src.agent.evaluator` and silently no-ops on `ImportError`). Replace its body to log a LangSmith feedback score against the current trace, and **delete the dangling `from src.agent import evaluator` import**. The composite-score / custom-evaluator logic is removed entirely — LangSmith stores scores natively.

```python
async def _run_eval_background(self, conversation_id, user_id, question, response_text, tools_used):
    """Fire-and-forget eval logging to LangSmith for sampled conversations."""
    from langsmith import Client

    try:
        client = Client()
        # Log a feedback keyed to the current run tree; LangSmith links it
        # to the trace automatically. No custom evaluator / RDS table.
        # No score is written here — this is a sampled-run marker only.
        # (Live automatic LLM-as-Judge scoring is out of scope for R5; see
        #  the live-traffic judge note in 5.4.)
        client.create_feedback(
            feedback_key="sampled_eval",
            comment=f"user={user_id} tools={tools_used}",
            feedback_source_type="app",
            source_metadata={"conversation_id": str(conversation_id)},
        )
    except Exception as exc:  # eval must never break the response path
        logger.warning("LangSmith feedback logging failed: %s", exc)
```

The sampling gate that calls this method stays as-is (driven by `AGENT_EVAL_SAMPLE_RATE`); the existing `TestEvalSampling` test (which mocks `_run_eval_background` and asserts it fires on sample) continues to pass unchanged.

**File:** `backend/src/agent/router.py`

Add a user feedback route so the chat UI can send thumbs up/down with a trace ID:

```python
@router.post("/feedback")
async def agent_feedback(payload: AgentFeedbackRequest, user=Depends(get_current_user)):
    """Record a user feedback score against a LangSmith trace."""
    from langsmith import Client

    client = Client()
    client.create_feedback(
        feedback_key=payload.rating,  # e.g. "thumbs_up" / "thumbs_down"
        trace_id=payload.trace_id,
        feedback_source_type="app",
        source_metadata={"user_id": str(user.id)},
    )
    return {"status": "ok"}
```

#### 5.5 Unit tests for the eval pipeline

**File:** `backend/tests/test_agent_eval.py`

Covers the new surface so the pipeline is verifiable offline (no real LangSmith calls):

- `test_upload_dataset_idempotent` — `get_or_create_dataset` is called; examples are created.
- `test_run_experiment_target` — `target()` invokes `create_agent_graph(...).compile()` and returns `{"response": ...}` for a fixture question (mock `get_all_tools` + graph `ainvoke`).
- `test_run_agent_builds_messages` — assert the message list starts with `SystemMessage(PERSONA_PROMPT)` then the `HumanMessage`.
- `test_feedback_route` — `POST /agent/feedback` calls `Client.create_feedback` and returns `{"status": "ok"}` (mock `Client`).
- `test_eval_background_logs_feedback` — `_run_eval_background` calls `create_feedback` **without a score** (sampled-run marker) and swallows exceptions on failure.

#### 5.6 CI experiment workflow

**File:** `.github/workflows/eval.yml`

Triggers on push to `main` (after deploy) and manual dispatch. Uses `uv` (the repo's package manager — backend is the `stocklens-backend` workspace package, installed via `uv sync --package stocklens-backend --all-extras`, **not** `pip install -e backend/`) and AWS OIDC credentials (the agent calls Bedrock, so CI needs AWS auth). `secrets.LANGSMITH_API_KEY` is remapped to `LANGCHAIN_API_KEY`. The job is **mandatory** but `continue-on-error` keeps a LangSmith/network outage from blocking the deploy pipeline.

```yaml
name: Agent Eval
on:
  workflow_dispatch:
  push:
    branches: [main]
    paths: ['backend/src/agent/**', 'backend/agent_eval/**']

permissions:
  id-token: write # AWS OIDC
  contents: read

jobs:
  run-experiment:
    runs-on: ubuntu-latest
    continue-on-error: true # eval failure must not block deploy
    steps:
      - uses: actions/checkout@v5
      - uses: actions/setup-python@v6
      - name: Install uv
        uses: astral-sh/setup-uv@v5
      - name: Configure AWS credentials (Bedrock access)
        uses: aws-actions/configure-aws-credentials@v6
        with:
          role-to-assume: ${{ secrets.ECS_DEPLOY_ROLE_ARN }}
          aws-region: eu-west-2
      - name: Sync backend with extras
        run: uv sync --package stocklens-backend --all-extras
      - name: Upload golden dataset
        run: uv run --package stocklens-backend python -m agent_eval.upload_dataset
        env:
          LANGCHAIN_API_KEY: ${{ secrets.LANGSMITH_API_KEY }}
          LANGCHAIN_TRACING_V2: 'true'
          LANGCHAIN_PROJECT: stocklens-eval
      - name: Run LangSmith experiment
        run: uv run --package stocklens-backend python -m agent_eval.run_experiment
        env:
          LANGCHAIN_API_KEY: ${{ secrets.LANGSMITH_API_KEY }}
          LANGCHAIN_TRACING_V2: 'true'
          LANGCHAIN_PROJECT: stocklens-eval
```

**Files dropped from original plan:**

- ❌ No `schema.py` addition for `agent_evaluations` table
- ❌ No migration `0011_agent_evaluations.py`
- ❌ No `evaluator.py` file (replaced by LangSmith's built-in evaluators)
- ❌ No `EVAL_PROMPT` custom prompt
- ❌ No `evaluation_service.py`
- ❌ No composite score computation in Python

**Risk:** Low. LangSmith evaluation is fire-and-forget via the `evaluate()` SDK. The CI workflow runs offline (no impact on production traffic). If LangSmith is down, the experiment fails non-critically (`continue-on-error`) — agent continues serving and the deploy proceeds.

---

### Round 6 — Frontend Chat UI

**Goal:** Users can tap an AI chat button on the Portfolio screen and converse with the agent via a modal.

#### 6.1 Create agent chat service

**File:** `frontend/src/services/agent.ts`

```typescript
import { apiService } from './api';

const API_BASE = process.env.EXPO_PUBLIC_API_URL || 'http://localhost:8000';

export interface AgentMessage {
  role: 'user' | 'assistant';
  content: string;
  toolCalls?: any[];
  toolResults?: any[];
  createdAt: string;
}

export interface ConversationSummary {
  id: string;
  title: string | null;
  messageCount: number;
  createdAt: string;
  updatedAt: string;
}

export const agentService = {
  async sendMessage(
    message: string,
    conversationId?: string,
    onToken?: (token: string) => void,
    onToolStart?: (toolName: string) => void,
    onToolEnd?: (toolName: string) => void,
  ): Promise<{ conversationId: string; fullResponse: string }> {
    const token = await SecureStore.getItemAsync('stocklens_access_token');
    const response = await fetch(`${API_BASE}/agent/chat`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${token}`,
      },
      body: JSON.stringify({ message, conversation_id: conversationId || null }),
    });

    if (!response.ok) {
      throw new Error(`Chat request failed: ${response.status}`);
    }

    const reader = response.body!.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    let fullResponse = '';
    let resolvedConversationId = conversationId || '';
    let currentEvent = ''; // Track current SSE event type

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split('\n');
      buffer = lines.pop() || '';

      for (const line of lines) {
        if (line.startsWith('event: ')) {
          currentEvent = line.slice(7).trim();
        } else if (line.startsWith('data: ')) {
          const data = JSON.parse(line.slice(6));
          switch (currentEvent) {
            case 'token':
              fullResponse += data;
              onToken?.(data);
              break;
            case 'tool_start':
              onToolStart?.(data);
              break;
            case 'tool_end':
              onToolEnd?.(data);
              break;
            case 'done':
              resolvedConversationId = data.conversation_id;
              break;
            case 'error':
              throw new Error(data.error);
          }
          currentEvent = ''; // Reset after consuming
        }
      }
    }

    return { conversationId: resolvedConversationId, fullResponse };
  },

  async listConversations(): Promise<ConversationSummary[]> {
    return apiService.get('/agent/conversations');
  },

  async getConversation(
    conversationId: string,
  ): Promise<{ conversation: ConversationSummary; messages: AgentMessage[] }> {
    return apiService.get(`/agent/conversations/${conversationId}`);
  },

  async deleteConversation(conversationId: string): Promise<void> {
    return apiService.delete(`/agent/conversations/${conversationId}`);
  },
};
```

**Note:** The SSE parser uses a `currentEvent` tracker to associate `event:` lines with the subsequent `data:` line. This is the standard approach for manual SSE parsing. Use `EventSource` polyfill if available, but `fetch` + `ReadableStream` works on React Native.

**Risk:** Medium. SSE streaming from React Native needs testing. Different iOS/Android behavior with streaming responses.

#### 6.2 Create MessageBubble component

**File:** `frontend/src/components/chat/MessageBubble.tsx`

Simple functional component:

- User messages: right-aligned, primary background
- Assistant messages: left-aligned, surface background
- Shows tool indicators inline (small text below assistant messages)
- Supports long messages (scrollable within bubble)

#### 6.3 Create ToolIndicator component

**File:** `frontend/src/components/chat/ToolIndicator.tsx`

Animated indicator showing "Using [tool name]..." with a loading spinner. Disappears when tool completes.

#### 6.4 Create AgentChatScreen

**File:** `frontend/src/screens/AgentChatScreen.tsx`

Rendered as a `<Modal>` on the Portfolio screen. Contains:

- **Header:** "AI Assistant" title + close (X) button
- **Message list:** FlatList of MessageBubble components, auto-scrolls to bottom
- **Tool indicators:** Animated row during tool execution
- **Input bar:** TextInput + Send button at bottom
- **Empty state:** "Ask me anything about your portfolio..." when no messages

Follows the existing modal pattern from `ReceiptDetailsScreen.tsx`:

```tsx
<Modal visible={visible} transparent animationType="fade" onRequestClose={onClose}>
  <View style={styles.overlay}>
    <View style={[styles.card, { backgroundColor: theme.background }]}>
      {/* Header, messages, input */}
    </View>
  </View>
</Modal>
```

State management:

```typescript
const [messages, setMessages] = useState<Message[]>([]);
const [input, setInput] = useState('');
const [isLoading, setIsLoading] = useState(false);
const [currentTool, setCurrentTool] = useState<string | null>(null);
const [conversationId, setConversationId] = useState<string | undefined>();
const flatListRef = useRef<FlatList>(null);
```

#### 6.5 Add AI chat button to Portfolio screen

**File:** `frontend/src/screens/portfolio/PortfolioListScreen.tsx`

**Add import:** `import { Ionicons } from '@expo/vector-icons';` at the top of the file along with existing imports.

In the header View alongside the existing `+` FAB:

```tsx
<View style={[styles.header, { backgroundColor: theme.background }]}>
  <Text style={[styles.title, { color: theme.text }]}>My Portfolios</Text>
  <View style={styles.headerActions}>
    <TouchableOpacity
      style={[styles.chatBtn, { backgroundColor: theme.primary }]}
      onPress={() => setChatVisible(true)}
      hitSlop={{ top: 8, bottom: 8, left: 8, right: 8 }}
    >
      <Ionicons name="chatbubble-ellipses" size={20} color="#fff" />
    </TouchableOpacity>
    <TouchableOpacity
      style={[styles.fab, { backgroundColor: theme.primary }]}
      onPress={() => navigation.navigate('CreatePortfolio')}
      hitSlop={{ top: 8, bottom: 8, left: 8, right: 8 }}
    >
      <Text style={styles.fabText}>+</Text>
    </TouchableOpacity>
  </View>
</View>
```

Add modal state and render:

```tsx
const [chatVisible, setChatVisible] = useState(false);

// In JSX:
<AgentChatScreen visible={chatVisible} onClose={() => setChatVisible(false)} />;
```

**Verification:** Tap AI chat button → modal opens → type "Show me my portfolio performance" → see SSE stream → response displayed.

---

## Testing Strategy

### Unit Tests (backend)

| Test File                            | Tests                                                   | Coverage             |
| ------------------------------------ | ------------------------------------------------------- | -------------------- |
| `tests/test_agent_graph.py`          | Graph compilation, node execution, tool routing         | Agent graph logic    |
| `tests/test_agent_tools.py`          | Each tool's input/output schema, error handling         | All 16 tools         |
| `tests/test_agent_repository.py`     | CRUD operations on sessions/messages                    | Repository layer     |
| `tests/test_agent_eval.py`           | LangSmith eval pipeline, feedback route, dataset upload | Round 5 eval surface |
| `tests/test_agent_tool_endpoints.py` | 7 new endpoint responses                                | New endpoints        |

### Integration Tests

| Test               | Description                                       |
| ------------------ | ------------------------------------------------- |
| Chat streaming     | Full chat flow: send message → receive SSE events |
| Session management | Create, list, get, delete sessions                |
| Auth gating        | Unauthenticated requests rejected                 |
| Ownership scoping  | User A cannot see User B's sessions               |

### E2E Tests (frontend)

| Test                | Description                                       |
| ------------------- | ------------------------------------------------- |
| Chat button appears | Portfolio screen shows AI chat button             |
| Modal opens/closes  | Tap button → modal visible → close → modal hidden |
| Send message        | Type message → tap send → see response            |
| History loads       | Old messages load when reopening session          |

---

## Success Criteria

- [ ] All 475 existing backend tests still pass
- [ ] New tests for graph, tools, repository, agent_eval, tool endpoints
- [ ] LangGraph graph compiles and runs end-to-end
- [ ] SSE streaming works from FastAPI → React Native modal
- [ ] All agent tools (16) return correct data for valid inputs
- [ ] Tools fail gracefully with error messages (no crash)
- [ ] LangSmith-native evaluation: sampled conversations + golden-dataset experiments run and score
- [ ] `eval.yml` CI workflow runs on push to `main` (mandatory, non-blocking)
- [ ] Chat history is persisted and retrievable across sessions
- [ ] Auth gating: unauthenticated users cannot access agent endpoints
- [ ] Ownership scoping: users only see their own conversations
- [ ] "Cannot execute trades" is enforced by persona prompt + no tool capability

---

## Risks & Mitigations

| Risk                                                                    | Impact                                                                 | Likelihood | Mitigation                                                                                                                                                                                      |
| ----------------------------------------------------------------------- | ---------------------------------------------------------------------- | ---------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **LangGraph API changed between docs and execution**                    | Graph doesn't compile                                                  | Medium     | Pin `langgraph>=1.0.0,<2.0.0`. Refer to docs.langchain.com for current API.                                                                                                                     |
| **SSE streaming broken on iOS React Native**                            | No streaming in chat UI                                                | Medium     | Use `fetch` + `ReadableStream` (not EventSource). Test on iOS simulator early.                                                                                                                  |
| **Bedrock rate limits with streaming**                                  | Throttled responses                                                    | Low        | Add retry-with-backoff in tool calls. Agent runs on Haiku (cheap, fast).                                                                                                                        |
| **LLM hallucinates ticker data outside tool results**                   | Wrong financial info                                                   | Medium     | Persona prompt + tool descriptions explicitly forbid this. Evaluation catches it.                                                                                                               |
| **yfinance endpoints flaky**                                            | Tool returns empty data                                                | Medium     | Graceful degradation in persona prompt: "say what failed, provide partial answer."                                                                                                              |
| **Large conversation history hits context window**                      | Truncation/exceeded limits                                             | Low        | `AGENT_MAX_HISTORY_TURNS=20` limit. System truncation of oldest turns.                                                                                                                          |
| **Background eval tasks pile up under load**                            | Resource exhaustion                                                    | Low        | Random sampling (10%). `asyncio.create_task` has no backpressure — switch to bounded queue if needed.                                                                                           |
| **Redis connection failure on load/save**                               | State falls back to RDS-only                                           | Medium     | `_load_state` and `_persist_turn` already catch Redis exceptions. RDS path works without Redis — user sees no difference, but session resume after restart loses fast path until next RDS load. |
| **Redis memory exhaustion (many active sessions)**                      | Redis evicts old sessions before 7-day TTL                             | Low        | Each conversation state ~50KB JSON. 1000 concurrent sessions ≈ 50MB. ElastiCache default instance has GB+ capacity. Monitor via ElastiCache `evictions` metric.                                 |
| **Connection pool exhaustion from multi-tool turns**                    | asyncpg pool max_size=10 may starve with 3+ users × 3-4 tools per turn | Medium     | Pool size is per-task, not global. If multiple concurrent chat requests hit 3-4 tools each, increase pool max_size or use per-turn shared connection.                                           |
| **`asyncio.create_task` eval task garbage collected before completion** | Eval scores silently dropped                                           | Low        | Mitigated via `_eval_tasks` registry set with `add_done_callback` self-removal. Holds strong reference for task lifetime.                                                                       |
| **slowapi limiter may buffer SSE streaming response**                   | Streaming delayed until buffered                                       | Low        | Mitigation: apply rate limit at a higher granularity (per-user vs per-request) or use middleware-based rate limiting. Test SSE behavior with limiter in integration tests.                      |
| **Agent tests require Bedrock API calls**                               | Tests are slow, non-deterministic, and incur cost                      | Medium     | Use `pytest-mock` to mock `ChatBedrockConverse` and `langchain_aws` calls. Add explicit documentation that agent tests require mocking Bedrock — do not call real APIs in unit tests.           |

---

## Verification Checklist

### Before Round 1

- [ ] All Phase 5 backend tests pass: `cd backend && uv run pytest`
- [ ] `alembic current` shows `0008` as current revision
- [ ] **Delete orphan migration** `backend/alembic/versions/af46e8a08234_create_spending_and_prediction_tables.py` (second root migration — blocks `alembic upgrade head`)
- [ ] Verify only one head: `alembic heads` shows only `0008`
- [ ] Frontend builds: `cd frontend && npx expo export --platform web --output-dir /tmp/test-build 2>&1`

### After Round 1

- [ ] `langgraph` and `langchain-core` importable
- [ ] Migrations 0009+0010 applied: `alembic upgrade head`
- [ ] `conversations` and `agent_conversations` tables exist in PostgreSQL
- [ ] Config values accessible via `settings.AGENT_MODEL_ID`

### After Round 2

- [ ] Graph compiles without errors
- [ ] Each tool returns expected data for valid inputs
- [ ] Tools return error messages for invalid inputs (no crash)
- [ ] Graph routes correctly: agent → tools → agent → END

### After Round 3

- [ ] `curl -N` to `/agent/chat` returns SSE stream
- [ ] Session CRUD endpoints work with proper auth
- [ ] Ownership scoping enforced

### After Round 4

- [ ] All 7 new tool endpoints return valid JSON
- [ ] Spending analysis aggregates correctly
- [ ] Ticker info returns company data
- [ ] Diversification score is within expected range

### After Round 5

- [ ] `langsmith>=0.3.0` added to `backend/pyproject.toml` and synced
- [ ] `agent_eval/` package exists; golden dataset uploads idempotently
- [ ] `python -m agent_eval.run_experiment` runs and scores via LangSmith evaluators
- [ ] `_run_eval_background` logs LangSmith feedback (dangling `evaluator` import removed)
- [ ] `POST /agent/feedback` route deployed
- [ ] `eval.yml` runs on push to `main` (mandatory, `continue-on-error`)

### After Round 6

- [ ] AI chat button visible on Portfolio screen
- [ ] Chat modal opens/closes smoothly
- [ ] Messages stream in real-time
- [ ] Tool indicators shown during execution
- [ ] Conversation history persists across modal open/close
