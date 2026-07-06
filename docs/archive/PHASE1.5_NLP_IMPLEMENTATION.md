# Implementation Plan: NLP Cascade OCR System

## Overview

Add a confidence-gated cascade to the receipt OCR pipeline: fast regex parsing first, LLM escalation only when confidence is low. Per-field confidence scoring, discrepancy detection, background enrichment for slow LLM calls, and fuzzy merchant matching.

## Requirements

- Cascade: regex → confidence check → Bedrock Haiku escalation
- Per-field confidence (0.0–1.0) from both heuristic and LLM
- Discrepancy logging when heuristic and LLM disagree
- Background async enrichment when confidence < threshold
- Retry logic with backoff for transient LLM failures
- Graceful degradation: never lose a scan, flag degraded results
- Redis: LLM response cache, background job status, retry state
- 50–100 synthetic receipt eval dataset
- Fuzzy merchant matching via rapidfuzz
- Keep existing regex parsing working (no breaking changes)

## Architecture Changes

| File                                     | Change                                                                                            |
| ---------------------------------------- | ------------------------------------------------------------------------------------------------- |
| `backend/src/receipts/cascade.py`        | **NEW** — cascade orchestrator, per-field confidence, discrepancy detection                       |
| `backend/src/receipts/llm_extractor.py`  | **NEW** — Bedrock Haiku structured extraction (Pydantic output) with retry + cache                |
| `backend/src/receipts/cache.py`          | **NEW** — Redis wrapper for LLM cache + job status + retry state                                  |
| `backend/src/receipts/merchant_match.py` | **NEW** — rapidfuzz fuzzy merchant matching                                                       |
| `backend/src/receipts/models.py`         | **MODIFY** — add `FieldConfidence`, `CascadeResult`, `CascadeDecision` models                     |
| `backend/src/receipts/router.py`         | **MODIFY** — swap `process_receipt()` for cascade, add background enrichment, health check        |
| `backend/src/config.py`                  | **MODIFY** — add `REDIS_URL`, `CASCADE_CONFIDENCE_THRESHOLD`, `LLM_MAX_TOKENS`, `LLM_MAX_RETRIES` |
| `backend/alembic/versions/`              | **NEW** — migration for `cascade_decisions` table                                                 |
| `backend/tests/test_cascade.py`          | **NEW** — cascade logic tests                                                                     |
| `backend/tests/test_llm_extractor.py`    | **NEW** — LLM extractor tests (mocked Bedrock)                                                    |
| `backend/tests/eval_dataset.py`          | **NEW** — 50–100 synthetic receipts                                                               |
| `backend/pyproject.toml`                 | **MODIFY** — add `rapidfuzz` dependency                                                           |

## Data Structures

### FieldConfidence (Pydantic model)

```python
# backend/src/receipts/models.py — add to existing file

class FieldConfidence(BaseModel):
    """An extracted field with its confidence score."""
    value: str | float | list[dict] | None = None
    confidence: float  # 0.0 - 1.0
    source: Literal["regex", "llm"]

class CascadeResult(BaseModel):
    """Result of the cascade extraction pipeline."""
    extraction: ReceiptExtraction
    field_confidences: dict[str, FieldConfidence]  # {"merchant": ..., "total": ..., "date": ..., "items": ...}
    overall_confidence: float
    source: Literal["regex", "cascade", "degraded", "failed"]
    discrepancies: list[dict]  # [{"field": "merchant", "regex": "TESCO", "llm": "Tesco Express"}]
    raw_text: str
```

### LLM Extraction Response (Pydantic model for structured output)

```python
# backend/src/receipts/llm_extractor.py

class LLMExtractionResult(BaseModel):
    """Structured output from Bedrock Haiku extraction."""
    merchant_name: str | None = None
    total_amount: float | None = None
    date: str | None = None  # ISO format
    line_items: list[dict] = Field(default_factory=list)
    category: str | None = None
    confidence: dict[str, float] = Field(default_factory=dict)  # per-field confidence
```

## Failure Handling & Retry Strategy

### Three tiers of failure

| Scenario                                      | What happens                                         | User sees                                     |
| --------------------------------------------- | ---------------------------------------------------- | --------------------------------------------- |
| **Regex succeeds, no LLM needed**             | Return regex result immediately                      | Fast response (~100ms)                        |
| **Regex low confidence, LLM succeeds**        | Return merged result                                 | Slightly slower (~2s), higher quality         |
| **LLM transient failure (timeout, 5xx)**      | Retry 2x with backoff (1s, 2s) → fall back to regex  | Return regex result with `source: "degraded"` |
| **LLM permanent failure (4xx, invalid JSON)** | Skip LLM, return regex result                        | Return regex result with `source: "degraded"` |
| **Both layers fail**                          | Return whatever regex extracted + `source: "failed"` | User can edit fields manually in UI           |

### Key principle: never lose a scan

Every scan produces OCR text + regex extraction. Even if Bedrock is completely down, the user gets a result they can correct. The `source` field tells them what happened:

- `"regex"` — high confidence, no LLM needed
- `"pending_llm"` — low confidence, LLM enrichment in progress
- `"cascade"` — LLM enriched the result
- `"degraded"` — LLM failed, regex only
- `"failed"` — minimal extraction, needs manual correction

## Redis Integration

Redis (already in stack via the shared `ConnectionPool` in `backend/src/cache/redis.py`, initialised at app startup in `lifespan`) solves three problems. The new `backend/src/receipts/cache.py` **reuses this existing pool** — it does not create its own connection.

### 1. LLM Response Cache

- **Key**: `llm_cache:{sha256(raw_text)[:16]}`
- **Value**: JSON-serialized `LLMExtractionResult`
- **TTL**: 24 hours
- **Why**: Same OCR text → same LLM call. Avoids paying for duplicate Bedrock calls on retries/duplicates.
- **Implementation**: Check cache before Bedrock call, store on success.

### 2. Background Enrichment Status

- **Key**: `enrich_status:{receipt_id}`
- **Value**: `{status: "pending"|"done"|"failed", started_at, finished_at}`
- **TTL**: 1 hour
- **Why**: Client can poll `GET /receipts/{id}` and know if enrichment is still running.
- **Implementation**: Set `"pending"` before background task, `"done"`/`"failed"` after.

### 3. Retry State (dual-key)

Two scopes are tracked to prevent both per-receipt retry loops AND retry storms on identical OCR text across many receipts:

- **Per-receipt**: `retry_count:receipt:{receipt_id}` — integer, TTL 5 min
- **Per-text-hash**: `retry_count:hash:{sha256(raw_text)[:16]}` — integer, TTL 5 min
- **Why**: Per-receipt stops one receipt looping forever. Per-text-hash stops the same bad OCR text triggering 100s of LLM calls if many receipts come in with identical garbled text.
- **Implementation**: `increment_retry(scope, key_id)` increments the key `retry_count:{scope}:{key_id}` and returns the attempt count. The LLM extractor checks BOTH against `LLM_MAX_RETRIES` before each call.

## Implementation Steps

### Phase 1: Foundation (no behavioral change)

#### Step 1. Add `rapidfuzz` dependency

- **File**: `backend/pyproject.toml`
- **Action**: Add `"rapidfuzz>=3.0.0"` to `[project.dependencies]`
- **Why**: Needed for fuzzy merchant matching
- **Dependencies**: None
- **Risk**: Low

#### Step 2. Add config values

- **File**: `backend/src/config.py`
- **Action**: Add fields to `Settings`:
  ```python
  REDIS_URL: str = "redis://localhost:6379/0"
  CASCADE_CONFIDENCE_THRESHOLD: float = 0.7
  LLM_MAX_TOKENS: int = 1024
  LLM_MAX_RETRIES: int = 2
  LLM_RETRY_BACKOFF: float = 1.0  # seconds, doubles each retry
  LLM_CACHE_TTL: int = 86400  # 24 hours
  ENRICH_STATUS_TTL: int = 3600  # 1 hour
  ```
- **Why**: REDIS_URL for cache/status/retries; threshold controls LLM escalation; retries with backoff for transient failures
- **Dependencies**: None
- **Risk**: Low

#### Step 3. Add new Pydantic models

- **File**: `backend/src/receipts/models.py`
- **Action**: Add `FieldConfidence` and `CascadeResult` models at the end of the file
- **Why**: Shared data contracts for the cascade system
- **Dependencies**: None
- **Risk**: Low — additive only

#### Step 4. Reuse existing Redis connection pool

- **File**: `backend/src/receipts/cache.py` (NEW)
- **Action**: Create module that **reuses the existing `get_redis()` from `backend/src/cache/redis.py`** (already has a `ConnectionPool` initialised at app startup via lifespan). Do NOT create a lazy singleton — use the shared pool:

  ```python
  import hashlib
  import json

  from src.cache.redis import get_redis  # shared pool, initialised in lifespan


  def _text_hash(raw_text: str) -> str:
      return hashlib.sha256(raw_text.encode()).hexdigest()[:16]

  async def get_cached_llm(raw_text: str) -> dict | None:
      """Check LLM cache by text hash. Returns parsed dict or None."""
      # Import settings inside function to avoid circular import (config → receipts → cache → config)
      from src.config import settings
      key = f"llm_cache:{_text_hash(raw_text)}"
      cached = await (await get_redis()).get(key)
      return json.loads(cached) if cached else None

  async def set_cached_llm(raw_text: str, result: dict) -> None:
      from src.config import settings
      key = f"llm_cache:{_text_hash(raw_text)}"
      await (await get_redis()).setex(key, settings.LLM_CACHE_TTL, json.dumps(result))

  async def set_enrich_status(receipt_id: str, status: str) -> None:
      from src.config import settings
      await (await get_redis()).setex(f"enrich_status:{receipt_id}", settings.ENRICH_STATUS_TTL, status)

  async def get_enrich_status(receipt_id: str) -> str | None:
      return await (await get_redis()).get(f"enrich_status:{receipt_id}")

  async def increment_retry(scope: str, key_id: str) -> int:
      """Increment retry count by scope (receipt_id OR text_hash). Returns attempt number.

      Two scopes are tracked: per-receipt (retry_count:{receipt_id}) and per-text-hash
      (retry_count:{hash}). Per-text-hash prevents retry storms on identical OCR text
      across multiple receipts.
      """
      redis = await get_redis()
      key = f"retry_count:{scope}:{key_id}"
      count = await redis.incr(key)
      await redis.expire(key, 300)  # 5 min TTL
      return count
  ```

- **Why**: Reuses the existing `ConnectionPool` from `backend/src/cache/redis.py` (initialised in app lifespan) instead of creating a second connection. Settings imported inside functions to avoid circular import (config → receipts → cache → config). Retry key is scoped to both receipt_id and text_hash.
- **Dependencies**: Step 2 (config), existing `backend/src/cache/redis.py`
- **Risk**: Low

### Phase 2: LLM Extractor

#### Step 5. Create LLM extractor module

- **File**: `backend/src/receipts/llm_extractor.py` (NEW)
- **Action**: Create module with:
  - `_build_extraction_prompt(raw_text: str) -> str` — prompt that asks Haiku to extract all fields as JSON
  - `extract_with_llm(raw_text: str) -> LLMExtractionResult | None` — calls Bedrock Haiku, parses JSON response into Pydantic model
  - Uses `langchain_aws.ChatBedrock` (same pattern as `bedrock.py`)
  - Prompt asks for structured JSON with per-field confidence scores
  - Temperature=0, max_tokens from config
  - Check Redis cache before Bedrock call, store on success
  - Retry with backoff on transient failures (timeout, 5xx)
  - Graceful degradation: returns None on permanent failure
- **Why**: Core LLM extraction capability for the cascade
- **Dependencies**: Step 2 (config), Step 3 (models), Step 4 (cache)
- **Risk**: Medium — Bedrock prompt engineering, JSON parsing

**Prompt design** (key detail):

```
Extract receipt data from this OCR text. Return JSON with these fields:
- merchant_name: string or null
- total_amount: number or null
- date: ISO date string or null
- line_items: array of {description, quantity, amount}
- category: one of Groceries, Dining, Transport, Utilities, Entertainment, Healthcare, Shopping, Travel, Education, Uncategorised
- confidence: object with keys merchant_name, total_amount, date, line_items, category (each 0.0-1.0)

Only return valid JSON, no other text.

OCR text:
{raw_text}
```

### Phase 3: Cascade Logic

#### Step 6. Create cascade orchestrator

- **File**: `backend/src/receipts/cascade.py` (NEW)
- **Action**: Create module with:

  ```python
  def _score_heuristic_confidence(
      result: dict, raw_text: str, known_merchants: list[str]
  ) -> dict[str, FieldConfidence]:
      """Score each field from regex extraction with confidence.

      `known_merchants` is the list of merchant keywords loaded from
      `backend/src/categories/seed.py` (extracted once at module load).
      """
      # merchant: 0.9 if found, 0.0 if not
      # total: 0.95 if found (high confidence pattern match), 0.0 if not
      # date: 0.85 if found, 0.0 if not
      # items: score by count (0 items = 0.0, N items = min(0.9, 0.5 + N*0.1))
      # Uses rapidfuzz to check if merchant matches known_merchants → boost confidence

  def _detect_discrepancies(
      heuristic: dict[str, FieldConfidence], llm: LLMExtractionResult
  ) -> list[dict]:
      """Compare heuristic and LLM results, log differences.

      Only logs a discrepancy when BOTH sources have confidence >= 0.5 for the
      field AND the values differ. This prevents noise from low-confidence
      fields where a difference is expected, not anomalous.
      """
      for field in ("merchant", "total", "date"):
          h_conf = heuristic[field].confidence
          l_conf = llm.confidence.get(field, 0.0)
          if h_conf >= 0.5 and l_conf >= 0.5:
              if _values_differ(heuristic[field].value, getattr(llm, f"{field}_field")):
                  discrepancies.append({"field": field, "regex": ..., "llm": ...})
      return discrepancies

  def _merge_results(
      heuristic: dict[str, FieldConfidence], llm: LLMExtractionResult, discrepancies: list[dict]
  ) -> CascadeResult:
      """Pick the higher-confidence value for each field."""

  async def cascade_extract(image_bytes: bytes) -> CascadeResult:
      """Full cascade: OCR → regex → confidence check → optional LLM escalation."""
      # 1. Run existing process_receipt() via asyncio.to_thread() (CPU-bound OCR)
      # 2. Score heuristic confidence per field
      # 3. Compute overall_confidence = (merchant_conf + total_conf + date_conf) / 3
      # 4. If overall_confidence >= threshold: return regex result (source="regex")
      # 5. If below threshold: call extract_with_llm()
      # 6. If LLM fails: return regex result (source="degraded")
      # 7. Compare, detect discrepancies, merge
      # 8. Return CascadeResult (source="cascade")
  ```

- **Why**: Core cascade logic — the main feature
- **Dependencies**: Steps 1–5
- **Risk**: Medium — confidence scoring logic needs tuning
- **Note**: `process_receipt()` is CPU-bound (Tesseract). Must use `asyncio.to_thread()` to avoid blocking the event loop.

#### Step 7. Create fuzzy merchant matcher

- **File**: `backend/src/receipts/merchant_match.py` (NEW)
- **Action**: Create module with:
  ```python
  def fuzzy_match_merchant(
      merchant_name: str, known_merchants: list[str] | None = None
  ) -> tuple[str | None, float]:
      """Match merchant against known list using rapidfuzz. Returns (best_match, score)."""
  ```
  - **Load known merchants from `backend/src/categories/seed.py`** — extract all `merchant_keywords` from `SEED_CATEGORIES` at module load:
    ```python
    from src.categories.seed import SEED_CATEGORIES
    KNOWN_MERCHANTS = [kw for cat in SEED_CATEGORIES for kw in cat["merchant_keywords"]]
    ```
  - Use `rapidfuzz.fuzz.token_sort_ratio` for matching
  - Threshold: score > 80 = match
- **Why**: Boost confidence when merchant matches a known entity. Seed data already curated.
- **Dependencies**: Step 1 (rapidfuzz)
- **Risk**: Low

### Phase 4: Database & Router Integration

#### Step 8. Add cascade_decisions table + migration

- **File**: `backend/alembic/versions/` (NEW migration)
- **Action**: Create Alembic migration for `cascade_decisions` table:
  ```sql
  CREATE TABLE cascade_decisions (
      id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
      receipt_id UUID NOT NULL REFERENCES receipts(id) ON DELETE CASCADE,
      raw_text_hash VARCHAR(16) NOT NULL,  -- sha256[:16] for cache lookup
      regex_confidence REAL NOT NULL,
      llm_confidence REAL,
      chosen_source VARCHAR(20) NOT NULL,  -- "regex" | "cascade" | "degraded"
      field_confidences JSONB NOT NULL,    -- per-field scores from chosen source
      discrepancies JSONB,                 -- regex vs LLM differences
      processing_time_ms INTEGER NOT NULL,
      created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
  );
  CREATE INDEX idx_cascade_decisions_receipt ON cascade_decisions(receipt_id);
  CREATE INDEX idx_cascade_decisions_hash ON cascade_decisions(raw_text_hash);
  ```
- **File**: `backend/src/receipts/models.py` — add `CascadeDecision` Pydantic model
- **Why**: ML observability — track every cascade decision for A/B analysis, drift detection, and eval. This is your experiment tracking without MLflow.
- **Dependencies**: Step 3 (models)
- **Risk**: Low — additive migration

#### Step 9. Add health check endpoint

- **File**: `backend/src/receipts/router.py`
- **Action**: Add `GET /receipts/health` endpoint:
  ```python
  @router.get("/health")
  async def health_check():
      """Verify Bedrock + Redis connectivity."""
      checks = {}
      # Bedrock: invoke with minimal prompt
      try:
          checks["bedrock"] = "ok" if await _check_bedrock() else "degraded"
      except Exception:
          checks["bedrock"] = "unavailable"
      # Redis: ping
      try:
          await (await get_redis()).ping()
          checks["redis"] = "ok"
      except Exception:
          checks["redis"] = "unavailable"
      status = "healthy" if all(v == "ok" for v in checks.values()) else "degraded"
      return {"status": status, "checks": checks}
  ```
- **Why**: DevOps signal — shows you think about operational health, not just features
- **Dependencies**: Step 4 (cache.py for Redis), Step 5 (llm_extractor for Bedrock)
- **Risk**: Low

### Phase 5: Router Integration

#### Step 10. Modify router to use cascade

- **File**: `backend/src/receipts/router.py`
- **Action**: In `scan_receipt()`:

  1. Run `process_receipt()` via `asyncio.to_thread()` (CPU-bound OCR — don't block event loop)
  2. Score heuristic confidence
  3. If confidence >= threshold: insert with `source="regex"`, return immediately
  4. If confidence < threshold: insert with `source="pending_llm"`, fire background task
  5. Background task: run `extract_with_llm()`, merge with regex, update DB row
  6. Log decision to `cascade_decisions` table

  ```python
  import asyncio
  from fastapi import BackgroundTasks

  async def scan_receipt(
      ...,
      background_tasks: BackgroundTasks,  # injected by FastAPI
  ):
      # Run CPU-bound OCR in thread pool
      result = await asyncio.to_thread(process_receipt, image_bytes)
      # ... score confidence, insert receipt ...
      if confidence < settings.CASCADE_CONFIDENCE_THRESHOLD:
          # ponytail: BackgroundTasks — replace with Celery/Redis queue when
          # retries/persistence across worker restarts are needed. MVP: fine.
          background_tasks.add_task(
              _enrich_receipt_background, receipt_id, result["ocr_raw_text"]
          )
      return receipt  # Fast response with regex results

  async def _enrich_receipt_background(receipt_id: str, raw_text: str) -> None:
      """Background task: run LLM extraction and update the receipt.

      Accepts (receipt_id, raw_text) — NOT image_bytes — so the background
      task doesn't carry the (already-discarded) image payload.
      """
      try:
          await set_enrich_status(receipt_id, "pending")
          llm_result = await extract_with_llm(raw_text)
          if llm_result:
              async with connection_ctx() as conn:
                  await conn.execute("""
                      UPDATE receipts
                      SET source = 'cascade',
                          ocr_confidence = $1,
                          merchant_name = COALESCE($2, merchant_name),
                          total_amount = COALESCE($3, total_amount),
                          line_items = COALESCE($4, line_items)
                      WHERE id = $5
                  """, llm_result.confidence.get("total_amount", 0.0),
                       llm_result.merchant_name, llm_result.total_amount,
                       json.dumps(llm_result.line_items), receipt_id)
              await set_enrich_status(receipt_id, "done")
          else:
              await set_enrich_status(receipt_id, "failed")
      except Exception:
          await set_enrich_status(receipt_id, "failed")
  ```

- **Why**: Returns fast with regex results, enriches in background. Never blocks the user.
- **Dependencies**: Steps 6, 7, 8
- **Risk**: Medium — must not break existing behavior; cascade falls back to regex

#### Step 11. Update source field logic

- **File**: `backend/src/receipts/router.py`
- **Action**: Change `source = "regex"` to use cascade source values: `"regex"` | `"pending_llm"` | `"cascade"` | `"degraded"`
- **Why**: Reflect actual extraction method; `"pending_llm"` tells client enrichment is in progress
- **Dependencies**: Step 10
- **Risk**: Low

### Phase 6: Eval Dataset & Tests

#### Step 12. Create eval dataset

- **File**: `backend/tests/eval_dataset.py` (NEW)
- **Action**: Create 50–100 synthetic receipt texts covering:
  - Simple receipts (clear total, merchant, date)
  - Complex receipts (multiple totals, VAT, discounts)
  - Edge cases (no date, no merchant, handwritten-style OCR errors)
  - Different formats (UK £, US $, EU €)
  - Different merchants (Tesco, Starbucks, Uber, Amazon, etc.)
  - Each entry: `{"text": "...", "expected": {"merchant": "...", "total": ..., "date": "...", "items_count": N}}`
- **Why**: Evaluate both heuristic and LLM extraction accuracy
- **Dependencies**: None (can be done in parallel)
- **Risk**: Low

#### Step 13. Write cascade tests

- **File**: `backend/tests/test_cascade.py` (NEW)
- **Action**: Test:
  - `_score_heuristic_confidence()` with various inputs
  - `_detect_discrepancies()` with matching/differing results
  - `_merge_results()` picks higher confidence
  - `cascade_extract()` end-to-end (mock LLM)
  - Cascade returns regex result when confidence >= threshold
  - Cascade escalates to LLM when confidence < threshold
  - Background enrichment updates DB correctly
- **Why**: Verify cascade logic
- **Dependencies**: Step 6
- **Risk**: Low

#### Step 14. Write LLM extractor tests

- **File**: `backend/tests/test_llm_extractor.py` (NEW)
- **Action**: Test with mocked Bedrock:
  - Valid JSON response parsing
  - Malformed JSON graceful handling
  - None/empty response handling
  - Per-field confidence extraction
  - Cache hit/miss behavior
  - Retry on transient failure
- **Why**: Verify LLM extraction without real API calls
- **Dependencies**: Step 5
- **Risk**: Low

#### Step 15. Run eval dataset

- **File**: `backend/tests/test_eval.py` (NEW)
- **Action**: Parametrized test over eval_dataset:
  - For each synthetic receipt, run regex extraction
  - Assert heuristic extraction matches expected (for high-quality OCR text)
  - Log field-level precision/recall/F1 metrics
- **Why**: Measure extraction quality with real metrics
- **Dependencies**: Steps 6, 12
- **Risk**: Low

## Cascade Logic Flow

```
Image bytes
    │
    ▼
┌─────────────────────┐
│  preprocess_image()  │  existing OCR preprocessing
│  extract_text()      │  Tesseract OCR (via asyncio.to_thread)
└─────────┬───────────┘
          │ raw_text
          ▼
┌─────────────────────┐
│  process_receipt()   │  existing regex parsing
│  (parse_total, etc.) │  returns heuristic result
└─────────┬───────────┘
          │ heuristic result
          ▼
┌─────────────────────┐
│ _score_heuristic_    │  per-field confidence
│   confidence()       │  (rapidfuzz merchant match)
└─────────┬───────────┘
          │ field confidences
          ▼
     overall_confidence >= threshold?
          │
     ┌────┴────┐
     │ YES     │ NO
     │         │
     ▼         ▼
  Insert     Insert with
  with       source="pending_llm"
  source=    │
  "regex"    ▼
  │      Fire BackgroundTask
  │         │
  │         ▼
  │    ┌──────────────────┐
  │    │ extract_with_llm()│  Bedrock Haiku
  │    │ (with retry +     │  structured extraction
  │    │  cache check)     │
  │    └────────┬─────────┘
  │             │
  │             ▼
  │    ┌─────────────────┐
  │    │ _detect_         │  compare regex vs LLM
  │    │  discrepancies() │  log differences
  │    └────────┬────────┘
  │             │
  │             ▼
  │    ┌─────────────────┐
  │    │ _merge_results() │  pick higher confidence
  │    └────────┬────────┘
  │             │
  │             ▼
  │    Update DB: source="cascade"
  │    Log to cascade_decisions
  │
  ▼
  Return to client
  (fast response)
```

## Per-Field Confidence Scoring

### Heuristic (regex) confidence:

| Field      | Found                        | Not Found |
| ---------- | ---------------------------- | --------- |
| `total`    | 0.95 (strong pattern match)  | 0.0       |
| `merchant` | 0.90 (first non-skip line)   | 0.0       |
| `date`     | 0.85 (date pattern match)    | 0.0       |
| `items`    | 0.50 + (N \* 0.10), cap 0.90 | 0.0       |

**Merchant boost**: If `fuzzy_match_merchant()` finds a known merchant with score > 80, boost confidence to 0.95.

### LLM confidence:

From the prompt response — Haiku returns per-field confidence scores (0.0–1.0). The model is instructed to score based on clarity of the OCR text for each field.

### Overall confidence:

`overall = (merchant_conf + total_conf + date_conf) / 3`

(Items excluded from overall — they're optional on many receipts.)

## Background Enrichment Approach

FastAPI `BackgroundTasks` for non-blocking LLM calls:

1. `scan_receipt()` runs OCR + regex synchronously via `asyncio.to_thread()` (~200ms)
2. If `overall_confidence >= threshold`: insert receipt with `source="regex"`, return immediately
3. If `overall_confidence < threshold`: insert receipt with `source="pending_llm"`, return immediately
4. Fire `BackgroundTasks.add_task(_enrich_receipt_background, receipt_id, raw_text)`
5. Background task runs LLM extraction (~1-2s), merges with regex, updates DB row
6. Client polls `GET /receipts/{id}` — sees `source="pending_llm"` → waits → sees `source="cascade"` when done
7. Redis tracks enrichment status for fast status checks without DB queries

**Why FastAPI BackgroundTasks**: Already available, no new infrastructure. Works with the asyncpg pool.

> **MVP limitation (ponytail):** `BackgroundTasks` does not survive worker restarts and has no built-in retry/observability. For MVP this is fine — a lost enrichment just means a receipt stays at `source="pending_llm"` and the client can re-scan. Replace with a Celery/Redis queue (or RQ/Dramatiq) when retries and persistence across restarts become required.

## Eval Dataset Approach

50-100 synthetic receipts as Python data:

```python
EVAL_RECEIPTS = [
    {
        "name": "tesco_simple",
        "text": "TESCO STORES LTD\n25/06/2026\nMilk 1.65\nBread 1.20\nTotal £2.85",
        "expected": {
            "merchant": "TESCO STORES LTD",
            "total": 2.85,
            "date": "2026-06-25",
            "items_count": 2,
        },
    },
    # ... 49-99 more
]
```

Categories covered:

- Simple grocery (5)
- Restaurant/dining (5)
- Transport/Uber (5)
- Electronics/Amazon (5)
- UK format with £ (10)
- US format with $ (10)
- EU format with € (5)
- Edge cases: no merchant (5), no date (5), no items (5), multiple totals (5), OCR errors (5)

## Test Strategy

| Test File                | What it Tests                                                        | Approach                           |
| ------------------------ | -------------------------------------------------------------------- | ---------------------------------- |
| `test_cascade.py`        | Confidence scoring, discrepancy detection, merge logic, cascade flow | Unit tests with mocked LLM         |
| `test_llm_extractor.py`  | JSON parsing, prompt building, error handling                        | Unit tests with mocked Bedrock     |
| `test_eval.py`           | End-to-end extraction accuracy                                       | Parametrized over eval dataset     |
| `test_merchant_match.py` | Fuzzy matching accuracy                                              | Unit tests with known merchants    |
| `test_ocr.py` (existing) | Regex parsing functions                                              | **No changes** — continues to pass |

## Risks & Mitigations

| Risk                                | Mitigation                                                                                 |
| ----------------------------------- | ------------------------------------------------------------------------------------------ |
| LLM JSON response unparseable       | Graceful fallback to regex result; log warning                                             |
| Bedrock unavailable                 | `extract_with_llm()` returns None; cascade returns regex result                            |
| Confidence threshold too aggressive | Configurable via `CASCADE_CONFIDENCE_THRESHOLD`; start conservative (0.7)                  |
| Background task DB update fails     | Log error; receipt still has regex results                                                 |
| rapidfuzz adds dependency           | Already planned; lightweight pure-Python package                                           |
| Existing tests break                | Cascade is additive; `process_receipt()` unchanged; router changes are backward-compatible |

## Success Criteria

- [ ] Existing `test_ocr.py` tests pass unchanged
- [ ] New `test_cascade.py` tests pass
- [ ] New `test_llm_extractor.py` tests pass (mocked)
- [ ] Eval dataset demonstrates extraction accuracy with field-level metrics
- [ ] `POST /receipts/scan` returns fast for high-confidence receipts (~200ms)
- [ ] Low-confidence receipts get background LLM enrichment (source transitions pending_llm → cascade)
- [ ] `source` field reflects actual extraction method
- [ ] Per-field confidence scores are returned in response
- [ ] Discrepancies between regex and LLM are logged to `cascade_decisions`
- [ ] `GET /receipts/health` returns Bedrock + Redis status
- [ ] Redis caches LLM responses (same OCR text → no duplicate Bedrock calls)
