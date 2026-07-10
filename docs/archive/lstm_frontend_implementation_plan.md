# Implementation Plan: LSTM as the sole future-return metric on Receipt Details

## Overview

On `ReceiptDetailsScreen` the "could become" (future) carousel currently shows an LSTM
direction badge plus a return value that is literally the historical CAGR (`getCombinedProjection`
returns `rate: cagr`). The user wants the **LSTM to be the only predicted future-return metric**,
displayed **inside the card** (replacing the static/preset return that just copies past returns),
**varying with the year picker**, and the **bottom warning box updated** to credit the LSTM model.

Decision (confirmed with user): future numeric return = **period-specific historical CAGR** for the
selected lookback window (so it changes with the year picker), framed as the LSTM forecast via the
in-card LSTM direction/confidence badge. The backend LSTM is a directional classifier only
(`direction` + `confidence`); it outputs no numeric return, so the magnitude comes from the selected
period's own history. Frontend-only change — no ML retrain.

## Why these values look "the same as past returns" today

- `projectionService.getCombinedProjection` (line 118): `rate: cagr ?? 0.1` → uses full-history CAGR.
- `renderStockCard` future branch (lines 448-454): `rate = pred?.rate ?? investmentValue.returnRate`
  → falls back to the static preset when no prediction, i.e. a copy of a past-return assumption.
- `loadPredictions` (line 319) ignores the year, so the badge never reacts to the picker.

## Requirements

- Future card shows ONE predicted return, sourced from the LSTM/period logic — no preset fallback.
- That return changes when the future `YearSelector` (`selectedFutureYears`) changes.
- LSTM direction + confidence stays as the in-card badge (already inside `StockCard`).
- Warning box text mentions the LSTM model made these predictions.
- Past ("could have been") section is unchanged in behavior (not in scope).

## Architecture Changes

1. `frontend/src/services/projectionService.ts` — add period-aware CAGR helper; make
   `getCombinedProjection` accept an optional period so its `rate` is window-specific.
2. `frontend/src/screens/ReceiptDetailsScreen.tsx` — load per-period future rates keyed to
   `selectedFutureYears`; drive the future card from those rates + the LSTM `predictions` map;
   remove the `investmentValue.returnRate` fallback; update warning text.
3. `frontend/src/components/StockCard.tsx` — **no change required** (badge already supported).

## Implementation Steps

### Phase 1: Period-aware growth rate (projectionService.ts)

1. **Import period helpers** (projectionService.ts, top imports)
   - Action: add `import { periodToYears, periodToStartDate } from '../constants/periods';`
   - Why: needed to slice OHLCV to the selected window and convert to years.
   - Dependencies: none.
   - Risk: Low.

2. **Add `getHistoricalCAGRForPeriod`** (projectionService.ts, after `getHistoricalCAGRFromToday`)
   - Action:
     ```ts
     export async function getHistoricalCAGRForPeriod(
       ticker: string,
       periodLabel: string,
     ): Promise<number | null> {
       try {
         const ohlcv = await marketService.getOHLCV(ticker, periodToStartDate(periodLabel));
         if (ohlcv.length < 2) return null;
         const first = ohlcv[0].adjusted_close;
         const last = ohlcv[ohlcv.length - 1].adjusted_close;
         if (!first || !last || first <= 0) return null;
         const years = periodToYears(periodLabel);
         if (!(years > 0)) return null;
         return (last / first) ** (1 / years) - 1;
       } catch {
         return null;
       }
     }
     ```
   - Why: gives a window-specific growth rate that differs from the full-history CAGR used by the
     past section, and reacts to the year picker.
   - Dependencies: step 1.
   - Risk: Low. `getOHLCV(ticker, startDate)` already supports the date-range param.

3. **Make `getCombinedProjection` period-aware** (projectionService.ts, line 105)
   - Action: change signature to `getCombinedProjection(ticker: string, periodLabel?: string)` and
     compute `rate` via `getHistoricalCAGRForPeriod(ticker, periodLabel)` when a period is supplied
     (else fall back to existing `getCAGR` for backward compatibility with `SummaryScreen`).
     Keep `direction`/`confidence` from the LSTM `getPrediction` call.
   - Why: keeps `SummaryScreen.tsx` working (optional param) while enabling window-specific rates.
   - Dependencies: step 2.
   - Risk: Low — additive, backward-compatible.

### Phase 2: Wire future rates to the year picker (ReceiptDetailsScreen.tsx)

4. **Add `futureRates` state** (ReceiptDetailsScreen.tsx, near line 263)
   - Action: `const [futureRates, setFutureRates] = useState<Record<string, number>>({});`
   - Why: holds the window-specific growth rate per ticker for the active future period.
   - Dependencies: none.
   - Risk: Low.

5. **Add `loadFutureRates(period)` callback** (ReceiptDetailsScreen.tsx, near `loadHistoricalForYears`)
   - Action:
     ```ts
     const loadFutureRates = useCallback(async (period: string) => {
       try {
         const results = await Promise.all(
           STOCK_PRESETS.map(async (s) => ({
             ticker: s.ticker,
             rate: await getHistoricalCAGRForPeriod(s.ticker, period),
           })),
         );
         const map: Record<string, number> = {};
         results.forEach((r) => {
           if (r.rate !== null && r.rate !== undefined) map[r.ticker] = r.rate;
         });
         setFutureRates(map);
       } catch {
         /* keep previous */
       }
     }, []);
     ```
   - Why: separate the window-specific magnitude from the LSTM direction so we don't re-fetch the
     model on every year change.
   - Dependencies: step 2, step 4.
   - Risk: Low.

6. **Trigger `loadFutureRates` from `selectedFutureYears`** (ReceiptDetailsScreen.tsx, near line 352)
   - Action: add `useEffect(() => { loadFutureRates(selectedFutureYears).catch(() => {}); },
[loadFutureRates, selectedFutureYears]);` and call `loadFutureRates(selectedFutureYears)` inside
     `handleRefresh`.
   - Why: makes the future return change with the year picker.
   - Dependencies: step 5.
   - Risk: Low.

7. **Drive the future card from `futureRates` + LSTM, drop preset fallback**
   (ReceiptDetailsScreen.tsx, `renderStockCard` `else` branch, lines 448-455)
   - Action: replace
     ```ts
     const pred = predictions[investmentValue.ticker];
     const rate = pred?.rate ?? investmentValue.returnRate;
     ```
     with
     ```ts
     const pred = predictions[investmentValue.ticker];
     const rate = futureRates[investmentValue.ticker];
     ```
     and guard: if `rate === undefined`, render an "LSTM prediction unavailable" state
     (e.g. `futureDisplay = '—'`, `percentDisplay = 'N/A'`, neutral color, no fake return). Do NOT
     fall back to `investmentValue.returnRate`.
   - Why: this is the core fix — LSTM/period rate becomes the only future metric; the preset copy of
     past returns is removed.
   - Dependencies: step 4, 5, 6.
   - Risk: Medium — ensure the "unavailable" branch renders cleanly (no crash on undefined math).

8. **LSTM badge stays, but only when a prediction exists** (lines 470-488)
   - Action: keep the LSTM `↑/↓/—` badge from `predictions[ticker]`; when no prediction, show
     `badgeTextToShow = 'LSTM unavailable'` (or omit) instead of Overperformer/Underperformer so the
     future card never implies a non-LSTM prediction.
   - Why: keeps LSTM as the sole forward signal; removes the misleading Overperformer preset fallback
     in future mode.
   - Dependencies: step 7.
   - Risk: Low.

### Phase 3: Warning box (ReceiptDetailsScreen.tsx)

9. **Update warning text** (lines 909-912)
   - Action: replace the two sentences with something like:
     "Projections are hypothetical and generated by a deep-learning (LSTM) model that predicts each
     stock's likely direction and confidence. The projected growth rate reflects the selected
     period's historical performance and is not a guarantee of future results. Past performance does
     not predict future returns."
   - Why: satisfies the request to tell users the LSTM made these predictions.
   - Dependencies: none.
   - Risk: Low.

## Testing Strategy

- Unit (`frontend/src/__tests__/services/projectionService.unit.test.ts`): add cases for
  `getHistoricalCAGRForPeriod` (valid window, <2 points → null, API error → null) and for
  `getCombinedProjection(ticker, '5Y')` returning the window-specific rate.
- Integration (`frontend/src/__tests__/screens/ReceiptDetailsScreen.integration.test.tsx`): assert the
  future carousel return changes when `selectedFutureYears` changes, and that no preset/fallback
  return is shown when rates are unavailable. Update any assertions that expected the old
  `returnRate` behavior or the old warning string.
- Manual: open a receipt → "could become" carousel → switch future year picker → future card value
  updates; badge shows LSTM direction/confidence; bottom warning mentions LSTM.

## Risks & Mitigations

- **Short window → sparse OHLCV**: `getHistoricalCAGRForPeriod` returns `null` for <2 points → card
  shows "unavailable" rather than a wrong number. Mitigation: the guard in step 7.
- **Direction vs magnitude mismatch** (e.g. LSTM ↓ but period CAGR positive): expected with the chosen
  approach; the badge communicates direction while the number is the period growth. Acceptable per
  user decision.
- **Extra network calls per year change**: only `getHistoricalCAGRForPeriod` per ticker, not the LSTM
  model. Cheap, parallelized.
- **`SummaryScreen` regression**: mitigated by keeping `getCombinedProjection` period param optional.

## Success Criteria

- [ ] Future card return is the only predicted future metric (no preset/`returnRate` fallback).
- [ ] Future return changes when the future year picker changes.
- [ ] LSTM direction/confidence badge remains in the card and is the sole forward signal.
- [ ] When period data is unavailable, the card shows a clean "unavailable" state (no fake past return).
- [ ] Bottom warning box credits the LSTM model.
- [ ] `projectionService` unit tests + Receipt Details integration tests pass.
