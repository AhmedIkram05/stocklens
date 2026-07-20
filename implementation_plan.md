# Implementation Plan: Frontend Agent Feature Integration (Refactored)

## What Changed

The 7 tool endpoints in `backend/src/agent/tool_endpoints.py` serve **two purposes**:

1. **Agent tools** — called automatically by the LangGraph ReAct loop when the agent needs data
2. **REST endpoints** — directly callable from frontend for non-chat UI

This changes Phase 5 entirely. Only endpoints that add **genuine unique value** above what existing screens already show should become dedicated screens.

---

## Corrected Understanding of the 7 Endpoints

| Tool                                  | Primary Use       | REST Endpoint                                     | Unique Value for Screens?                                                                                            |
| ------------------------------------- | ----------------- | ------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------- |
| `get_spending_analysis`               | Agent tool + REST | `GET /agent/spending-analysis/{portfolio_id}`     | **Yes** — SummaryScreen currently computes spending from receipts locally; this gives categorized spend + MoM change |
| `get_sector_exposure`                 | Agent tool + REST | `GET /agent/sector-exposure/{portfolio_id}`       | **Yes** — PortfolioDetailScreen shows holdings but not sector breakdown                                              |
| `get_portfolio_diversification_score` | Agent tool + REST | `GET /agent/diversification-score/{portfolio_id}` | **Yes** — SummaryScreen has educational content, no actual diversification score                                     |
| `get_ticker_info`                     | Agent tool + REST | `GET /agent/ticker-info/{ticker}`                 | **Yes** — PortfolioDetailScreen shows price/shares but not company fundamentals                                      |
| `get_market_news`                     | Agent tool + REST | `GET /agent/market-news`                          | **Maybe** — could add news to HomeScreen or PortfolioDetail, but yfinance news is limited/stale                      |
| `get_dividend_insights`               | Agent tool + REST | `GET /agent/dividend-insights/{ticker}`           | **Maybe** — useful when viewing a specific holding; lower priority                                                   |
| `compare_tickers_side_by_side`        | Agent tool + REST | `POST /agent/compare-tickers`                     | **Maybe** — useful as a standalone screen; not tied to existing flow                                                 |

---

## Revised Phase Overview

| Phase | Feature                                     | Priority | Est. Files | Depends On          |
| ----- | ------------------------------------------- | -------- | ---------- | ------------------- |
| 1     | Chat UI Gaps: Tool Results Rendering        | High     | 1-2        | —                   |
| 2     | Chat UI Gaps: Conversation History UI       | High     | 3-4        | —                   |
| 3     | Chat UI Gaps: Feedback Comment + Auto-Title | Medium   | 2          | Phase 2             |
| 4     | New REST-powered Screens                    | Medium   | 4-5        | —                   |
| 5     | Ticker Detail Screen (info + dividends)     | Low      | 1-2        | Phase 4 ticker-info |
| 6     | Compare Tickers Screen                      | Low      | 1          | —                   |
| 7     | Market News (optional)                      | Low      | 1          | Phase 4             |

---

## Phase 1: Tool Results in Message Bubbles

**Goal**: Render structured tool output (tables, charts, key-value pairs) directly in the chat message stream. The agent already calls these tools — the frontend just doesn't display the results.

### Files to Modify

| File                                                  | Action     | Scope                                   |
| ----------------------------------------------------- | ---------- | --------------------------------------- |
| `frontend/src/components/chat/MessageBubble.tsx`      | Modify     | Render `toolResults` below message text |
| `frontend/src/components/chat/ToolResultRenderer.tsx` | Create new | Per-tool result renderer                |

### Strategy

Tools return JSON strings. Map each to a renderer:

| Tool                                  | Renderer                | Output                                         |
| ------------------------------------- | ----------------------- | ---------------------------------------------- |
| `get_portfolio_summary`               | Key-value card          | Total value, P&L, cost basis                   |
| `get_portfolio_holdings`              | Data table              | Ticker, shares, price, P&L per row             |
| `get_sector_exposure`                 | Horizontal bar list     | Sector name + allocation % bars                |
| `get_portfolio_performance`           | Metrics card            | TWR, day change, total gain                    |
| `compare_to_benchmark`                | Comparison card         | Alpha, tracking error, info ratio              |
| `get_portfolio_diversification_score` | Score badge + breakdown | 0-100 score, factor breakdown, recommendations |
| `compare_tickers_side_by_side`        | Table                   | Ticker × metric matrix                         |
| `get_market_ohlcv`                    | Mini table              | Date, O, H, L, C, V                            |
| `get_market_quote`                    | Quote card              | Price, change, volume                          |
| `get_ticker_info`                     | Info card               | Company name, sector, market cap, PE           |
| `get_market_news`                     | Article list            | Title, source, time per article                |
| `get_lstm_forecast`                   | Direction badge         | UP/FLAT/DOWN with confidence %                 |
| `get_spending_analysis`               | Category bars           | Category, amount, % of total                   |
| `get_recent_transactions`             | Transaction table       | Date, type, amount                             |
| `get_cash_flow_summary`               | Summary card            | Deposits total, count, last deposit            |
| `get_dividend_insights`               | Dividend card           | Yield, payout ratio, ex-date                   |

### Tool Result Detection

- The SSE stream sends `tool_start` / `tool_end` events — `onToolEnd(toolName)` fires when a tool completes
- On `tool_end`, the `AgentMessage.toolResults` should contain the result
- Render `toolResults` as a collapsible section below the message text

### Generic Fallback

For any tool without a custom renderer: pretty-print the JSON in a scrollable `<Text>` with monospace font.

### Complexity: Medium

---

## Phase 2: Conversation History UI

**Goal**: Allow users to browse, resume, and delete past conversations.

### Files to Create/Modify

| File                                                    | Action     | Scope                                                        |
| ------------------------------------------------------- | ---------- | ------------------------------------------------------------ |
| `frontend/src/screens/ConversationHistoryScreen.tsx`    | Create new | Modal list of past conversations                             |
| `frontend/src/components/chat/ConversationListItem.tsx` | Create new | Row: title, count, relative time, delete                     |
| `frontend/src/screens/AgentChatScreen.tsx`              | Modify     | Add history icon to header                                   |
| `frontend/src/services/agent.ts`                        | Verify     | `listConversations`, `getConversation`, `deleteConversation` |

### UI Design

- Header icon: `clock-history` (Ionicons) next to close button
- Presents as full-screen modal over the chat modal
- List rows: auto-title, message count, relative timestamp
- Tap → load conversation, dismiss history, replace messages state
- Swipe-left → delete button → confirmation → `deleteConversation`

### Complexity: Medium

---

## Phase 3: Feedback Comment + Auto-Title

**Goal**: Improve feedback (comment field) and show conversation titles.

### Files to Modify

| File                                       | Action         | Scope                                            |
| ------------------------------------------ | -------------- | ------------------------------------------------ |
| `frontend/src/screens/AgentChatScreen.tsx` | Modify         | Show conversation title in header                |
| `agent.ts` → `submitFeedback`              | Already exists | Accepts `comment` param — UI just never sends it |

### Feedback Comment UI

- When thumbs up/down tapped → show small modal with:
  - "Tell us more (optional)" textarea
  - Submit / Cancel buttons
- Calls `submitFeedback(rating, traceId, comment)`

### Auto-Title Display

- `ConversationSummary.title` exists from API — display in `AgentChatScreen` header
- Show in `ConversationHistoryScreen` list rows (already from API)

### Complexity: Low

---

## Phase 4: REST-Powered Screens (4 screens)

**Goal**: Expose 4 high-value endpoints as new screens that add data not currently shown anywhere.

### 4a. SpendingAnalysisScreen → SummaryScreen upgrade

**Replace**: SummaryScreen's local receipt-based spending calculation with `GET /agent/spending-analysis/{portfolio_id}`

**Value**: Categorized spending + month-over-month change (not just total from receipts)

```typescript
// GET /agent/spending-analysis/{portfolio_id}?months=6
// Response: { portfolio_name, period_months, total_spent_gbp, categories[], month_over_month{} }
```

- Keep existing educational content (definitions, insights, projections) in SummaryScreen
- Replace the "Total Money Spent" card with the categorized breakdown from the API
- Show category bars: Food $450 (40%), Transport $120 (25%), etc.
- Show MoM change per category: "Food: +12% vs last month"

**Entry point**: Existing SummaryScreen — just change data source.

### 4b. SectorExposureScreen → PortfolioDetail action button

**Add to**: `PortfolioDetailScreen` — new "Sector Exposure" button next to "Benchmark"

**Value**: PortfolioDetailScreen shows holdings table but no sector view. Sector exposure shows what % is Tech vs Healthcare vs Energy.

```typescript
// GET /agent/sector-exposure/{portfolio_id}
// Response: { total_value_gbp, sectors[{ sector, value_gbp, allocation_pct, tickers[] }] }
```

**New screen**: `SectorExposureScreen.tsx` — horizontal bar chart of sectors with tickers per sector.

### 4c. DiversificationScoreScreen → PortfolioDetail action button

**Add to**: `PortfolioDetailScreen` — new "Diversification" button (or tab within SectorExposureScreen)

**Value**: SummaryScreen has educational content about diversification but no actual score. This gives the 0-100 score + factor breakdown + recommendations.

```typescript
// GET /agent/diversification-score/{portfolio_id}
// Response: { overall_score, breakdown{hhi_concentration_score, holdings_diversity_score, ...}, recommendations[] }
```

**New screen**: `DiversificationScoreScreen.tsx` — score badge (0-100), factor breakdown bars, recommendations list.

### 4d. SpendingAnalysisScreen (new)

Actually this was already covered in 4a — the SummaryScreen IS the spending analysis screen.

### Files to Create

| File                                                  | Purpose                                          |
| ----------------------------------------------------- | ------------------------------------------------ |
| `frontend/src/services/analysis.ts`                   | New service: wrap the 4 REST endpoints           |
| `frontend/src/screens/SectorExposureScreen.tsx`       | Sector bars + ticker lists                       |
| `frontend/src/screens/DiversificationScoreScreen.tsx` | Score badge + factor breakdown + recommendations |

### Files to Modify

| File                                                       | Purpose                                                                                 |
| ---------------------------------------------------------- | --------------------------------------------------------------------------------------- |
| `frontend/src/screens/SummaryScreen.tsx`                   | Change data source from local receipts to `/agent/spending-analysis/{portfolio_id}` API |
| `frontend/src/screens/portfolio/PortfolioDetailScreen.tsx` | Add Sector Exposure and Diversification action buttons                                  |

### Complexity: Medium (new screens + data fetching + chart rendering)

---

## Phase 5: Ticker Detail Screen

**Goal**: Show company info + dividends when tapping a holding in PortfolioDetailScreen.

### Files to Create

| File                                          | Purpose                         |
| --------------------------------------------- | ------------------------------- |
| `frontend/src/screens/TickerDetailScreen.tsx` | Company profile + dividend info |

### Data Sources

```typescript
// GET /agent/ticker-info/{ticker} → company_name, sector, industry, market_cap, pe_ratio, etc.
// GET /agent/dividend-insights/{ticker} → dividend_rate, yield, payout_ratio, ex_date, 5yr growth
```

### Entry Point

- Tap a holding ticker in PortfolioDetailScreen's holdings table
- Navigate to `TickerDetailScreen` with the ticker symbol

### Complexity: Low

---

## Phase 6: Compare Tickers Screen

**Goal**: Side-by-side multi-ticker comparison — useful standalone or accessible from BenchmarkScreen.

### Files to Create

| File                                     | Purpose                         |
| ---------------------------------------- | ------------------------------- |
| `frontend/src/screens/CompareScreen.tsx` | Ticker input + comparison table |

```typescript
// POST /agent/compare-tickers { tickers: string[], metrics?: string[] }
// Response: { tickers[], comparisons[{ ticker, price, market_cap, pe_ratio, sector, ... }] }
```

### Entry Points

- From BenchmarkScreen — add "Compare Tickers" button in header
- From chat — agent could suggest `/compare AAPL MSFT` (future slash command)

### Complexity: Low

---

## Phase 7: Market News (Optional)

**Goal**: Add news section to HomeScreen or PortfolioDetailScreen.

```typescript
// GET /agent/market-news?tickers=AAPL,MSFT&max_articles=5
// Response: { tickers[], articles[{ title, publisher, link, published_date, summary }] }
```

**Note from backend**: yfinance news is limited/stale — consider before investing UI effort here.

**Complexity**: Low

---

## Implementation Order

```
Phase 1 (Tool Results in Bubbles)     → makes chat immediately useful
Phase 2 (Conversation History)        → high user value, unlocks Phase 3
Phase 3 (Feedback Comment + Title)   → quick wins
Phase 4a (SummaryScreen → API)        → replace local calc with proper categories
Phase 4b (SectorExposureScreen)      → new portfolio insight screen
Phase 4c (DiversificationScoreScreen) → new portfolio insight screen
Phase 5 (TickerDetailScreen)          → tap holding → see fundamentals
Phase 6 (CompareScreen)               → standalone ticker comparison
Phase 7 (Market News)                → optional, yfinance quality concern
```

---

## Decision History

User-locked decisions captured:

1. **Charts**: Custom `View`-based bars (no charting library dependency)
2. **Caching**: 5-min in-memory TTL per `(endpoint, portfolio_id)` in `analysis.ts`
3. **SummaryScreen portfolio_id**: Pass via navigation params/props from caller (no picker)
4. **Tool Results data**: Backend persists tool_calls + tool_results on `agent_messages` rows; the SSE stream emits them during streaming; history fetch loads persisted versions
5. **History presentation**: Nested Modal over chat Modal (existing pattern)
6. **Tool results display**: Tap-to-expand accordion in MessageBubble (compact default, full on tap)
7. **Tests**: Full integration tests per new screen (match existing repo standard)
8. **Navigation placement**: Add SectorExposure / DiversificationScore / TickerDetail to existing `PortfolioStack`

## TBD Micro-Decisions (locked with defaults)

| Decision                                                | Default                                                           | Notes                                                                           |
| ------------------------------------------------------- | ----------------------------------------------------------------- | ------------------------------------------------------------------------------- |
| Who supplies `portfolio_id` to SummaryScreen            | Navigation param from `MainTabs` bottom-tab orchestration         | SummaryScreen becomes a sibling to other tabs, takes `route.params.portfolioId` |
| TickerDetail entry point                                | Tap ticker column in `PortfolioDetailScreen` holdings table       | Wraps cell in `TouchableOpacity`                                                |
| CompareScreen entry points                              | (a) FAB in `BenchmarkScreen`, (b) chat-message agent will suggest | Avoid scatter — minimum viable (a)                                              |
| Resume history tap behaviour                            | Replace current conversation with selected one                    | Existing "new conversation" flow stays as fallback via clear button             |
| Modal close behaviour when conversation history updated | Refresh list on history screen focus rather than real-time push   | Simpler                                                                         |
| Spending analysis when user has no portfolio            | Redirect to PortfolioCreationScreen                               | Avoid empty/error state in SummaryScreen                                        |

## File Manifest Summary

### Phase 4 creates/modifies

```
create: frontend/src/services/analysis.ts
create: frontend/src/screens/SectorExposureScreen.tsx
create: frontend/src/screens/DiversificationScoreScreen.tsx
create: frontend/src/components/analysis/SectorBar.tsx           # custom View bar
create: frontend/src/components/analysis/MetricBar.tsx          # custom View bar
modify: frontend/src/screens/SummaryScreen.tsx                  # use analysis.ts; shows categories
modify: frontend/src/screens/portfolio/PortfolioDetailScreen.tsx# add 2 action buttons
modify: frontend/src/navigation/AppNavigator.tsx                # register new routes
modify: frontend/src/__tests__/screens/SectorExposureScreen.integration.test.tsx
modify: frontend/src/__tests__/screens/DiversificationScoreScreen.integration.test.tsx
modify: frontend/src/__tests__/services/analysis.unit.test.ts
modify: frontend/src/__tests__/screens/SummaryScreen.integration.test.tsx
```

### Phase 1 creates/modifies

```
create: frontend/src/components/chat/ToolResultRenderer.tsx
create: frontend/src/components/chat/ToolResultsAccordion.tsx
modify: frontend/src/components/chat/MessageBubble.tsx        # add toolResults rendering
modify: frontend/src/services/agent.ts                          # emit toolResults payloads from SSE
modify: backend/src/agent/service.py                            # persist tool_calls + tool_results on agent_messages
modify: frontend/src/__tests__/components/ToolResultRenderer.unit.test.tsx
modify: frontend/src/__tests__/screens/AgentChatScreen.integration.test.tsx
modify: backend/tests/test_agent_service.py                     # verify tool_results round-trip
```

### Phase 2 creates/modifies

```
create: frontend/src/screens/ConversationHistoryScreen.tsx
create: frontend/src/components/chat/ConversationListItem.tsx
modify: frontend/src/screens/AgentChatScreen.tsx               # add history icon
modify: frontend/src/__tests__/screens/ConversationHistoryScreen.integration.test.tsx
modify: frontend/src/__tests__/components/ConversationListItem.unit.test.tsx
```

### Phase 3 modifies

```
modify: frontend/src/screens/AgentChatScreen.tsx               # feedback modal + title header
modify: frontend/src/__tests__/screens/AgentChatScreen.integration.test.tsx
```

### Phase 5 creates/modifies

```
create: frontend/src/screens/TickerDetailScreen.tsx
modify: frontend/src/screens/portfolio/PortfolioDetailScreen.tsx # wrapper tap handler on ticker cell
modify: frontend/src/__tests__/screens/TickerDetailScreen.integration.test.tsx
```

### Phase 6 creates/modifies

```
create: frontend/src/screens/CompareScreen.tsx
modify: frontend/src/screens/portfolio/BenchmarkScreen.tsx # add "Compare" FAB
modify: frontend/src/__tests__/screens/CompareScreen.integration.test.tsx
```

### Cross-cutting modifies

```
modify: frontend/src/navigation/AppNavigator.tsx   # register all new screens
```
