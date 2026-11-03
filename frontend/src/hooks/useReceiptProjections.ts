/**
 * useReceiptProjections
 *
 * Historical and LSTM-framed investment projections for a receipt total:
 * period pickers, historical CAGRs, LSTM predictions, window growth rates, and
 * the derived per-stock display values consumed by the projection carousels.
 *
 * The two pure helpers (`buildInvestmentOptions`, `computeStockCardView`) hold
 * the maths so they can be unit-tested without rendering.
 */

import { useCallback, useEffect, useMemo, useState } from 'react';
import { brandColors, useTheme } from '../contexts/ThemeContext';
import { STOCK_PRESETS } from '../services/stockPresets';
import { periodToYears, periodLabel } from '../constants/periods';
import { subscribe } from '../services/eventBus';
import {
  getHistoricalCAGRFromToday,
  getCombinedProjection,
  getHistoricalCAGRForPeriod,
} from '../services/projectionService';
import { formatCurrencyGBP } from '../utils/formatters';

export type Prediction = { direction: 'UP' | 'FLAT' | 'DOWN'; rate: number; confidence: number };

/** Projected value of `amount` for each stock preset over `period`. */
export function buildInvestmentOptions(totalAmount: number, period: string) {
  const yrs = periodToYears(period);
  return STOCK_PRESETS.map((stock) => {
    const futureValue = totalAmount * Math.pow(1 + stock.returnRate, yrs);
    const gain = futureValue - totalAmount;
    const percentReturn = (futureValue / totalAmount - 1) * 100;
    return { ...stock, futureValue, gain, percentReturn };
  });
}

export type StockCardView = {
  futureDisplay: string;
  gainDisplay: string;
  percentDisplay: string;
  valueColor: string;
  badgeText?: string;
  badgeColor?: string;
};

export type StockCardViewArgs = {
  item: { ticker: string; name: string; returnRate: number };
  years: string;
  mode: 'past' | 'future';
  totalAmount: number;
  historicalRates: Record<string, Record<string, number>>;
  futureRates: Record<string, number>;
  predictions: Record<string, Prediction>;
  bestPastTicker?: string;
  worstPastTicker?: string;
  mutedColor: string;
};

/** Derive the display values for one projection card. */
export function computeStockCardView({
  item,
  years,
  mode,
  totalAmount,
  historicalRates,
  futureRates,
  predictions,
  bestPastTicker,
  worstPastTicker,
  mutedColor,
}: StockCardViewArgs): StockCardView {
  // Past (historical) uses API-derived total return (last/first - 1) for the selected period when available
  // Future uses preset annual returnRate and the formula amount * (1 + return_rate)^years
  const yrs = periodToYears(years);
  let computedFutureValue: number;
  let computedGain: number;
  let computedPercentReturn: number;

  if (mode === 'past') {
    const cagr = historicalRates[item.ticker]?.[years];
    if (cagr !== undefined && cagr !== null) {
      // historical CAGR -> compute future value over the period (equivalent to last/first)
      computedFutureValue = totalAmount * Math.pow(1 + cagr, yrs);
      computedGain = computedFutureValue - totalAmount;
      // show cumulative percent over the whole period (not annualized)
      computedPercentReturn = (Math.pow(1 + cagr, yrs) - 1) * 100;
    } else {
      // fallback to preset rate when historical data is unavailable
      const rate = item.returnRate;
      computedFutureValue = totalAmount * Math.pow(1 + rate, yrs);
      computedGain = computedFutureValue - totalAmount;
      computedPercentReturn = (computedFutureValue / totalAmount - 1) * 100;
    }
  } else {
    // future mode — LSTM-framed projection. The rate is the selected window's
    // historical CAGR (period-specific, changes with the year picker); the LSTM
    // model supplies the in-card direction/confidence.
    const rate = futureRates[item.ticker];
    if (rate === undefined) {
      // Prediction data unavailable for this ticker — show a neutral
      // "unavailable" state instead of a fabricated return.
      computedFutureValue = NaN;
      computedGain = NaN;
      computedPercentReturn = NaN;
    } else {
      computedFutureValue = totalAmount * Math.pow(1 + rate, yrs);
      computedGain = computedFutureValue - totalAmount;
      computedPercentReturn = (computedFutureValue / totalAmount - 1) * 100;
    }
  }

  const unavailable = Number.isNaN(computedFutureValue);
  const futureDisplay = unavailable ? '—' : formatCurrencyGBP(computedFutureValue);
  const gainDisplay = unavailable ? '—' : formatCurrencyGBP(computedGain);
  const percentDisplay = unavailable ? 'N/A' : `${computedPercentReturn.toFixed(1)}%`;

  // color: green for positive or zero, red for negative; muted when unavailable
  const valueColor = unavailable
    ? mutedColor
    : computedPercentReturn >= 0
      ? brandColors.green
      : brandColors.red;

  // determine badge: show prediction direction for future mode, Over/Underperformer for past
  let badgeTextToShow: string | undefined = undefined;
  let badgeColorToShow: string | undefined = undefined;

  if (mode === 'future') {
    const pred = predictions[item.ticker];
    if (pred) {
      const conf = pred.confidence;
      if (conf < 0.4) {
        // Low confidence (near 3-class floor) — model is a near-tie; don't
        // assert a direction.
        badgeTextToShow = `LSTM ? · ${(conf * 100).toFixed(0)}%`;
        badgeColorToShow = '#000000';
      } else if (pred.direction === 'UP') {
        badgeTextToShow = `LSTM ↑ · ${(conf * 100).toFixed(0)}%`;
        badgeColorToShow = brandColors.green;
      } else if (pred.direction === 'DOWN') {
        badgeTextToShow = `LSTM ↓ · ${(conf * 100).toFixed(0)}%`;
        badgeColorToShow = brandColors.red;
      } else {
        badgeTextToShow = `LSTM — · ${(conf * 100).toFixed(0)}%`;
        badgeColorToShow = '#000000';
      }
    } else {
      badgeTextToShow = 'LSTM unavailable';
      badgeColorToShow = '#000000';
    }
  } else {
    if (item.ticker === bestPastTicker) badgeTextToShow = 'Overperformer';
    else if (item.ticker === worstPastTicker) badgeTextToShow = 'Underperformer';
  }

  // Fallback color for non-prediction badges
  if (!badgeColorToShow) {
    badgeColorToShow =
      badgeTextToShow === 'Overperformer'
        ? brandColors.green
        : badgeTextToShow === 'Underperformer'
          ? brandColors.red
          : undefined;
  }

  return {
    futureDisplay,
    gainDisplay,
    percentDisplay,
    valueColor,
    badgeText: badgeTextToShow,
    badgeColor: badgeColorToShow,
  };
}

export default function useReceiptProjections(totalAmount: number) {
  const [selectedYears, setSelectedYears] = useState<string>('5Y');
  const [selectedFutureYears, setSelectedFutureYears] = useState<string>('5Y');
  const { theme } = useTheme();

  const investmentOptions = useMemo(
    () => buildInvestmentOptions(totalAmount, selectedYears),
    [selectedYears, totalAmount],
  );

  const futureInvestmentOptions = useMemo(
    () => buildInvestmentOptions(totalAmount, selectedFutureYears),
    [selectedFutureYears, totalAmount],
  );

  // historical CAGRs per ticker and period label (e.g. { NVDA: {"5Y": 0.18, "3Y": 0.22} })
  const [historicalRates, setHistoricalRates] = useState<Record<string, Record<string, number>>>(
    {},
  );
  const [, setRatesLoading] = useState(false);
  const [, setRatesError] = useState<string | null>(null);

  // LSTM predictions per ticker
  const [predictions, setPredictions] = useState<Record<string, Prediction>>({});

  // Period-specific growth rates (window CAGR) for the future projection, keyed
  // by ticker. Recomputed when the future year picker changes so the LSTM-framed
  // return reacts to the selected period.
  const [futureRates, setFutureRates] = useState<Record<string, number>>({});

  // load historical rates whenever selectedYears changes
  const loadHistoricalForYears = useCallback(async (period: string) => {
    setRatesLoading(true);
    setRatesError(null);
    try {
      const promises = STOCK_PRESETS.map(async (s) => {
        try {
          const cagr = await getHistoricalCAGRFromToday(s.ticker);
          return { ticker: s.ticker, total: cagr };
        } catch (e: any) {
          return { ticker: s.ticker, total: null };
        }
      });

      const results = await Promise.all(promises);
      setHistoricalRates((prev) => {
        const map: Record<string, Record<string, number>> = { ...prev };
        results.forEach((r: any) => {
          if (!map[r.ticker]) map[r.ticker] = {};
          if (r.total !== null && r.total !== undefined) map[r.ticker][period] = r.total as number;
        });
        return map;
      });
    } catch (err: any) {
      setRatesError(err?.message || String(err));
    } finally {
      setRatesLoading(false);
    }
  }, []);

  useEffect(() => {
    loadHistoricalForYears(selectedYears).catch(() => {});
    const unsub = subscribe('historical-updated', (payload) => {
      // payload may contain symbol/interval; refresh if it's one of our tracked tickers
      const updatedTicker = payload?.symbol as string | undefined;
      if (!updatedTicker || STOCK_PRESETS.some((s) => s.ticker === updatedTicker)) {
        loadHistoricalForYears(selectedYears).catch(() => {});
      }
    });
    return () => {
      unsub();
    };
  }, [loadHistoricalForYears, selectedYears]);

  // Load LSTM predictions for all tickers
  const loadPredictions = useCallback(async () => {
    try {
      const results = await Promise.allSettled(
        STOCK_PRESETS.map(async (s) => {
          const pred = await getCombinedProjection(s.ticker);
          if (!pred) return null;
          return {
            ticker: s.ticker,
            direction: pred.direction,
            rate: pred.rate,
            confidence: pred.confidence,
          };
        }),
      );
      const map: Record<string, Prediction> = {};
      results.forEach((r) => {
        if (r.status === 'fulfilled' && r.value) {
          map[r.value.ticker] = {
            direction: r.value.direction,
            rate: r.value.rate,
            confidence: r.value.confidence,
          };
        }
      });
      setPredictions(map);
    } catch {
      // Keep empty — no badges shown
    }
  }, []);

  useEffect(() => {
    loadPredictions().catch(() => {});
  }, [loadPredictions]);

  // Load window-specific future rates whenever the future period changes.
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
      // Keep previous rates on failure
    }
  }, []);

  useEffect(() => {
    loadFutureRates(selectedFutureYears).catch(() => {});
  }, [loadFutureRates, selectedFutureYears]);

  // Compute best/worst performers for past based on the currently selected years
  const { bestPastTicker, worstPastTicker } = useMemo(() => {
    try {
      const yrs = periodToYears(selectedYears);
      const list = investmentOptions.map((it) => {
        const cagr = historicalRates[it.ticker]?.[selectedYears];
        const percent =
          cagr !== undefined && cagr !== null
            ? (Math.pow(1 + cagr, yrs) - 1) * 100
            : it.percentReturn;
        return { ticker: it.ticker, percent };
      });
      if (list.length === 0) return { bestPastTicker: undefined, worstPastTicker: undefined };
      let best = list[0];
      let worst = list[0];
      for (const p of list) {
        if (p.percent > best.percent) best = p;
        if (p.percent < worst.percent) worst = p;
      }
      return { bestPastTicker: best.ticker, worstPastTicker: worst.ticker };
    } catch (e) {
      return { bestPastTicker: undefined, worstPastTicker: undefined };
    }
  }, [investmentOptions, historicalRates, selectedYears]);

  const computeProjectionView = (
    item: (typeof investmentOptions)[number],
    years: string,
    mode: 'past' | 'future',
  ) =>
    computeStockCardView({
      item,
      years,
      mode,
      totalAmount,
      historicalRates,
      futureRates,
      predictions,
      bestPastTicker,
      worstPastTicker,
      mutedColor: theme.textSecondary,
    });

  return {
    selectedYears,
    setSelectedYears,
    selectedFutureYears,
    setSelectedFutureYears,
    investmentOptions,
    futureInvestmentOptions,
    formattedYearsLabel: periodLabel(selectedYears),
    formattedFutureYearsLabel: periodLabel(selectedFutureYears),
    loadHistoricalForYears,
    loadPredictions,
    loadFutureRates,
    computeProjectionView,
  } as const;
}
