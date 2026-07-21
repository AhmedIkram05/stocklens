# Implementation Plan: Frontend Agent Feature Integration

> **Scope reduced to CV-impactful work only.**

---

## Final Phase List

| Phase  | Feature                                                 | CV Signal                                                                                  | Est. Files          |
| ------ | ------------------------------------------------------- | ------------------------------------------------------------------------------------------ | ------------------- |
| **1**  | Tool Results in Message Bubbles                         | **HIGH** — SSE streaming, renderer pattern, real-time structured data                      | 4 create + 5 modify |
| **2**  | Conversation History UI + Feedback Comment + Auto-Title | **MEDIUM** — list CRUD, nested modal UX, chat state management                             | 3 create + 2 modify |
| **3a** | SectorExposureScreen                                    | **MEDIUM-HIGH** — custom bar chart components, portfolio domain math, yfinance integration | 2 create + 3 modify |
| **3b** | DiversificationScoreScreen                              | **MEDIUM-HIGH** — score algorithm visualization, custom bars, recommendations engine       | 1 create + 2 modify |
| —      | Quiet SummaryScreen upgrade                             | **Low**                                                                                    | 1 modify            |

---

## Phase 1: Tool Results in Message Bubbles

**Why**: The differentiating technical feature. Shows real-time SSE streaming with structured JSON rendering. Each tool maps to a specialized renderer — shows architectural thinking.

### Files

```
create: frontend/src/components/chat/ToolResultRenderer.tsx   # renderer registry + 16 renderers
create: frontend/src/components/chat/ToolResultsAccordion.tsx   # tap-to-expand accordion
modify: frontend/src/components/chat/MessageBubble.tsx          # render toolResults accordion
modify: frontend/src/services/agent.ts                         # parse tool result from SSE tool_end payload
modify: backend/src/agent/service.py                          # emit tool result in SSE tool_end payload + persist
modify: frontend/src/__tests__/components/ToolResultRenderer.unit.test.tsx
modify: frontend/src/__tests__/screens/AgentChatScreen.integration.test.tsx
modify: backend/tests/test_agent_service.py
```

### SSE Protocol Change

Currently `tool_end` SSE event only emits the tool name. Backend must be updated to include the result payload:

```python
# SSE event: event: tool_end
# data: {"tool_name": "get_portfolio_holdings", "result": "<base64 JSON of result>"}
# Frontend decodes base64 → JSON.parse → ToolResultRenderer
```

Result is base64-encoded JSON to avoid SSE formatting issues with complex nested JSON. This avoids a second HTTP round-trip for tool results.

### Renderer Map (16 tools → renderers)

| Tool                                  | Renderer Type     | Description                          |
| ------------------------------------- | ----------------- | ------------------------------------ |
| `get_portfolio_summary`               | Key-value card    | Total value, cost basis, P&L         |
| `get_portfolio_holdings`              | Table             | Ticker, shares, price, P&L           |
| `get_sector_exposure`                 | Horizontal bars   | Sector allocation %                  |
| `get_portfolio_performance`           | Metrics card      | TWR, day change, total gain          |
| `compare_to_benchmark`                | Comparison card   | Alpha, tracking error, info ratio    |
| `get_portfolio_diversification_score` | Score + bars      | 0-100 score, factor breakdown        |
| `compare_tickers_side_by_side`        | Table             | Ticker × metric matrix               |
| `get_market_ohlcv`                    | Mini table        | Date, O, H, L, C, V                  |
| `get_market_quote`                    | Quote card        | Price, change, volume                |
| `get_ticker_info`                     | Info card         | Company name, sector, market cap, PE |
| `get_market_news`                     | Article list      | Title, source, time                  |
| `get_lstm_forecast`                   | Direction badge   | UP/FLAT/DOWN + confidence %          |
| `get_spending_analysis`               | Category bars     | Category, amount, %                  |
| `get_recent_transactions`             | Transaction table | Date, type, amount                   |
| `get_cash_flow_summary`               | Summary card      | Deposits, count, last                |
| `get_dividend_insights`               | Dividend card     | Yield, payout ratio, ex-date         |
| _(fallback)_                          | JSON dump         | Monospace pretty-print               |

### Generic Fallback

For any tool without a custom renderer: pretty-print the JSON in a scrollable `<Text>` with monospace font.

---

## Phase 2: Conversation History UI + Feedback Comment + Auto-Title

**Why**: High user value. List UI with CRUD, nested modal UX, chat state management. Not architecturally interesting but completes the chat experience.

### Files

```
create: frontend/src/screens/ConversationHistoryScreen.tsx    # list of past conversations
create: frontend/src/components/chat/ConversationListItem.tsx # row: title, count, time, delete
modify: frontend/src/screens/AgentChatScreen.tsx              # history icon + feedback modal + title
modify: frontend/src/__tests__/screens/ConversationHistoryScreen.integration.test.tsx
modify: frontend/src/__tests__/components/ConversationListItem.unit.test.tsx
```

### History UI

- Header icon: `clock-history` (Ionicons)
- List rows: auto-title, message count, relative timestamp
- Tap → load conversation, replace messages state
- Swipe-left → delete → `deleteConversation`

### Feedback Comment

- Thumbs up/down tapped → small modal with textarea "Tell us more (optional)"
- Calls `submitFeedback(rating, traceId, comment)` — `comment` param already in API, never sent before

### Auto-Title Display

- `ConversationSummary.title` in header
- Show in history list rows

---

## Phase 3a: SectorExposureScreen

**Why**: Custom bar chart components (no charting library). Data comes from live yfinance sector mapping via Redis-cached endpoint. Visually rich, good for demo.

### Redis Caching

`tool_endpoints.py` sector-exposure endpoint is wrapped with 5-min Redis TTL:

- Key: `agent:sector:{portfolio_id}`
- yfinance calls are expensive — caching prevents hammering on every screen open
- Same pattern as existing quote cache (60s) and prediction cache (6h)

### Files

```
create: frontend/src/screens/SectorExposureScreen.tsx         # bar chart + ticker lists
create: frontend/src/components/analysis/SectorBar.tsx       # custom View horizontal bar
modify: frontend/src/screens/portfolio/PortfolioDetailScreen.tsx  # "Sector Exposure" button
modify: frontend/src/navigation/AppNavigator.tsx              # register route
modify: frontend/src/__tests__/screens/SectorExposureScreen.integration.test.tsx
```

### Data

```
GET /agent/sector-exposure/{portfolio_id}
→ { total_value_gbp, sectors[{ sector, value_gbp, allocation_pct, tickers[] }] }
```

### Entry Point

- "Sector Exposure" button in `PortfolioDetailScreen` actions row

---

## Phase 3b: DiversificationScoreScreen

**Why**: Score algorithm visualization. HHI breakdown with custom bars. Shows ability to implement financial math + render it clearly.

### Files

```
create: frontend/src/screens/DiversificationScoreScreen.tsx   # score badge + bars + recommendations
modify: frontend/src/screens/portfolio/PortfolioDetailScreen.tsx  # "Diversification" button
modify: frontend/src/__tests__/screens/DiversificationScoreScreen.integration.test.tsx
```

### Data

```
GET /agent/diversification-score/{portfolio_id}
→ { overall_score, breakdown{ holdings_diversity_score, hhi_concentration_score,
  top_holding_weight_score, sector_diversity_score }, recommendations[] }
```

### Entry Point

- "Diversification" button in `PortfolioDetailScreen` actions row

---

## Quiet SummaryScreen Upgrade

`SummaryScreen` changes data source from local receipt calculation to `GET /agent/spending-analysis/{portfolio_id}` — shows categorized spending + MoM change. No new files. Just modify the existing screen to call the API instead of computing from receipts.

---

## File Manifest Final

```
NEW (create):
  frontend/src/components/chat/ToolResultRenderer.tsx          # Phase 1
  frontend/src/components/chat/ToolResultsAccordion.tsx         # Phase 1
  frontend/src/screens/ConversationHistoryScreen.tsx            # Phase 2
  frontend/src/components/chat/ConversationListItem.tsx        # Phase 2
  frontend/src/screens/SectorExposureScreen.tsx                # Phase 3a
  frontend/src/components/analysis/SectorBar.tsx               # Phase 3a
  frontend/src/screens/DiversificationScoreScreen.tsx          # Phase 3b
  total: 7 new files

MODIFY (existing):
  frontend/src/components/chat/MessageBubble.tsx                # Phase 1
  frontend/src/services/agent.ts                                # Phase 1
  backend/src/agent/service.py                                  # Phase 1
  frontend/src/screens/AgentChatScreen.tsx                     # Phase 1 + 2
  frontend/src/screens/portfolio/PortfolioDetailScreen.tsx     # Phase 3a + 3b
  frontend/src/navigation/AppNavigator.tsx                      # Phase 3a + 3b
  frontend/src/screens/SummaryScreen.tsx                       # quiet upgrade
  total: ~8 modified files

NEW TESTS (mirror new files):
  frontend/src/__tests__/components/ToolResultRenderer.unit.test.tsx
  frontend/src/__tests__/screens/AgentChatScreen.integration.test.tsx
  backend/tests/test_agent_service.py
  frontend/src/__tests__/screens/ConversationHistoryScreen.integration.test.tsx
  frontend/src/__tests__/components/ConversationListItem.unit.test.tsx
  frontend/src/__tests__/screens/SectorExposureScreen.integration.test.tsx
  frontend/src/__tests__/screens/DiversificationScoreScreen.integration.test.tsx
```

---

## Implementation Order

```
Phase 1  →  Tool Results in Bubbles           [HIGHEST CV VALUE — streaming + rendering]
Phase 2  →  Conversation History + Feedback   [completes chat UX]
Phase 3a →  SectorExposureScreen              [custom charts, yfinance]
Phase 3b →  DiversificationScoreScreen         [algorithm visualization]
Quiet    →  SummaryScreen spending upgrade     [no new files]
```

---

## Decision History

| Decision                          | Choice                                                    |
| --------------------------------- | --------------------------------------------------------- |
| Charts                            | Custom `View`-based bars (no charting lib)                |
| Phase 4b/4c yfinance caching      | **5-min Redis TTL in `tool_endpoints.py`**                |
| SummaryScreen portfolio_id        | Via route params (no picker needed)                       |
| Phase 1 tool results data         | **Stream result in SSE `tool_end` payload** (base64 JSON) |
| History presentation              | Nested Modal over chat Modal                              |
| Tool results display              | Tap-to-expand accordion                                   |
| Tests                             | Full integration tests per new screen                     |
| Navigation                        | Add to existing `PortfolioStack`                          |
| Phase 3 (Feedback)                | Merged into Phase 2                                       |
| Phase 5 (TickerDetailScreen)      | Dropped — agent covers it                                 |
| Phase 6 (CompareScreen)           | Dropped — low CV signal                                   |
| Phase 7 (Market News)             | Dropped — yfinance quality concern                        |
| Phase 4a (SummaryScreen)          | Merged quietly into Phase 3a/3b work                      |
| Phase 4a (SummaryScreen separate) | Merged quietly into Phase 3a/3b work                      |
