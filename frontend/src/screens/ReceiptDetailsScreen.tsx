/**
 * ReceiptDetailsScreen
 *
 * Detailed view for a single receipt with investment projections.
 */

import React, { useMemo, useState, useEffect, useCallback } from 'react';
import {
  View,
  Text,
  StyleSheet,
  Alert,
  ScrollView,
  TouchableOpacity,
  RefreshControl,
} from 'react-native';
import type { TextStyle, ViewStyle } from 'react-native';
import ScreenContainer from '../components/ScreenContainer';
import BackButton from '../components/BackButton';
import { RouteProp, useNavigation, useRoute } from '@react-navigation/native';
import { Ionicons } from '@expo/vector-icons';
import type { RootStackParamList } from '../navigation/AppNavigator';
import { brandColors } from '../contexts/ThemeContext';
import { radii, spacing, typography } from '../styles/theme';
import { useBreakpoint } from '../hooks/useBreakpoint';
import DangerButton from '../components/DangerButton';
import ResponsiveContainer from '../components/ResponsiveContainer';
import { receiptService } from '../services/receipts';
import { categoryService, type Category } from '../services/categories';
import { portfolioService, Portfolio } from '../services/portfolios';
import { useTheme } from '../contexts/ThemeContext';
import { formatCurrencyRounded } from '../utils/formatters';

// Route prop for receipt details screen
type ReceiptDetailsRouteProp = RouteProp<RootStackParamList, 'ReceiptDetails'>;

import { STOCK_PRESETS } from '../services/stockPresets';
import { periodToYears, periodLabel } from '../constants/periods';

import { subscribe, emit } from '../services/eventBus';
import {
  getHistoricalCAGRFromToday,
  getCombinedProjection,
  getHistoricalCAGRForPeriod,
} from '../services/projectionService';
import { formatCurrencyGBP, formatRelativeDate } from '../utils/formatters';
import StockCard from '../components/StockCard';
import ReceiptCard from '../components/ReceiptCard';
import ProjectionCarouselSection from '../components/ProjectionCarouselSection';
import EditValueModal from '../components/EditValueModal';
import CategoryPickerModal from '../components/CategoryPickerModal';
import DepositModal from '../components/DepositModal';
import ReceiptMetaPanel from '../components/ReceiptMetaPanel';
import ReceiptItemsCard from '../components/ReceiptItemsCard';

import type { SourceBadgeKey } from '../components/ReceiptCard';

const SOURCE_BADGE: Record<SourceBadgeKey, { label: string; color: string }> = {
  regex: { label: 'Regex', color: '#22c55e' },
  cascade: { label: 'AI Enhanced', color: '#3b82f6' },
  degraded: { label: 'Low Quality', color: '#f97316' },
  failed: { label: 'Failed', color: '#ef4444' },
};

/** Projected value of `amount` for each stock preset over `period`. */
function buildInvestmentOptions(totalAmount: number, period: string) {
  const yrs = periodToYears(period);
  return STOCK_PRESETS.map((stock) => {
    const futureValue = totalAmount * Math.pow(1 + stock.returnRate, yrs);
    const gain = futureValue - totalAmount;
    const percentReturn = (futureValue / totalAmount - 1) * 100;
    return { ...stock, futureValue, gain, percentReturn };
  });
}

/** Receipt details and projection screen. */
export default function ReceiptDetailsScreen() {
  const navigation = useNavigation<any>();
  const route = useRoute<ReceiptDetailsRouteProp>();
  const {
    receiptId,
    totalAmount: initialAmount,
    date,
    image,
    confidence,
    processingTimeMs,
    merchantName: initialMerchant,
    lineItems: initialItems,
  } = route.params;
  const source = route.params.source as SourceBadgeKey | undefined;
  const confidencePct = confidence != null ? Math.round(confidence * 100) : null;

  const [selectedYears, setSelectedYears] = useState<string>('5Y');
  const [selectedFutureYears, setSelectedFutureYears] = useState<string>('5Y');

  // Load the authoritative receipt (merchant + line items) from the backend.
  // The scan endpoint already persisted these; route params are only a fast path.
  const [receipt, setReceipt] = useState<any>(null);
  const [refreshing, setRefreshing] = useState(false);
  const loadReceiptDetail = useCallback(async () => {
    if (!receiptId) return;
    try {
      const r = await receiptService.getById(receiptId);
      if (r) setReceipt(r);
    } catch {
      // Keep previous receipt on failure
    }
  }, [receiptId]);

  useEffect(() => {
    loadReceiptDetail().catch(() => {});
  }, [loadReceiptDetail]);

  const totalAmount = receipt?.total_amount ?? initialAmount ?? 0;
  const merchantName: string | null = receipt?.merchant_name ?? initialMerchant ?? null;
  const rawLineItems = receipt?.line_items;
  const lineItems: any[] = rawLineItems
    ? Array.isArray(rawLineItems)
      ? rawLineItems
      : Object.values(rawLineItems)
    : (initialItems ?? []);

  // Cross-check: sum of line items vs scanned total (flags likely OCR total misread)
  const itemsSubtotal = lineItems.reduce(
    (sum: number, it: any) => sum + (Number(it?.price ?? it?.amount ?? 0) || 0),
    0,
  );
  const totalMismatch =
    lineItems.length > 0 &&
    Math.abs(itemsSubtotal - totalAmount) > Math.max(0.02, (totalAmount || 0) * 0.01);

  // Category list (for display + user correction of the OCR-assigned category).
  const [categories, setCategories] = useState<Category[]>([]);
  const [categoryModalVisible, setCategoryModalVisible] = useState(false);
  const [categorySaving, setCategorySaving] = useState(false);
  const loadCategories = useCallback(async () => {
    try {
      const cs = await categoryService.listCategories();
      setCategories(cs);
    } catch {
      // Keep previous categories on failure
    }
  }, []);

  useEffect(() => {
    loadCategories().catch(() => {});
  }, [loadCategories]);

  // Merchant edit modal state
  const [merchantModalVisible, setMerchantModalVisible] = useState(false);
  const [merchantEditValue, setMerchantEditValue] = useState('');
  const [merchantSaving, setMerchantSaving] = useState(false);

  // Total amount edit modal state
  const [amountModalVisible, setAmountModalVisible] = useState(false);
  const [amountEditValue, setAmountEditValue] = useState('');
  const [amountSaving, setAmountSaving] = useState(false);

  // Date edit modal state
  const [dateModalVisible, setDateModalVisible] = useState(false);
  const [dateEditValue, setDateEditValue] = useState('');
  const [dateSaving, setDateSaving] = useState(false);

  const categoryName: string | null = categories.length
    ? (categories.find((c) => c.id === (receipt?.category_id ?? null))?.name ?? null)
    : null;

  async function handleSelectCategory(catId: string) {
    if (!receiptId) return;
    setCategorySaving(true);
    try {
      await receiptService.update(receiptId, { category_id: catId });
      setReceipt((prev: any) => (prev ? { ...prev, category_id: catId } : prev));
      try {
        emit('receipts-changed', { id: receiptId, action: 'updated' });
      } catch (e) {}
      setCategoryModalVisible(false);
    } catch {
      Alert.alert('Error', 'Could not update category');
    } finally {
      setCategorySaving(false);
    }
  }
  async function handleUpdateMerchant() {
    if (!receiptId || !merchantEditValue.trim()) return;
    setMerchantSaving(true);
    try {
      await receiptService.update(receiptId, { merchant_name: merchantEditValue.trim() });
      setReceipt((prev: any) =>
        prev ? { ...prev, merchant_name: merchantEditValue.trim() } : prev,
      );
      try {
        emit('receipts-changed', { id: receiptId, action: 'updated' });
      } catch (e) {}
      setMerchantModalVisible(false);
    } catch {
      Alert.alert('Error', 'Could not update merchant');
    } finally {
      setMerchantSaving(false);
    }
  }

  async function handleUpdateAmount() {
    if (!receiptId || !amountEditValue.trim()) return;
    const parsed = parseFloat(amountEditValue.trim());
    if (isNaN(parsed) || parsed <= 0) {
      Alert.alert('Invalid amount', 'Enter a valid positive number');
      return;
    }
    setAmountSaving(true);
    try {
      await receiptService.update(receiptId, { total_amount: parsed });
      setReceipt((prev: any) => (prev ? { ...prev, total_amount: parsed } : prev));
      try {
        emit('receipts-changed', { id: receiptId, action: 'updated' });
      } catch (e) {}
      setAmountModalVisible(false);
    } catch {
      Alert.alert('Error', 'Could not update amount');
    } finally {
      setAmountSaving(false);
    }
  }

  async function handleUpdateDate() {
    if (!receiptId || !dateEditValue.trim()) return;
    // Basic date validation: must be YYYY-MM-DD
    const trimmed = dateEditValue.trim();
    if (!/^\d{4}-\d{2}-\d{2}$/.test(trimmed)) {
      Alert.alert('Invalid date', 'Enter date as YYYY-MM-DD');
      return;
    }
    setDateSaving(true);
    try {
      await receiptService.update(receiptId, { transaction_date: trimmed });
      setReceipt((prev: any) => (prev ? { ...prev, transaction_date: trimmed } : prev));
      try {
        emit('receipts-changed', { id: receiptId, action: 'updated' });
      } catch (e) {}
      setDateModalVisible(false);
    } catch {
      Alert.alert('Error', 'Could not update date');
    } finally {
      setDateSaving(false);
    }
  }

  const { contentHorizontalPadding, sectionVerticalSpacing, isSmallPhone, isTablet, width } =
    useBreakpoint();
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
  const [predictions, setPredictions] = useState<
    Record<string, { direction: 'UP' | 'FLAT' | 'DOWN'; rate: number; confidence: number }>
  >({});

  // Period-specific growth rates (window CAGR) for the future projection, keyed
  // by ticker. Recomputed when the future year picker changes so the LSTM-framed
  // return reacts to the selected period.
  const [futureRates, setFutureRates] = useState<Record<string, number>>({});

  // Deposit into portfolio
  const [depositModalVisible, setDepositModalVisible] = useState(false);
  const [portfolioList, setPortfolioList] = useState<Portfolio[]>([]);
  const [portfoliosLoading, setPortfoliosLoading] = useState(false);
  const [depositingPid, setDepositingPid] = useState<string | null>(null);

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
      const map: Record<
        string,
        { direction: 'UP' | 'FLAT' | 'DOWN'; rate: number; confidence: number }
      > = {};
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

  const handleRefresh = useCallback(async () => {
    setRefreshing(true);
    await Promise.allSettled([
      loadReceiptDetail(),
      loadCategories(),
      loadHistoricalForYears(selectedYears),
      loadPredictions(),
      loadFutureRates(selectedFutureYears),
    ]);
    setRefreshing(false);
  }, [
    loadReceiptDetail,
    loadCategories,
    loadHistoricalForYears,
    loadPredictions,
    loadFutureRates,
    selectedYears,
    selectedFutureYears,
  ]);

  async function handleOpenDeposit() {
    setDepositModalVisible(true);
    setPortfoliosLoading(true);
    try {
      const data = await portfolioService.listPortfolios();
      setPortfolioList(data);
    } catch {
      Alert.alert('Error', 'Could not load portfolios');
      setDepositModalVisible(false);
    } finally {
      setPortfoliosLoading(false);
    }
  }

  async function handleSelectPortfolio(pid: string) {
    setDepositingPid(pid);
    try {
      await portfolioService.createCashFlow(pid, {
        amount: totalAmount,
        source: 'receipt',
        source_id: receiptId ?? undefined,
        notes: `Deposit from ${formattedAmount} receipt`,
      });
      Alert.alert('Deposited', `${formatCurrencyRounded(totalAmount)} deposited into portfolio`);
      setDepositModalVisible(false);
    } catch {
      Alert.alert('Error', 'Failed to deposit. Please try again.');
    } finally {
      setDepositingPid(null);
    }
  }

  const cardSpacing = isTablet ? spacing.lg : spacing.md;
  const cardWidth = useMemo(() => {
    if (isTablet) {
      return Math.min(320, width * 0.38);
    }
    if (isSmallPhone) {
      return Math.max(240, width * 0.72);
    }
    return Math.min(300, Math.max(260, width * 0.6));
  }, [isSmallPhone, isTablet, width]);

  const snapInterval = useMemo(() => cardWidth + cardSpacing, [cardSpacing, cardWidth]);

  const formattedAmount = formatCurrencyGBP(totalAmount || 0);

  const formattedYearsLabel = periodLabel(selectedYears);
  const formattedFutureYearsLabel = periodLabel(selectedFutureYears);

  const renderStockCard = (
    investmentValue: (typeof investmentOptions)[number],
    isLastItem: boolean,
    years: string = selectedYears,
    mode: 'past' | 'future' = 'past',
  ) => {
    // Past (historical) uses API-derived total return (last/first - 1) for the selected period when available
    // Future uses preset annual returnRate and the formula amount * (1 + return_rate)^years
    const yrs = periodToYears(years);
    let computedFutureValue: number;
    let computedGain: number;
    let computedPercentReturn: number;

    if (mode === 'past') {
      const cagr = historicalRates[investmentValue.ticker]?.[years];
      if (cagr !== undefined && cagr !== null) {
        // historical CAGR -> compute future value over the period (equivalent to last/first)
        computedFutureValue = totalAmount * Math.pow(1 + cagr, yrs);
        computedGain = computedFutureValue - totalAmount;
        // show cumulative percent over the whole period (not annualized)
        computedPercentReturn = (Math.pow(1 + cagr, yrs) - 1) * 100;
      } else {
        // fallback to historical calculation at render time (best-effort) or preset if unavailable
        // use projectUsingHistoricalCAGR synchronously is not possible; fallback to preset rate
        const rate = investmentValue.returnRate;
        computedFutureValue = totalAmount * Math.pow(1 + rate, yrs);
        computedGain = computedFutureValue - totalAmount;
        computedPercentReturn = (computedFutureValue / totalAmount - 1) * 100;
      }
    } else {
      // future mode — LSTM-framed projection. The rate is the selected window's
      // historical CAGR (period-specific, changes with the year picker); the LSTM
      // model supplies the in-card direction/confidence. No preset/fallback copy
      // of past returns.
      const rate = futureRates[investmentValue.ticker];
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
      ? theme.textSecondary
      : computedPercentReturn >= 0
        ? brandColors.green
        : brandColors.red;

    // determine badge: show prediction direction for future mode, Over/Underperformer for past
    let badgeTextToShow: string | undefined = undefined;
    let badgeColorToShow: string | undefined = undefined;

    if (mode === 'future') {
      const pred = predictions[investmentValue.ticker];
      if (pred) {
        const conf = pred.confidence;
        if (conf < 0.4) {
          // Low confidence (near 3-class floor) — model is a near-tie; don't
          // assert a direction. ponytail: threshold pinned to CONTEXT.md <0.4.
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
      if (investmentValue.ticker === bestPastTicker) badgeTextToShow = 'Overperformer';
      else if (investmentValue.ticker === worstPastTicker) badgeTextToShow = 'Underperformer';
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

    return (
      <StockCard
        name={investmentValue.name}
        ticker={investmentValue.ticker}
        futureDisplay={futureDisplay}
        formattedAmount={formattedAmount}
        percentDisplay={percentDisplay}
        gainDisplay={gainDisplay}
        valueColor={valueColor}
        isLast={isLastItem}
        onPress={() => {}}
        cardWidth={cardWidth}
        badgeText={badgeTextToShow}
        badgeColor={badgeColorToShow}
      />
    );
  };

  // Compute best/worst performers for past based on the currently selected years
  const { bestPastTicker, worstPastTicker } = React.useMemo(() => {
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

  // Main render
  return (
    <ScreenContainer contentStyle={{ paddingVertical: sectionVerticalSpacing }}>
      <ScrollView
        contentContainerStyle={[styles.content, isSmallPhone && styles.contentCompact]}
        showsVerticalScrollIndicator={false}
        refreshControl={
          <RefreshControl
            refreshing={refreshing}
            onRefresh={handleRefresh}
            tintColor={theme.primary}
            colors={[theme.primary]}
          />
        }
      >
        <View style={[styles.headerRow, isSmallPhone && styles.headerRowCompact]}>
          <BackButton />
        </View>

        <ResponsiveContainer maxWidth={width - contentHorizontalPadding * 2}>
          <>
            <View style={{ width: '100%' }}>
              <ReceiptCard
                image={image}
                amount={formattedAmount}
                label={formatRelativeDate(date)}
                time={new Date(date).toLocaleString()}
                onPress={() => {}}
                source={source}
                confidence={confidence}
              />
            </View>

            {/* Total Amount — tappable to edit */}
            <ReceiptMetaPanel
              label="Total Amount"
              value={formatCurrencyGBP(totalAmount || 0)}
              onPress={() => {
                setAmountEditValue(totalAmount > 0 ? totalAmount.toFixed(2) : '');
                setAmountModalVisible(true);
              }}
              accessibilityLabel="Edit total amount"
            />

            {/* Date — tappable to edit */}
            <ReceiptMetaPanel
              label="Date"
              value={formatRelativeDate(receipt?.transaction_date ?? date)}
              onPress={() => {
                setDateEditValue(receipt?.transaction_date ?? date ?? '');
                setDateModalVisible(true);
              }}
              accessibilityLabel="Edit transaction date"
            />

            {merchantName && (
              <ReceiptMetaPanel
                label="Merchant"
                value={merchantName}
                onPress={() => {
                  setMerchantEditValue(merchantName);
                  setMerchantModalVisible(true);
                }}
                accessibilityLabel="Edit merchant name"
              />
            )}

            {lineItems.length > 0 && (
              <ReceiptItemsCard
                items={lineItems}
                subtotal={itemsSubtotal}
                totalAmount={totalAmount}
                mismatch={totalMismatch}
              />
            )}

            <ReceiptMetaPanel
              label="Category"
              value={categoryName ?? 'Uncategorised'}
              onPress={() => setCategoryModalVisible(true)}
              accessibilityLabel="Edit category"
            />

            {source && (
              <View style={[styles.cascadePanel, { backgroundColor: theme.surface }]}>
                <Text style={[styles.cascadeTitle, { color: theme.text }]}>Extraction Details</Text>
                <View style={styles.cascadeRow}>
                  <Text style={[styles.cascadeLabel, { color: theme.textSecondary }]}>Source</Text>
                  <View
                    style={[
                      styles.sourceBadge,
                      {
                        backgroundColor:
                          (SOURCE_BADGE[source as SourceBadgeKey]?.color ?? '#6b7280') + '20',
                      },
                    ]}
                  >
                    <Text
                      style={[
                        styles.sourceBadgeText,
                        { color: SOURCE_BADGE[source as SourceBadgeKey]?.color ?? '#6b7280' },
                      ]}
                    >
                      {SOURCE_BADGE[source as SourceBadgeKey]?.label || source}
                    </Text>
                  </View>
                </View>
                {confidencePct != null && confidencePct > 0 && (
                  <View style={styles.cascadeRow}>
                    <Text style={[styles.cascadeLabel, { color: theme.textSecondary }]}>
                      Confidence
                    </Text>
                    <View style={styles.confidenceContainer}>
                      <View style={styles.confidenceBarBg}>
                        <View
                          style={[
                            styles.confidenceBarFill,
                            {
                              width: `${confidencePct}%`,
                              backgroundColor:
                                confidencePct > 70
                                  ? '#22c55e'
                                  : confidencePct > 40
                                    ? '#f97316'
                                    : '#ef4444',
                            },
                          ]}
                        />
                      </View>
                      <Text style={[styles.confidenceText, { color: theme.text }]}>
                        {confidencePct}%
                      </Text>
                    </View>
                  </View>
                )}
                {processingTimeMs != null && processingTimeMs > 0 && (
                  <View style={styles.cascadeRow}>
                    <Text style={[styles.cascadeLabel, { color: theme.textSecondary }]}>
                      Processing Time
                    </Text>
                    <Text style={[styles.cascadeValue, { color: theme.text }]}>
                      {processingTimeMs < 1000
                        ? `${Math.round(processingTimeMs)}ms`
                        : `${(processingTimeMs / 1000).toFixed(1)}s`}
                    </Text>
                  </View>
                )}
              </View>
            )}

            {/* Spacer before investment projections */}
            <View style={{ height: spacing.xl }} />

            <ProjectionCarouselSection
              title={`Your ${formattedAmount} could have been...`}
              subtitle={`If invested ${formattedYearsLabel} ago`}
              periodValue={selectedYears}
              onPeriodChange={setSelectedYears}
              compact={isSmallPhone}
              carouselTitle="Investment Outlook"
              carouselSubtitle="Swipe to explore different stocks"
              data={investmentOptions}
              keyExtractor={(item: any) => item.ticker}
              renderItem={({ item, index }) =>
                renderStockCard(item, index === investmentOptions.length - 1, selectedYears, 'past')
              }
              snapInterval={snapInterval}
            />

            <View style={[styles.sectionSpacing, { height: sectionVerticalSpacing }]} />

            <ProjectionCarouselSection
              title={`Your ${formattedAmount} could become...`}
              subtitle={`If invested today for ${formattedFutureYearsLabel}`}
              periodValue={selectedFutureYears}
              onPeriodChange={setSelectedFutureYears}
              compact={isSmallPhone}
              carouselTitle="Potential Growth"
              carouselSubtitle="LSTM badge = model's predicted direction + confidence (5 trading days)"
              data={futureInvestmentOptions}
              keyExtractor={(item: any) => `future-${item.ticker}`}
              renderItem={({ item, index }) =>
                renderStockCard(
                  item,
                  index === futureInvestmentOptions.length - 1,
                  selectedFutureYears,
                  'future',
                )
              }
              snapInterval={snapInterval}
            />
          </>
        </ResponsiveContainer>

        <TouchableOpacity
          style={[
            styles.depositButton,
            { backgroundColor: brandColors.blue, marginBottom: spacing.md },
          ]}
          onPress={handleOpenDeposit}
          activeOpacity={0.8}
        >
          <View style={{ flexDirection: 'row', alignItems: 'center', justifyContent: 'center' }}>
            <Ionicons
              name="wallet-outline"
              size={18}
              color={brandColors.white}
              style={{ marginRight: 8 }}
            />
            <Text style={{ color: brandColors.white, ...typography.button }}>
              Deposit into Portfolio
            </Text>
          </View>
        </TouchableOpacity>

        <DangerButton
          accessibilityLabel="Delete receipt"
          onPress={() =>
            Alert.alert('Delete receipt', 'Are you sure you want to delete this receipt?', [
              { text: 'Cancel', style: 'cancel' },
              {
                text: 'Delete',
                style: 'destructive',
                onPress: async () => {
                  try {
                    if (!receiptId) {
                      Alert.alert('Cannot delete', 'Receipt has not been saved yet');
                      return;
                    }
                    await receiptService.delete(receiptId);
                    // notify listeners that receipts changed
                    try {
                      emit('receipts-changed', { id: receiptId, action: 'deleted' });
                    } catch (e) {}
                    Alert.alert('Deleted', 'Receipt deleted');
                    navigation.navigate('MainTabs' as any);
                  } catch (e: any) {
                    Alert.alert('Delete failed', e?.message || 'Failed to delete receipt');
                  }
                },
              },
            ])
          }
        >
          <View style={{ flexDirection: 'row', alignItems: 'center', justifyContent: 'center' }}>
            <Ionicons
              name="trash-outline"
              size={18}
              color={brandColors.white}
              style={{ marginRight: 10 }}
            />
            <Text style={{ color: brandColors.white, ...typography.button }}>Delete Receipt</Text>
          </View>
        </DangerButton>

        <View
          style={[
            styles.warningBox,
            isSmallPhone && styles.warningBoxCompact,
            { backgroundColor: theme.surface },
          ]}
        >
          <Ionicons name="warning" size={28} color={brandColors.red} style={styles.warningIcon} />
          <Text style={[styles.warningText, { color: theme.text }]}>
            Projections are hypothetical and generated by a deep-learning (LSTM) model that predicts
            each stock's likely direction and confidence. The projected growth rate reflects the
            selected period's historical performance and is not a guarantee of future results. Past
            performance does not predict future returns.
          </Text>
        </View>
      </ScrollView>

      <DepositModal
        visible={depositModalVisible}
        formattedAmount={formattedAmount}
        portfolios={portfolioList}
        loading={portfoliosLoading}
        depositingPid={depositingPid}
        onSelectPortfolio={handleSelectPortfolio}
        onClose={() => setDepositModalVisible(false)}
      />

      <CategoryPickerModal
        visible={categoryModalVisible}
        categories={categories}
        selectedCategoryId={receipt?.category_id ?? null}
        saving={categorySaving}
        onSelectCategory={handleSelectCategory}
        onClose={() => setCategoryModalVisible(false)}
      />

      <EditValueModal
        visible={merchantModalVisible}
        title="Edit merchant name"
        value={merchantEditValue}
        onChangeText={setMerchantEditValue}
        onSave={handleUpdateMerchant}
        onClose={() => setMerchantModalVisible(false)}
        saving={merchantSaving}
        placeholder="Enter merchant name"
      />

      <EditValueModal
        visible={amountModalVisible}
        title="Edit total amount"
        value={amountEditValue}
        onChangeText={setAmountEditValue}
        onSave={handleUpdateAmount}
        onClose={() => setAmountModalVisible(false)}
        saving={amountSaving}
        placeholder="0.00"
        keyboardType="decimal-pad"
      />

      <EditValueModal
        visible={dateModalVisible}
        title="Edit transaction date"
        value={dateEditValue}
        onChangeText={setDateEditValue}
        onSave={handleUpdateDate}
        onClose={() => setDateModalVisible(false)}
        saving={dateSaving}
        placeholder="YYYY-MM-DD"
      />
    </ScreenContainer>
  );
}

// Styles
type Styles = {
  content: ViewStyle;
  contentCompact: ViewStyle;
  headerRow: ViewStyle;
  headerRowCompact: ViewStyle;
  sectionSpacing: ViewStyle;
  warningBox: ViewStyle;
  warningBoxCompact: ViewStyle;
  cascadePanel: ViewStyle;
  cascadeTitle: TextStyle;
  cascadeRow: ViewStyle;
  cascadeLabel: TextStyle;
  cascadeValue: TextStyle;
  sourceBadge: ViewStyle;
  sourceBadgeText: TextStyle;
  confidenceContainer: ViewStyle;
  confidenceBarBg: ViewStyle;
  confidenceBarFill: ViewStyle;
  confidenceText: TextStyle;
  warningIcon: ViewStyle;
  warningText: TextStyle;
  depositButton: ViewStyle;
};

// Stylesheet
const styles = StyleSheet.create<Styles>({
  content: {
    paddingHorizontal: 0,
    paddingBottom: spacing.xxl,
  },
  contentCompact: {
    paddingBottom: spacing.xl,
  },
  headerRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginTop: spacing.md,
    marginBottom: spacing.lg,
  },
  headerRowCompact: {
    marginTop: spacing.sm,
    marginBottom: spacing.md,
  },
  sectionSpacing: {
    height: spacing.xxl,
  },
  cascadePanel: {
    borderRadius: radii.md,
    padding: spacing.md,
    marginTop: spacing.md,
  },
  cascadeTitle: {
    ...typography.sectionTitle,
    marginBottom: spacing.md,
  },
  cascadeRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    paddingVertical: spacing.sm,
  },
  cascadeLabel: {
    ...typography.body,
  },
  cascadeValue: {
    ...typography.bodyStrong,
  },
  sourceBadge: {
    paddingHorizontal: spacing.sm,
    paddingVertical: 2,
    borderRadius: radii.sm,
  },
  sourceBadgeText: {
    fontSize: 11,
    fontWeight: '600',
    textTransform: 'uppercase',
    letterSpacing: 0.5,
  },
  confidenceContainer: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
  },
  confidenceBarBg: {
    width: 80,
    height: 6,
    borderRadius: 3,
    backgroundColor: '#e5e7eb',
    overflow: 'hidden',
  },
  confidenceBarFill: {
    height: '100%',
    borderRadius: 3,
  },
  confidenceText: {
    ...typography.bodyStrong,
    minWidth: 35,
    textAlign: 'right',
  },
  warningBox: {
    marginTop: spacing.xl,
    flexDirection: 'row',
    alignItems: 'center',
    borderRadius: radii.md,
    padding: spacing.lg,
  },
  warningBoxCompact: {
    padding: spacing.md,
  },
  warningIcon: {
    marginRight: spacing.md,
  },
  warningText: {
    ...typography.caption,
    lineHeight: 18,
    flex: 1,
    textAlign: 'left',
  },
  depositButton: {
    borderRadius: radii.md,
    paddingVertical: spacing.md + 2,
    marginTop: spacing.xl,
  },
});
