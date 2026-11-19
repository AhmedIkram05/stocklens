import React, { useCallback, useState, useEffect, useRef } from 'react';
import {
  View,
  Text,
  ScrollView,
  TouchableOpacity,
  StyleSheet,
  ActivityIndicator,
  RefreshControl,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { useNavigation, useRoute, RouteProp, useFocusEffect } from '@react-navigation/native';
import { StackNavigationProp } from '@react-navigation/stack';
import { StatusBar } from 'expo-status-bar';

import BackButton from '../../components/BackButton';
import { brandColors, useTheme } from '../../contexts/ThemeContext';
import type { PortfolioStackParamList } from '../../navigation/types';
import type { PortfolioPerformance } from '../../services/portfolios';
import {
  graphqlRequest,
  PORTFOLIO_DETAIL_QUERY,
  toPortfolioPerformance,
  applyValuation,
} from '../../graphql/client';
import type { PortfolioDetailQuery } from '../../graphql/generated';
import {
  resetSubscriptionClient,
  subscribePortfolioValuation,
  type PortfolioValuationPayload,
} from '../../graphql/subscriptionClient';
import { formatCurrency } from '../../utils/formatters';

type PortfolioDetailRouteProp = RouteProp<PortfolioStackParamList, 'PortfolioDetail'>;
type PortfolioDetailNavigationProp = StackNavigationProp<
  PortfolioStackParamList,
  'PortfolioDetail'
>;

function positionsMatch(
  positions: Array<{ ticker: string; shares: number }>,
  holdings: Array<{ ticker: string; shares: number }>,
): boolean {
  return (
    positions.length === holdings.length &&
    holdings.every((h) => positions.find((p) => p.ticker === h.ticker)?.shares === h.shares)
  );
}

const formatPercent = (value: number | null | undefined) => {
  if (value == null) return 'N/A';
  const sign = value >= 0 ? '+' : '';
  return `${sign}${value.toFixed(2)}%`;
};

const formatWeight = (value: number) => `${value.toFixed(1)}%`;

const relativeTime = (iso: string) => {
  const diff = Date.now() - new Date(iso).getTime();
  const s = Math.floor(diff / 1000);
  if (s < 60) return `${s}s ago`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  return `${h}h ago`;
};

const COL_WIDTHS = {
  ticker: 70,
  shares: 65,
  avgCost: 85,
  price: 85,
  marketValue: 95,
  pnl: 95,
  pnlPct: 80,
  weight: 60,
};

const tableColumns = [
  { label: 'Ticker', key: 'ticker', width: COL_WIDTHS.ticker, align: 'left' as const },
  { label: 'Shares', key: 'shares', width: COL_WIDTHS.shares, align: 'right' as const },
  { label: 'Avg Cost', key: 'avgCost', width: COL_WIDTHS.avgCost, align: 'right' as const },
  { label: 'Price', key: 'price', width: COL_WIDTHS.price, align: 'right' as const },
  {
    label: 'Mkt Value',
    key: 'marketValue',
    width: COL_WIDTHS.marketValue,
    align: 'right' as const,
  },
  { label: 'P&L $', key: 'pnl', width: COL_WIDTHS.pnl, align: 'right' as const },
  { label: 'P&L %', key: 'pnlPct', width: COL_WIDTHS.pnlPct, align: 'right' as const },
  { label: 'Wt %', key: 'weight', width: COL_WIDTHS.weight, align: 'right' as const },
];

export default function PortfolioDetailScreen() {
  const navigation = useNavigation<PortfolioDetailNavigationProp>();
  const route = useRoute<PortfolioDetailRouteProp>();
  const { theme } = useTheme();
  const { portfolioId, portfolioName } = route.params;

  const [performance, setPerformance] = useState<PortfolioPerformance | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [lastTickAt, setLastTickAt] = useState<string | null>(null);
  const mountedRef = useRef(true);
  // Latest server valuation — a completed fetch can be older than a websocket
  // tick, so it is folded back onto each fresh snapshot (N10).
  const valuationRef = useRef<PortfolioValuationPayload | null>(null);
  // Positions the current snapshot was fetched with — a tick may only overlay a
  // snapshot whose positions are unchanged (a trade must win over a stale tick).
  const positionsRef = useRef<Array<{ ticker: string; shares: number }> | null>(null);
  const [streamAttempt, setStreamAttempt] = useState(0);
  const retryAttemptRef = useRef(0);
  const retryTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const fetchSeqRef = useRef(0);

  const fetchPerformance = useCallback(
    async (isRefresh = false, silent = false) => {
      const seq = ++fetchSeqRef.current;
      try {
        if (!silent) {
          if (isRefresh) {
            setRefreshing(true);
          } else {
            setLoading(true);
          }
        }
        if (!silent) setError(null);
        const data = await graphqlRequest<PortfolioDetailQuery>(PORTFOLIO_DETAIL_QUERY, {
          id: portfolioId,
        });
        const fresh = data.portfolio ? toPortfolioPerformance(data.portfolio.performance) : null;
        if (fresh) {
          positionsRef.current = fresh.holdings.map(({ ticker, shares }) => ({ ticker, shares }));
        }
        if (mountedRef.current && seq === fetchSeqRef.current)
          setPerformance((prev) => {
            if (!fresh) return null;
            if (!prev) return fresh;
            const valuation = valuationRef.current;
            if (!valuation) return fresh;
            // A tick captured before a trade/deposit must not resurrect old
            // positions: only overlay when the position set matches the fetch.
            return positionsMatch(positionsRef.current ?? [], valuation.holdings)
              ? applyValuation(fresh, valuation)
              : fresh;
          });
      } catch (err: any) {
        if (!silent) setError(err?.message || 'Failed to load portfolio performance');
      } finally {
        if (!silent) {
          setLoading(false);
          setRefreshing(false);
        }
      }
    },
    [portfolioId],
  );

  // Live quote stream replaces the blind 30s poll — no setInterval remains.
  useEffect(() => {
    return () => {
      mountedRef.current = false;
    };
  }, []);

  // Route params can change while this instance is reused — drop the previous
  // portfolio's last tick so it cannot be overlaid on the new one.
  useEffect(() => {
    valuationRef.current = null;
    positionsRef.current = null;
    retryAttemptRef.current = 0;
    setLastTickAt(null);
  }, [portfolioId]);

  // One server-computed valuation stream replaces the per-ticker fan-out.
  useEffect(() => {
    const unsubscribe = subscribePortfolioValuation(
      portfolioId,
      (valuation) => {
        if (!mountedRef.current) return;
        if (valuation.dataQuality !== 'complete') return;
        const positions = positionsRef.current;
        if (positions && !positionsMatch(positions, valuation.holdings)) return;
        retryAttemptRef.current = 0;
        valuationRef.current = valuation;
        setLastTickAt(valuation.calculatedAt);
        setPerformance((prev) => (prev ? applyValuation(prev, valuation) : prev));
      },
      () => {
        // Auth expiry/transport error: force a fresh socket so connectionParams
        // re-reads the token, then resubscribe with capped backoff.
        resetSubscriptionClient();
        retryAttemptRef.current += 1;
        const delay = Math.min(5_000 * retryAttemptRef.current, 60_000);
        retryTimerRef.current = setTimeout(() => {
          if (mountedRef.current) setStreamAttempt((n) => n + 1);
        }, delay);
      },
    );

    return () => {
      unsubscribe();
      if (retryTimerRef.current) {
        clearTimeout(retryTimerRef.current);
        retryTimerRef.current = null;
      }
    };
  }, [portfolioId, streamAttempt]);

  useFocusEffect(
    useCallback(() => {
      fetchPerformance();
    }, [fetchPerformance]),
  );

  const handleRefresh = useCallback(() => {
    fetchPerformance(true);
  }, [fetchPerformance]);

  if (loading) {
    return (
      <SafeAreaView style={[styles.container, { backgroundColor: theme.background }]}>
        <StatusBar style="auto" />
        <View style={styles.centered}>
          <ActivityIndicator size="large" color={theme.primary} />
        </View>
      </SafeAreaView>
    );
  }

  if (error || !performance) {
    return (
      <SafeAreaView style={[styles.container, { backgroundColor: theme.background }]}>
        <StatusBar style="auto" />
        <View style={styles.centered}>
          <Text style={[styles.errorText, { color: theme.error }]}>
            {error || 'Portfolio not found'}
          </Text>
          <TouchableOpacity
            style={[styles.retryButton, { backgroundColor: theme.primary }]}
            onPress={() => fetchPerformance()}
          >
            <Text style={styles.retryButtonText}>Retry</Text>
          </TouchableOpacity>
        </View>
      </SafeAreaView>
    );
  }

  const {
    total_market_value,
    total_unrealised_pl,
    total_unrealised_pl_pct,
    day_change,
    day_change_pct,
    twr,
    twr_start_date,
    twr_end_date,
    free_cash_balance,
    data_quality,
    holdings,
  } = performance;

  const isPnlPositive = total_unrealised_pl != null && total_unrealised_pl >= 0;
  const isDayChangePositive = day_change != null && day_change >= 0;
  const isTwrPositive = twr != null && twr >= 0;
  const isDataPartial = data_quality === 'partial';
  const activeHoldings = holdings.filter((h) => h.shares > 0);

  return (
    <SafeAreaView style={[styles.container, { backgroundColor: theme.background }]}>
      <StatusBar style="auto" />
      <ScrollView
        style={styles.scrollView}
        contentContainerStyle={styles.scrollContent}
        refreshControl={
          <RefreshControl
            refreshing={refreshing}
            onRefresh={handleRefresh}
            tintColor={theme.primary}
          />
        }
      >
        <BackButton />

        <Text style={[styles.portfolioName, { color: theme.text }]}>
          {performance.portfolio_name || portfolioName || `Portfolio #${portfolioId}`}
        </Text>

        <Text style={[styles.totalValue, { color: theme.text }]}>
          {total_market_value != null ? formatCurrency(total_market_value) : 'N/A'}
        </Text>

        <View style={styles.metricsRow}>
          <View style={styles.metric}>
            <Text style={[styles.metricLabel, { color: theme.textSecondary }]}>Day Change</Text>
            <Text
              style={[
                styles.metricValue,
                { color: isDayChangePositive ? brandColors.green : brandColors.red },
              ]}
            >
              {day_change != null
                ? `${formatCurrency(day_change)} (${formatPercent(day_change_pct)})`
                : 'N/A'}
            </Text>
          </View>
          <View style={styles.metric}>
            <Text style={[styles.metricLabel, { color: theme.textSecondary }]}>Total P&L</Text>
            <Text
              style={[
                styles.metricValue,
                { color: isPnlPositive ? brandColors.green : brandColors.red },
              ]}
            >
              {total_unrealised_pl != null
                ? `${formatCurrency(total_unrealised_pl)} (${formatPercent(
                    total_unrealised_pl_pct,
                  )})`
                : 'N/A'}
            </Text>
          </View>
        </View>

        <View style={styles.metricsRow}>
          <View style={styles.metric}>
            <Text style={[styles.metricLabel, { color: theme.textSecondary }]}>TWR</Text>
            <Text
              style={[
                styles.metricValue,
                { color: isTwrPositive ? brandColors.green : brandColors.red },
              ]}
            >
              {formatPercent(twr != null ? twr * 100 : twr)}
            </Text>
            <Text style={[styles.metricSub, { color: theme.textSecondary }]}>
              {twr_start_date && twr_end_date ? `${twr_start_date} → ${twr_end_date}` : ''}
            </Text>
          </View>
        </View>

        {isDataPartial && (
          <View style={styles.warningBanner}>
            <Text style={styles.warningText}>
              Some holdings lack price data — values are partial.
            </Text>
          </View>
        )}

        <Text style={[styles.freshnessText, { color: theme.textSecondary }]}>
          Valuation updated {relativeTime(lastTickAt ?? performance.calculated_at)}
        </Text>

        <View style={styles.sectionHeader}>
          <Text style={[styles.sectionTitle, { color: theme.text }]}>
            Holdings ({activeHoldings.length})
          </Text>
        </View>

        {activeHoldings.length > 0 ? (
          <View style={styles.tableSection}>
            <ScrollView horizontal showsHorizontalScrollIndicator>
              <View style={{ paddingRight: 20 }}>
                <View style={[styles.tableHeader, { borderBottomColor: theme.border }]}>
                  {tableColumns.map((col) => (
                    <Text
                      key={col.key}
                      style={[
                        styles.tableHeaderCell,
                        { width: col.width, color: theme.textSecondary, textAlign: col.align },
                      ]}
                    >
                      {col.label}
                    </Text>
                  ))}
                </View>
                {activeHoldings.map((h, i) => {
                  const pl = h.unrealised_pl;
                  const isPositive = pl != null && pl >= 0;
                  return (
                    <View
                      key={h.ticker}
                      style={[
                        styles.tableRow,
                        i % 2 === 1 && { backgroundColor: theme.surface },
                        { borderBottomColor: theme.border },
                      ]}
                    >
                      <Text
                        style={[
                          styles.tableCell,
                          styles.tickerCell,
                          { width: COL_WIDTHS.ticker, color: theme.text },
                        ]}
                      >
                        {h.ticker}
                      </Text>
                      <Text
                        style={[styles.tableCell, { width: COL_WIDTHS.shares, color: theme.text }]}
                      >
                        {h.shares.toLocaleString()}
                      </Text>
                      <Text
                        style={[styles.tableCell, { width: COL_WIDTHS.avgCost, color: theme.text }]}
                      >
                        {formatCurrency(h.average_cost_basis)}
                      </Text>
                      <Text
                        style={[styles.tableCell, { width: COL_WIDTHS.price, color: theme.text }]}
                      >
                        {h.current_price != null ? formatCurrency(h.current_price) : '--'}
                      </Text>
                      <Text
                        style={[
                          styles.tableCell,
                          { width: COL_WIDTHS.marketValue, color: theme.text },
                        ]}
                      >
                        {h.market_value != null ? formatCurrency(h.market_value) : '--'}
                      </Text>
                      <Text
                        style={[
                          styles.tableCell,
                          {
                            width: COL_WIDTHS.pnl,
                            color: isPositive ? brandColors.green : brandColors.red,
                          },
                        ]}
                      >
                        {pl != null ? formatCurrency(pl) : '--'}
                      </Text>
                      <Text
                        style={[
                          styles.tableCell,
                          {
                            width: COL_WIDTHS.pnlPct,
                            color: isPositive ? brandColors.green : brandColors.red,
                          },
                        ]}
                      >
                        {h.unrealised_pl_pct != null ? formatPercent(h.unrealised_pl_pct) : '--'}
                      </Text>
                      <Text
                        style={[styles.tableCell, { width: COL_WIDTHS.weight, color: theme.text }]}
                      >
                        {h.portfolio_weight_pct != null
                          ? formatWeight(h.portfolio_weight_pct)
                          : '--'}
                      </Text>
                    </View>
                  );
                })}
              </View>
            </ScrollView>
          </View>
        ) : (
          <View style={styles.emptyState}>
            <Text style={[styles.emptyText, { color: theme.textSecondary }]}>
              No holdings yet. Tap Buy to get started.
            </Text>
          </View>
        )}

        <View style={styles.cashRow}>
          <Text style={[styles.cashLabel, { color: theme.textSecondary }]}>Free Cash:</Text>
          <Text style={[styles.cashValue, { color: brandColors.blue }]}>
            {formatCurrency(free_cash_balance)}
          </Text>
        </View>

        <View style={styles.actionsRow}>
          <TouchableOpacity
            style={[styles.actionButton, { backgroundColor: brandColors.blue }]}
            onPress={() => navigation.navigate('Deposit', { portfolioId })}
          >
            <Text style={styles.actionButtonText}>Deposit</Text>
          </TouchableOpacity>
          <TouchableOpacity
            style={[styles.actionButton, { backgroundColor: theme.primary }]}
            onPress={() => navigation.navigate('Trade', { portfolioId, mode: 'buy' })}
          >
            <Text style={styles.actionButtonText}>Trade</Text>
          </TouchableOpacity>
          <TouchableOpacity
            style={[styles.actionButton, { backgroundColor: theme.textSecondary, opacity: 0.7 }]}
            onPress={() => navigation.navigate('Benchmark', { portfolioId })}
          >
            <Text style={styles.actionButtonText}>Benchmark</Text>
          </TouchableOpacity>
          <TouchableOpacity
            style={[styles.actionButton, { backgroundColor: '#10b981' }]}
            onPress={() => navigation.navigate('SectorExposure', { portfolioId })}
          >
            <Text style={styles.actionButtonText}>Sector Exposure</Text>
          </TouchableOpacity>
          <TouchableOpacity
            style={[styles.actionButton, { backgroundColor: '#AF52DE' }]}
            onPress={() => navigation.navigate('DiversificationScore', { portfolioId })}
          >
            <Text style={styles.actionButtonText}>Diversification</Text>
          </TouchableOpacity>
        </View>
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
  },
  scrollView: {
    flex: 1,
  },
  scrollContent: {
    padding: 20,
    paddingBottom: 40,
  },
  centered: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
    padding: 20,
  },
  errorText: {
    fontSize: 16,
    textAlign: 'center',
    marginBottom: 16,
  },
  retryButton: {
    paddingHorizontal: 24,
    paddingVertical: 10,
    borderRadius: 8,
  },
  retryButtonText: {
    color: '#fff',
    fontSize: 16,
    fontWeight: '600',
  },
  portfolioName: {
    fontSize: 20,
    fontWeight: '600',
    marginBottom: 4,
  },
  totalValue: {
    fontSize: 32,
    fontWeight: '700',
    marginBottom: 16,
  },
  metricsRow: {
    flexDirection: 'row',
    gap: 24,
    marginBottom: 24,
  },
  metric: {
    flex: 1,
  },
  metricLabel: {
    fontSize: 13,
    fontWeight: '500',
    marginBottom: 2,
  },
  metricValue: {
    fontSize: 16,
    fontWeight: '700',
  },
  metricSub: {
    fontSize: 11,
    fontWeight: '400',
    marginTop: 2,
  },
  warningBanner: {
    backgroundColor: '#FFF3CD',
    borderRadius: 8,
    padding: 10,
    marginBottom: 16,
  },
  warningText: {
    color: '#856404',
    fontSize: 13,
    textAlign: 'center',
  },
  freshnessText: {
    fontSize: 12,
    textAlign: 'center',
    marginBottom: 12,
  },
  sectionHeader: {
    marginBottom: 8,
  },
  sectionTitle: {
    fontSize: 16,
    fontWeight: '600',
  },
  tableSection: {
    marginBottom: 20,
  },
  tableHeader: {
    flexDirection: 'row',
    borderBottomWidth: 1,
    paddingBottom: 8,
    marginBottom: 4,
  },
  tableHeaderCell: {
    fontSize: 12,
    fontWeight: '600',
    textTransform: 'uppercase',
    letterSpacing: 0.5,
  },
  tableRow: {
    flexDirection: 'row',
    paddingVertical: 10,
    borderBottomWidth: StyleSheet.hairlineWidth,
  },
  tableCell: {
    fontSize: 14,
    textAlign: 'right',
  },
  tickerCell: {
    fontWeight: '600',
    textAlign: 'left',
  },
  emptyState: {
    paddingVertical: 48,
    alignItems: 'center',
  },
  emptyText: {
    fontSize: 15,
    textAlign: 'center',
  },
  cashRow: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    marginBottom: 20,
    gap: 6,
  },
  cashLabel: {
    fontSize: 16,
    fontWeight: '500',
  },
  cashValue: {
    fontSize: 18,
    fontWeight: '700',
  },
  actionsRow: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 10,
    justifyContent: 'center',
  },
  actionButton: {
    paddingHorizontal: 18,
    paddingVertical: 10,
    borderRadius: 999,
  },
  actionButtonText: {
    color: '#fff',
    fontSize: 14,
    fontWeight: '700',
  },
});
