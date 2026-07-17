# Goal: Tool Review — Phase 6 Agent Tools

> Evaluates all 19 proposed agent tools against Phase 6 goals (analytical Q&A, no trade execution, streaming, graceful degradation, LLM-as-Judge eval).
> **Date:** 2026-07-13

---

## Evaluation Criteria

Each tool is scored 1–5 (5 = best) across six dimensions:

| Dimension               | What it measures                                                                          |
| ----------------------- | ----------------------------------------------------------------------------------------- |
| **User Need**           | Would a user naturally ask this question? Is this a high-frequency query?                 |
| **Scope Fit**           | Is the tool's scope right — not too broad, not too narrow for an LLM to select correctly? |
| **Data Reliability**    | How dependable is the data source? (yfinance flakiness, DB staleness, API rate limits)    |
| **LLM Disambiguity**    | Can the LLM reliably distinguish this tool from similar ones via description alone?       |
| **Novelty**             | Is this genuinely new logic, or just wrapping an existing endpoint as-is?                 |
| **Implementation Risk** | Likelihood of bugs, edge cases, or unexpected complexity during build.                    |

**Overall:** 🟢 Keep / 🟡 Flag (needs attention) / 🔴 Cut / 🔵 Merge

---

## Market Data (4 tools)

### 1. `get_market_ohlcv` — Fetch historical OHLCV price data

| Dimension           | Score       | Notes                                                                                               |
| ------------------- | ----------- | --------------------------------------------------------------------------------------------------- |
| User Need           | 5           | "How has AAPL performed over the last year?" — core finance Q                                       |
| Scope Fit           | 5           | Clear: historical prices for one ticker over a date range                                           |
| Data Reliability    | 4           | DB-backed with yfinance fallback; cache layer makes this solid                                      |
| LLM Disambiguity    | 4           | Distinct from `get_market_quote` (current vs historical). Description must specify date range param |
| Novelty             | 2           | Wraps existing `/market/ohlcv/{ticker}` endpoint                                                    |
| Implementation Risk | 1           | Trivial — wrap existing endpoint                                                                    |
| **Overall**         | 🟢 **Keep** | No-brainer. Every finance agent needs this.                                                         |

### 2. `get_market_quote` — Current price snapshot

| Dimension           | Score       | Notes                                                     |
| ------------------- | ----------- | --------------------------------------------------------- |
| User Need           | 5           | "What's AAPL trading at?" — simplest, most frequent query |
| Scope Fit           | 5           | Single ticker, single price snapshot. Unambiguous         |
| Data Reliability    | 4           | yfinance real-time with 60s Redis cache                   |
| LLM Disambiguity    | 4           | "Current price" vs ohlcv's "historical prices" is clear   |
| Novelty             | 2           | Wraps existing `/market/quote/{ticker}` endpoint          |
| Implementation Risk | 1           | Trivial                                                   |
| **Overall**         | 🟢 **Keep** | Essential.                                                |

### 3. `get_ticker_info` — Company profile and fundamentals

| Dimension           | Score       | Notes                                                                                                                                                                                             |
| ------------------- | ----------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| User Need           | 4           | "Tell me about Apple" — common, but less actionable than price/performance Qs                                                                                                                     |
| Scope Fit           | 4           | Company profile, sector, fundamentals. Broad but coherent                                                                                                                                         |
| Data Reliability    | 3           | yfinance `Ticker.info` — mostly static fields (sector, industry, market cap). Ratio data (PE, dividend yield) is more volatile but generally reliable. Some fields may be missing for small caps. |
| LLM Disambiguity    | 3           | Risk: LLM might use this for price data instead of `get_market_quote`. Description must say "use for company background, NOT for current price."                                                  |
| Novelty             | 5           | NEW endpoint — no existing equivalent                                                                                                                                                             |
| Implementation Risk | 2           | Straightforward yfinance wrapper                                                                                                                                                                  |
| **Overall**         | 🟢 **Keep** | Valuable for company-level questions. Mitigate LLM ambiguity with precise description.                                                                                                            |

### 4. `get_market_news` — Recent news headlines

| Dimension           | Score       | Notes                                                                                                                                                                                         |
| ------------------- | ----------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| User Need           | 4           | "What's happening with Tesla?" — real user need                                                                                                                                               |
| Scope Fit           | 4           | Returns recent headlines for given tickers                                                                                                                                                    |
| Data Reliability    | 2           | ⚠️ **Big concern.** yfinance news is limited (3-5 items), often stale (hours to days old), and may return empty for smaller tickers. This is the least reliable data source in the inventory. |
| LLM Disambiguity    | 4           | News is clearly distinct from price/fundamental tools                                                                                                                                         |
| Novelty             | 5           | NEW endpoint                                                                                                                                                                                  |
| Implementation Risk | 3           | Low code complexity, but data quality risk is real                                                                                                                                            |
| **Overall**         | 🟡 **Flag** | Keep it, but the description MUST set expectations: "Returns recent news headlines. May return limited or no results for smaller tickers. Not real-time — can be several hours old."          |

---

## Portfolio (3 tools)

### 5. `get_portfolio_summary` — Portfolio overview

| Dimension           | Score       | Notes                                                                                                                                                                  |
| ------------------- | ----------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| User Need           | 5           | "How's my portfolio doing?" — top-3 most likely question                                                                                                               |
| Scope Fit           | 4           | Returns total value, cost basis, P&L, day change. Good scope                                                                                                           |
| Data Reliability    | 5           | DB-backed, computed from owned positions                                                                                                                               |
| LLM Disambiguity    | 3           | ⚠️ Overlaps with `get_portfolio_performance` and `get_portfolio_history`. LLM may not distinguish "summary" vs "performance" vs "history" without precise descriptions |
| Novelty             | 2           | Wraps existing portfolio summary endpoint                                                                                                                              |
| Implementation Risk | 1           | Trivial wrap                                                                                                                                                           |
| **Overall**         | 🟢 **Keep** | Essential. Mitigate overlap with clear descriptions (see recommendations).                                                                                             |

### 6. `get_portfolio_holdings` — Current holdings list

| Dimension           | Score       | Notes                                                          |
| ------------------- | ----------- | -------------------------------------------------------------- |
| User Need           | 4           | "What do I own?" — common question                             |
| Scope Fit           | 5           | Clear: list of positions with shares, price, value             |
| Data Reliability    | 5           | DB-backed. No external dependency                              |
| LLM Disambiguity    | 4           | Clearly distinct from summary (aggregate) vs holdings (detail) |
| Novelty             | 2           | Wraps existing holdings endpoint                               |
| Implementation Risk | 1           | Trivial                                                        |
| **Overall**         | 🟢 **Keep** | No-brainer.                                                    |

### 7. `get_sector_exposure` — Sector allocation (NEW)

| Dimension           | Score       | Notes                                                                                                                                                                        |
| ------------------- | ----------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| User Need           | 4           | "What sectors am I exposed to?" — moderately common, higher for sophisticated users                                                                                          |
| Scope Fit           | 4           | Sector → value → % breakdown. Good scope                                                                                                                                     |
| Data Reliability    | 3           | ✅ Sector mapping from DB holdings. ⚠️ Ticker → sector mapping relies on yfinance `Ticker.info['sector']` which is cached forever — stale for companies that changed sectors |
| LLM Disambiguity    | 5           | Unique — no other tool does sector breakdown                                                                                                                                 |
| Novelty             | 5           | NEW — genuine aggregation logic                                                                                                                                              |
| Implementation Risk | 2           | Straightforward: join holdings with yfinance ticker info, aggregate                                                                                                          |
| **Overall**         | 🟢 **Keep** | Strong differentiator. Document sector staleness risk.                                                                                                                       |

---

## Performance (3 tools)

### 8. `get_portfolio_performance` — TWR returns

| Dimension           | Score       | Notes                                                                                                                                                                                                |
| ------------------- | ----------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| User Need           | 5           | "What's my return?" — core question                                                                                                                                                                  |
| Scope Fit           | 4           | Returns TWR, annualised TWR, daily returns                                                                                                                                                           |
| Data Reliability    | 5           | DB-backed performance computation                                                                                                                                                                    |
| LLM Disambiguity    | 3           | ⚠️ Major overlap with `get_portfolio_history` and `get_portfolio_summary`. "Performance" = returns %, "History" = value over time, "Summary" = current snapshot. LLMs struggle with this distinction |
| Novelty             | 2           | Wraps existing performance endpoint                                                                                                                                                                  |
| Implementation Risk | 1           | Trivial wrap                                                                                                                                                                                         |
| **Overall**         | 🟡 **Flag** | Keep, but this + `get_portfolio_history` + `get_portfolio_summary` form a confusing triad. See merge recommendation below.                                                                           |

### 9. `get_portfolio_history` — Historical portfolio values

| Dimension           | Score        | Notes                                                                                                                                                          |
| ------------------- | ------------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| User Need           | 3            | "How has my portfolio changed over time?" — less common than "what's my return?"                                                                               |
| Scope Fit           | 4            | Returns time series of portfolio values                                                                                                                        |
| Data Reliability    | 5            | DB-backed                                                                                                                                                      |
| LLM Disambiguity    | 2            | ⚠️ Very hard to distinguish from `get_portfolio_performance`. Both are time-series return data. User says "how did I do last month?" — LLM could choose either |
| Novelty             | 2            | Wraps existing performance history endpoint                                                                                                                    |
| Implementation Risk | 1            | Trivial                                                                                                                                                        |
| **Overall**         | 🔵 **Merge** | Strong candidate for merging with `get_portfolio_performance`. One tool with an `include_history` parameter.                                                   |

### 10. `compare_to_benchmark` — Benchmark comparison

| Dimension           | Score       | Notes                                                            |
| ------------------- | ----------- | ---------------------------------------------------------------- |
| User Need           | 4           | "How am I doing vs the S&P 500?" — common for engaged users      |
| Scope Fit           | 4           | Alpha, tracking error, information ratio. Good scope             |
| Data Reliability    | 5           | DB-backed (portfolio performance + benchmark OHLCV)              |
| LLM Disambiguity    | 4           | "Compare to benchmark" is clearly different from raw performance |
| Novelty             | 2           | Wraps existing benchmark endpoint                                |
| Implementation Risk | 1           | Trivial                                                          |
| **Overall**         | 🟢 **Keep** | Valuable and distinct.                                           |

---

## Forecasting (1 tool)

### 11. `get_lstm_forecast` — ML price prediction

| Dimension           | Score       | Notes                                                                                                                     |
| ------------------- | ----------- | ------------------------------------------------------------------------------------------------------------------------- |
| User Need           | 3           | "Will AAPL go up?" — users ask this, but they shouldn't _act_ on it. The persona prompt already warns about this          |
| Scope Fit           | 5           | Single ticker, returns UP/FLAT/DOWN + confidence                                                                          |
| Data Reliability    | 3           | LSTM model is inherently noisy (~53% directional accuracy). Not "reliable" in the traditional sense                       |
| LLM Disambiguity    | 5           | Unique — only forecasting tool                                                                                            |
| Novelty             | 2           | Wraps existing prediction endpoint                                                                                        |
| Implementation Risk | 1           | Trivial wrap                                                                                                              |
| **Overall**         | 🟢 **Keep** | High interest value even if model accuracy is modest. The agent should caveat the prediction uncertainty in its response. |

---

## Spending (3 tools)

### 12. `get_spending_analysis` — Category aggregation (NEW)

| Dimension           | Score       | Notes                                                                               |
| ------------------- | ----------- | ----------------------------------------------------------------------------------- |
| User Need           | 4           | "Where did my money go?" — strongly desired per grilling session                    |
| Scope Fit           | 5           | Category + amount + percentage + MoM change. Well-scoped                            |
| Data Reliability    | 5           | DB-backed from transactions table. No external dependency                           |
| LLM Disambiguity    | 4           | Distinct from `get_recent_transactions` (analysis vs raw list)                      |
| Novelty             | 5           | NEW — dedicated endpoint specifically requested in grilling. Real aggregation logic |
| Implementation Risk | 2           | SQL aggregation query + business logic. Straightforward                             |
| **Overall**         | 🟢 **Keep** | Strong differentiator. High value.                                                  |

### 13. `get_recent_transactions` — Recent transaction list

| Dimension           | Score       | Notes                                                                                                                                                                                        |
| ------------------- | ----------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| User Need           | 3           | "Show my recent buys/sells" — useful but less common than spending analysis                                                                                                                  |
| Scope Fit           | 4           | List of recent transactions with details. Good scope                                                                                                                                         |
| Data Reliability    | 5           | DB-backed                                                                                                                                                                                    |
| LLM Disambiguity    | 3           | ⚠️ Risk: LLM might use this for spending analysis questions. Description must say "use for raw transaction lists, NOT for aggregated spending breakdown — use get_spending_analysis instead" |
| Novelty             | 2           | Wraps existing transactions endpoint                                                                                                                                                         |
| Implementation Risk | 1           | Trivial                                                                                                                                                                                      |
| **Overall**         | 🟢 **Keep** | Useful for "show me my trades" type questions. Description must steer aggregation queries to `get_spending_analysis`.                                                                        |

### 14. `get_cash_flow_summary` — Cash flow data

| Dimension           | Score       | Notes                                                                                                                                                                                          |
| ------------------- | ----------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| User Need           | 2           | "How much cash have I deposited?" — niche, power-user query                                                                                                                                    |
| Scope Fit           | 3           | Cash flow deposits. Useful but narrow                                                                                                                                                          |
| Data Reliability    | 5           | DB-backed                                                                                                                                                                                      |
| LLM Disambiguity    | 3           | Could be confused with `get_portfolio_summary` which may already include free cash balance                                                                                                     |
| Novelty             | 2           | Wraps existing cash flows endpoint                                                                                                                                                             |
| Implementation Risk | 1           | Trivial                                                                                                                                                                                        |
| **Overall**         | 🟡 **Flag** | Useful but niche. If `get_portfolio_summary` already includes free cash balance, this is redundant. Consider whether `get_portfolio_summary` already exposes cash info — if yes, merge or cut. |

---

## Analysis (3 tools)

### 15. `get_portfolio_diversification_score` — HHI diversification (NEW)

| Dimension           | Score       | Notes                                                                                                                                                                                               |
| ------------------- | ----------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| User Need           | 3           | "Is my portfolio diversified?" — sophisticated users ask this. Less common but high-value                                                                                                           |
| Scope Fit           | 5           | Single score (0-100) with factor breakdown. Well-scoped                                                                                                                                             |
| Data Reliability    | 5           | Computed from DB holdings data. No external dependency                                                                                                                                              |
| LLM Disambiguity    | 5           | Unique — no other tool computes diversification                                                                                                                                                     |
| Novelty             | 5           | NEW — HHI-based computation. Strong differentiator per resume review                                                                                                                                |
| Implementation Risk | 3           | HHI formula is simple, but weight factors (holdings count 20%, sector HHI 40%, top holding weight 20%, correlation proxy 20%) need tuning. Edge cases: single-holding portfolio, all-cash portfolio |
| **Overall**         | 🟢 **Keep** | **Top differentiator.** High signal for AI interviews. Accept the tuning risk.                                                                                                                      |

### 16. `compare_tickers_side_by_side` — Multi-ticker comparison (NEW)

| Dimension           | Score       | Notes                                                                                                                                                                      |
| ------------------- | ----------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| User Need           | 4           | "How does AAPL compare to MSFT?" — common question                                                                                                                         |
| Scope Fit           | 4           | Matrix of ticker × metric. Good scope                                                                                                                                      |
| Data Reliability    | 3           | Relies on yfinance `Ticker.info` for each ticker. Multi-ticker means N yfinance calls                                                                                      |
| LLM Disambiguity    | 4           | "Compare multiple tickers" vs `get_ticker_info` ("single ticker deep dive"). Description must emphasise the matrix format                                                  |
| Novelty             | 5           | NEW — multi-ticker aggregation                                                                                                                                             |
| Implementation Risk | 3           | N concurrent yfinance calls could be slow. Need parallel fetch + timeout. Metrics need standardisation (e.g., all-or-nothing: if one ticker lacks a metric, omit that row) |
| **Overall**         | 🟢 **Keep** | High value. Mitigate data-source risk with parallel fetch + timeout + graceful partial results.                                                                            |

### 17. `get_ticker_screening` — Screen by criteria (NEW)

| Dimension           | Score              | Notes                                                                                                                                                                                                                                                                                                                    |
| ------------------- | ------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| User Need           | 3                  | "Find tech stocks with PE < 25" — power user query. Less common for retail investors                                                                                                                                                                                                                                     |
| Scope Fit           | 4                  | Filter by market cap, sector, PE, dividend yield. Good scope for screening                                                                                                                                                                                                                                               |
| Data Reliability    | 1                  | ⚠️ **Critical concern.** The plan already flags this: yfinance has no screening API. The only viable approach is (a) download a predefined universe (e.g., S&P 500 constituents) via yfinance, (b) fetch info for ALL of them, (c) filter locally. This is slow (~2s/ticker × 500 = 1000s), rate-limited, and unreliable |
| LLM Disambiguity    | 5                  | Unique — screening is clearly distinct from comparing or individual info                                                                                                                                                                                                                                                 |
| Novelty             | 5                  | NEW — but may not work as envisioned                                                                                                                                                                                                                                                                                     |
| Implementation Risk | 5                  | ⚠️ **Highest risk tool in the inventory.** Real screening requires either (a) a financial data API (Polygon, Alpha Vantage, Intrinio) or (b) a pre-computed ticker universe with cached fundamentals. The plan's ponytail comment ("yfinance screening is limited") understates this                                     |
| **Overall**         | 🔴 **Cut from v1** | The implementation path is either too slow (real-time fetch of N tickers), too unreliable (yfinance data quality), or requires a third-party data API not in the project. Remove from agent tools. Keep the endpoint for future use if a data API is added.                                                              |

---

## Insights (1 tool)

### 18. `get_dividend_insights` — Dividend data (NEW)

| Dimension           | Score       | Notes                                                                                                                                                              |
| ------------------- | ----------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| User Need           | 3           | "What's KO's dividend?" — moderate. Dividend-focused investors are a subset                                                                                        |
| Scope Fit           | 4           | Yield, payout ratio, growth rate, ex-div date, pay date. Well-scoped                                                                                               |
| Data Reliability    | 3           | yfinance `Ticker.info` dividend fields are generally available for dividend-paying stocks. But data is infrequently updated. Non-dividend stocks return empty/null |
| LLM Disambiguity    | 5           | Unique — only dividend-specific tool                                                                                                                               |
| Novelty             | 5           | NEW                                                                                                                                                                |
| Implementation Risk | 2           | Wraps yfinance info dividend fields. Handle the empty/null case gracefully                                                                                         |
| **Overall**         | 🟢 **Keep** | Valuable for dividend-oriented questions. Description must note: "Returns empty or null for stocks that don't pay dividends."                                      |

---

## Monitoring (1 tool)

### 19. `get_drift_metrics` — Model drift data

| Dimension           | Score      | Notes                                                                                                                                                                                                                                                                                                                                        |
| ------------------- | ---------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| User Need           | 1          | "Is the model drifting?" — **nobody will ask this.** This is an MLOps concern, not a user-facing finance question                                                                                                                                                                                                                            |
| Scope Fit           | 2          | PSI/KS scores per feature. Meaningless to end users                                                                                                                                                                                                                                                                                          |
| Data Reliability    | 5          | DB-backed drift metrics                                                                                                                                                                                                                                                                                                                      |
| LLM Disambiguity    | 5          | Unique, but for the wrong reasons — it's unique because no user would ever ask about it                                                                                                                                                                                                                                                      |
| Novelty             | 2          | Wraps existing drift endpoint                                                                                                                                                                                                                                                                                                                |
| Implementation Risk | 1          | Trivial                                                                                                                                                                                                                                                                                                                                      |
| **Overall**         | 🔴 **Cut** | This is an operations tool disguised as an agent tool. The agent might never call it (no user asks "check my drift metrics"), and if it does, the response is useless to a retail investor. Remove from agent toolset. Keep the endpoint available for the admin dashboard or monitoring alerts, but don't register it as an agent callable. |

---

## Summary: Recommended Inventory

### Keep (14 tools)

| #   | Tool                                  | Notes                                           |
| --- | ------------------------------------- | ----------------------------------------------- |
| 1   | `get_market_ohlcv`                    | Essential                                       |
| 2   | `get_market_quote`                    | Essential                                       |
| 3   | `get_ticker_info`                     | Valuable — precise description needed           |
| 4   | `get_market_news`                     | Keep with ⚠️ data quality caveat in description |
| 5   | `get_portfolio_summary`               | Essential                                       |
| 6   | `get_portfolio_holdings`              | Essential                                       |
| 7   | `get_sector_exposure`                 | Strong differentiator                           |
| 8   | `get_portfolio_performance`           | Essential — see merge note for #9               |
| 9   | `compare_to_benchmark`                | Valuable                                        |
| 10  | `get_lstm_forecast`                   | High interest value                             |
| 11  | `get_spending_analysis`               | Strong differentiator                           |
| 12  | `get_recent_transactions`             | Keep with redirect description                  |
| 13  | `get_portfolio_diversification_score` | **Top differentiator**                          |
| 14  | `compare_tickers_side_by_side`        | High value                                      |
| 15  | `get_dividend_insights`               | Valuable for dividend investors                 |

### Merge (1 pair)

| Action    | Tools                                                 | Rationale                                                                                                                                             |
| --------- | ----------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Merge** | `get_portfolio_performance` + `get_portfolio_history` | Same data domain (portfolio returns over time). Add `include_history: bool = false` parameter. Reduces LLM confusion from N=3 portfolio tools to N=2. |

### Flag (2 tools)

| Tool                    | Issue                                   | Mitigation                                                            |
| ----------------------- | --------------------------------------- | --------------------------------------------------------------------- |
| `get_market_news`       | yfinance news reliability               | Precise description setting expectations                              |
| `get_cash_flow_summary` | Redundancy with `get_portfolio_summary` | Check if portfolio_summary already has cash balance. Cut if redundant |

### Cut (2 tools)

| Tool                   | Reason                                                                                                                                                          |
| ---------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `get_ticker_screening` | yfinance has no screening capability. Requires a third-party financial data API not in the stack. Ponytail: cut until a screening-capable data source is added. |
| `get_drift_metrics`    | Nobody will ask about model drift. This is an MLOps operational metric, not a user-facing finance insight. Don't register as an agent callable.                 |

---

## Revised Tool Inventory: 15 Tools

After cuts and merges:

**Market Data (4):** `get_market_ohlcv`, `get_market_quote`, `get_ticker_info`, `get_market_news`
**Portfolio (2):** `get_portfolio_summary`, `get_portfolio_holdings`
**Performance (3):** `get_portfolio_performance` (with `include_history` param), `compare_to_benchmark`, `get_sector_exposure`
**Forecasting (1):** `get_lstm_forecast`
**Spending (3):** `get_spending_analysis`, `get_recent_transactions`, `get_cash_flow_summary` (conditional)
**Analysis (2):** `get_portfolio_diversification_score`, `compare_tickers_side_by_side`
**Insights (1):** `get_dividend_insights`

Total: 15–16 tools (depending on `get_cash_flow_summary` fate).

---

## The 3-Overlap Problem

The biggest risk to LLM tool selection is the high overlap between:

> `get_portfolio_summary` ↔ `get_portfolio_performance` ↔ `get_recent_transactions`

A user asks "how's my portfolio doing?" The LLM could reasonably pick any of:

- **Summary** — because "how's it doing" = current snapshot ✓
- **Performance** — because "how's it doing" = returns ✓
- **Transactions** — because recent activity affects "doing" ✗ (wrong, but plausible)

### Fix

Precise tool descriptions that explicitly list **complementary tools** the LLM should consider:

```
get_portfolio_summary:
  "Fetch a portfolio's current overview: total value, cost basis, P&L, day change.
   Use this for: 'How's my portfolio?' 'What's my portfolio worth?'
   Complementary tools: get_portfolio_performance (for return percentages over time)"

get_portfolio_performance:
  "Fetch a portfolio's time-weighted return (TWR) over a date range.
   Use this for: 'What's my return?' 'How did I perform last quarter?'
   Does NOT include: current value snapshot (use get_portfolio_summary)."
```

This cross-referencing pattern is non-standard but highly effective for LLM disambiguation.

---

## Tool Description Template (Updated)

```python
@tool
async def tool_name(param1: str, param2: int) -> str:
    """One-line: what this tool does.

    Use this when: {specific user question patterns}.
    Returns: {what the response contains}.
    Limitations: {what it does NOT do, data staleness, edge cases}.

    Complementary tools: {related tools to consider for related questions}.
    """
    ...
```

This 4-field description (one-line + when + returns + limitations) + optional complementary tools is the standard all 16 tools should follow.
