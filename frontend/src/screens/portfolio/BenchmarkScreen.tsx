import React, { useState, useEffect, useCallback, useMemo, useRef } from 'react';
import { View, ScrollView, RefreshControl, TouchableOpacity, StyleSheet } from 'react-native';
import Svg, { Polyline, Line, Text as SvgText } from 'react-native-svg';
import { useNavigation, useRoute, RouteProp } from '@react-navigation/native';
import { StackNavigationProp } from '@react-navigation/stack';
import { Ionicons } from '@expo/vector-icons';

import ScreenContainer from '../../components/ScreenContainer';
import PageHeader from '../../components/PageHeader';
import StatCard from '../../components/StatCard';
import YearSelector from '../../components/YearSelector';
import ResponsiveContainer from '../../components/ResponsiveContainer';
import AppText from '../../components/AppText';

import { useTheme, brandColors } from '../../contexts/ThemeContext';
import { PortfolioStackParamList } from '../../navigation/AppNavigator';
import { portfolioService, BenchmarkComparison } from '../../services/portfolios';
import { PERIOD_OPTIONS, periodToStartDate, periodLabel } from '../../constants/periods';
import { useBreakpoint } from '../../hooks/useBreakpoint';
import { spacing, typography, radii, shadows } from '../../styles/theme';

type BenchmarkRouteProp = RouteProp<PortfolioStackParamList, 'Benchmark'>;
type BenchmarkNavProp = StackNavigationProp<PortfolioStackParamList, 'Benchmark'>;

const BENCHMARK_TICKERS = ['SPY', 'QQQ'] as const;

// ── SVG Line Chart ───────────────────────────────────────────────────────────

interface ChartPoint {
  date: string;
  value: number;
}

function ReturnChart({
  portfolio,
  benchmark,
  benchmarkTicker,
  height = 200,
  theme,
}: {
  portfolio: ChartPoint[];
  benchmark: ChartPoint[];
  benchmarkTicker: string;
  height?: number;
  theme: ReturnType<typeof useTheme>['theme'];
}) {
  const { width: screenW, contentHorizontalPadding } = useBreakpoint();
  const chartW = screenW - contentHorizontalPadding * 2 - 32; // account for card padding
  const chartH = height;
  const padL = 48;
  const padR = 8;
  const padT = 20;
  const padB = 28;
  const innerW = chartW - padL - padR;
  const innerH = chartH - padT - padB;

  // Merge both series by date into a unified set
  const allDates = useMemo(() => {
    const dateSet = new Set<string>();
    portfolio.forEach((p) => dateSet.add(p.date));
    benchmark.forEach((b) => dateSet.add(b.date));
    return Array.from(dateSet).sort();
  }, [portfolio, benchmark]);

  if (allDates.length < 2 || (portfolio.length < 2 && benchmark.length < 2)) {
    return (
      <View style={[chartStyles.empty, { height: chartH, backgroundColor: theme.surface }]}>
        <AppText style={{ color: theme.textSecondary, ...typography.caption }}>
          Insufficient data for chart
        </AppText>
      </View>
    );
  }

  const dateIndex = new Map(allDates.map((d, i) => [d, i]));
  const n = allDates.length;

  const toPoints = (series: ChartPoint[]): { x: number; y: number }[] => {
    const values = series.map((s) => s.value);
    if (values.length === 0) return [];
    const min = Math.min(0, ...values);
    const max = Math.max(0, ...values);
    const range = max - min || 1;
    return series.map((s) => ({
      x: padL + ((dateIndex.get(s.date) ?? 0) / (n - 1)) * innerW,
      y: padT + (1 - (s.value - min) / range) * innerH,
    }));
  };

  const portfolioPts = toPoints(portfolio);
  const benchmarkPts = toPoints(benchmark);

  const allVals = [...portfolio.map((p) => p.value), ...benchmark.map((b) => b.value)];
  const minVal = Math.min(0, ...allVals);
  const maxVal = Math.max(0, ...allVals);
  const range = maxVal - minVal || 1;

  const yTicks = 5;
  const yTickValues = Array.from({ length: yTicks + 1 }, (_, i) => minVal + (range * i) / yTicks);

  return (
    <Svg width={chartW} height={chartH}>
      {/* Zero line */}
      {(() => {
        const zeroY = padT + (1 - (0 - minVal) / range) * innerH;
        return (
          <Line
            x1={padL}
            y1={zeroY}
            x2={chartW - padR}
            y2={zeroY}
            stroke={theme.textSecondary}
            strokeWidth={0.5}
            strokeDasharray="4,4"
          />
        );
      })()}

      {/* Y-axis labels */}
      {yTickValues.map((v, i) => {
        const y = padT + (1 - (v - minVal) / range) * innerH;
        return (
          <SvgText
            key={i}
            x={padL - 6}
            y={y + 4}
            fontSize={9}
            fill={theme.textSecondary}
            textAnchor="end"
          >
            {`${(v * 100).toFixed(0)}%`}
          </SvgText>
        );
      })}

      {/* Grid lines */}
      {yTickValues.map((v, i) => {
        const y = padT + (1 - (v - minVal) / range) * innerH;
        return (
          <Line
            key={i}
            x1={padL}
            y1={y}
            x2={chartW - padR}
            y2={y}
            stroke={theme.textSecondary}
            strokeWidth={0.3}
            opacity={0.3}
          />
        );
      })}

      {/* Lines */}
      {portfolioPts.length > 1 && (
        <Polyline
          points={portfolioPts.map((p) => `${p.x},${p.y}`).join(' ')}
          fill="none"
          stroke={brandColors.blue}
          strokeWidth={2}
        />
      )}
      {benchmarkPts.length > 1 && (
        <Polyline
          points={benchmarkPts.map((p) => `${p.x},${p.y}`).join(' ')}
          fill="none"
          stroke={theme.textSecondary}
          strokeWidth={2}
        />
      )}

      {/* Legend */}
      <SvgText x={padL + 2} y={chartH - 4} fontSize={10} fill={brandColors.blue}>
        Portfolio
      </SvgText>
      <SvgText x={padL + 72} y={chartH - 4} fontSize={10} fill={theme.textSecondary}>
        {benchmarkTicker}
      </SvgText>
    </Svg>
  );
}

const chartStyles = StyleSheet.create({
  empty: {
    borderRadius: radii.md,
    alignItems: 'center',
    justifyContent: 'center',
  },
});

// ── Main Screen ──────────────────────────────────────────────────────────────

export default function BenchmarkScreen() {
  const navigation = useNavigation<BenchmarkNavProp>();
  const route = useRoute<BenchmarkRouteProp>();
  const { theme } = useTheme();
  const { portfolioId, benchmarkTicker: initialTicker } = route.params;
  const { sectionVerticalSpacing } = useBreakpoint();

  const [activeBenchmark, setActiveBenchmark] = useState<string>(initialTicker ?? 'SPY');
  const [period, setPeriod] = useState<string>('1Y');
  const [data, setData] = useState<BenchmarkComparison | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const mountedRef = useRef(true);
  const pollRef = useRef({ ticker: activeBenchmark, period });

  // Keep pollRef in sync with current params
  pollRef.current = { ticker: activeBenchmark, period };

  const fetchBenchmark = useCallback(
    async (ticker: string, p: string, isRefresh = false, silent = false) => {
      if (!silent) {
        if (isRefresh) setRefreshing(true);
        else setLoading(true);
      }

      try {
        const endDate = new Date();
        const startDate = periodToStartDate(p, endDate);
        const result = await portfolioService.getBenchmark(portfolioId, ticker, startDate);
        if (mountedRef.current) setData(result);
      } catch (err) {
        console.warn('benchmark fetch error:', err);
        // keep stale data on refresh failure
      } finally {
        if (!silent) {
          setLoading(false);
          setRefreshing(false);
        }
      }
    },
    [portfolioId],
  );

  useEffect(() => {
    fetchBenchmark(activeBenchmark, period);
  }, [activeBenchmark, period, fetchBenchmark]);

  // Silent 30s polling for intraday benchmark updates
  useEffect(() => {
    mountedRef.current = true;
    const id = setInterval(() => {
      const { ticker, period: p } = pollRef.current;
      fetchBenchmark(ticker, p, false, true).catch(() => {});
    }, 30000);
    return () => {
      mountedRef.current = false;
      clearInterval(id);
    };
  }, [fetchBenchmark]);

  const handleRefresh = useCallback(() => {
    fetchBenchmark(activeBenchmark, period, true);
  }, [activeBenchmark, period, fetchBenchmark]);

  const alpha = data?.excess_return_alpha;
  const ir = data?.information_ratio;
  const te = data?.tracking_error;

  return (
    <ScreenContainer>
      <ResponsiveContainer>
        <ScrollView
          showsVerticalScrollIndicator={false}
          contentContainerStyle={{ paddingBottom: spacing.xl }}
          refreshControl={
            <RefreshControl
              refreshing={refreshing}
              onRefresh={handleRefresh}
              tintColor={theme.primary}
            />
          }
        >
          {/* Back button */}
          <TouchableOpacity onPress={() => navigation.goBack()} style={styles.backBtn}>
            <Ionicons name="chevron-back" size={24} color={theme.text} />
          </TouchableOpacity>

          <PageHeader subtitle={`vs ${activeBenchmark}`}>Benchmark</PageHeader>

          {/* Period selector */}
          <YearSelector options={[...PERIOD_OPTIONS]} value={period} onChange={setPeriod} />

          {/* Loading overlay */}
          {loading && !data && (
            <View style={styles.loadingBox}>
              <AppText style={{ color: theme.textSecondary }}>Loading...</AppText>
            </View>
          )}

          {data && (
            <>
              {/* Stat cards row */}
              <View style={[styles.statRow, { marginTop: sectionVerticalSpacing }]}>
                <StatCard
                  value={alpha != null ? `${alpha >= 0 ? '+' : ''}${alpha.toFixed(2)}%` : 'N/A'}
                  label="Alpha"
                  subtitle={periodLabel(period)}
                  variant={alpha != null && alpha >= 0 ? 'green' : 'white'}
                />
                <StatCard
                  value={te != null ? `${Math.abs(te).toFixed(2)}%` : 'N/A'}
                  label="Tracking Error"
                  variant="white"
                />
                <StatCard
                  value={ir != null ? ir.toFixed(2) : 'N/A'}
                  label="Info Ratio"
                  variant={ir != null && ir >= 0 ? 'blue' : 'white'}
                />
              </View>

              {/* Return comparison */}
              <View
                style={[styles.returnCard, { backgroundColor: theme.surface, ...shadows.level2 }]}
              >
                <View style={styles.returnCol}>
                  <AppText style={{ color: theme.textSecondary, ...typography.caption }}>
                    Portfolio
                  </AppText>
                  <AppText
                    style={[
                      typography.metricSm,
                      {
                        color:
                          data.portfolio_return != null && data.portfolio_return >= 0
                            ? brandColors.green
                            : brandColors.red,
                      },
                    ]}
                  >
                    {data.portfolio_return != null ? `${data.portfolio_return.toFixed(2)}%` : 'N/A'}
                  </AppText>
                </View>
                <View style={styles.returnDivider} />
                <View style={styles.returnCol}>
                  <AppText style={{ color: theme.textSecondary, ...typography.caption }}>
                    {activeBenchmark}
                  </AppText>
                  <AppText
                    style={[
                      typography.metricSm,
                      {
                        color:
                          data.benchmark_return != null && data.benchmark_return >= 0
                            ? brandColors.green
                            : brandColors.red,
                      },
                    ]}
                  >
                    {data.benchmark_return != null ? `${data.benchmark_return.toFixed(2)}%` : 'N/A'}
                  </AppText>
                </View>
              </View>

              {/* Cumulative return chart */}
              {(data.portfolio_cumulative_returns.length > 1 ||
                data.benchmark_cumulative_returns.length > 1) && (
                <View
                  style={[styles.chartCard, { backgroundColor: theme.surface, ...shadows.level2 }]}
                >
                  <AppText style={[styles.chartTitle, { color: theme.text }]}>
                    Cumulative Return — {periodLabel(period)}
                  </AppText>
                  <ReturnChart
                    portfolio={data.portfolio_cumulative_returns}
                    benchmark={data.benchmark_cumulative_returns}
                    benchmarkTicker={activeBenchmark}
                    theme={theme}
                  />
                </View>
              )}

              {/* Benchmark picker at bottom */}
              <View style={[styles.pickerSection, { marginTop: sectionVerticalSpacing }]}>
                <AppText style={[styles.pickerLabel, { color: theme.textSecondary }]}>
                  Benchmark
                </AppText>
                <View style={styles.pickerRow}>
                  {BENCHMARK_TICKERS.map((ticker) => {
                    const isActive = activeBenchmark === ticker;
                    return (
                      <TouchableOpacity
                        key={ticker}
                        style={[
                          styles.pickerBtn,
                          {
                            backgroundColor: isActive ? theme.primary : theme.surface,
                            borderColor: isActive ? theme.primary : theme.border,
                          },
                        ]}
                        onPress={() => setActiveBenchmark(ticker)}
                        disabled={loading && !!data}
                      >
                        <AppText
                          style={[
                            styles.pickerBtnText,
                            { color: isActive ? '#ffffff' : theme.text },
                          ]}
                        >
                          {ticker}
                        </AppText>
                      </TouchableOpacity>
                    );
                  })}
                </View>
              </View>
            </>
          )}
        </ScrollView>
      </ResponsiveContainer>
    </ScreenContainer>
  );
}

// ── Styles ───────────────────────────────────────────────────────────────────

const styles = StyleSheet.create({
  backBtn: {
    marginBottom: spacing.sm,
  },
  loadingBox: {
    alignItems: 'center',
    paddingVertical: spacing.xl,
  },
  statRow: {
    flexDirection: 'row',
    gap: spacing.sm,
  },
  returnCard: {
    flexDirection: 'row',
    alignItems: 'center',
    borderRadius: radii.md,
    paddingVertical: spacing.lg,
    paddingHorizontal: spacing.md,
    marginTop: spacing.md,
  },
  returnCol: {
    flex: 1,
    alignItems: 'center',
    gap: spacing.xs,
  },
  returnDivider: {
    width: 1,
    height: 32,
    backgroundColor: brandColors.white,
    opacity: 0.2,
  },
  chartCard: {
    borderRadius: radii.md,
    padding: spacing.md,
    marginTop: spacing.md,
  },
  chartTitle: {
    ...typography.body,
    fontWeight: '600',
    marginBottom: spacing.sm,
  },
  pickerSection: {
    gap: spacing.sm,
  },
  pickerLabel: {
    ...typography.caption,
  },
  pickerRow: {
    flexDirection: 'row',
    gap: spacing.md,
  },
  pickerBtn: {
    flex: 1,
    borderWidth: 1,
    borderRadius: radii.sm,
    paddingVertical: spacing.md,
    alignItems: 'center',
  },
  pickerBtnText: {
    ...typography.bodyStrong,
  },
});
