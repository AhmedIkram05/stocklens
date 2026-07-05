import React, { useState, useEffect, useCallback } from 'react';
import {
  View,
  Text,
  TouchableOpacity,
  ScrollView,
  StyleSheet,
  ActivityIndicator,
  RefreshControl,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { useNavigation, useRoute, RouteProp } from '@react-navigation/native';
import { StackNavigationProp } from '@react-navigation/stack';
import { StatusBar } from 'expo-status-bar';
import { useTheme, brandColors } from '../../contexts/ThemeContext';
import { PortfolioStackParamList } from '../../navigation/AppNavigator';
import { portfolioService, BenchmarkComparison } from '../../services/portfolios';

type BenchmarkRouteProp = RouteProp<PortfolioStackParamList, 'Benchmark'>;
type BenchmarkNavProp = StackNavigationProp<PortfolioStackParamList, 'Benchmark'>;

const BENCHMARK_TICKERS = ['SPY', 'QQQ'] as const;

interface InfoItem {
  title: string;
  description: string;
}

const INFO_ITEMS: InfoItem[] = [
  {
    title: 'Alpha',
    description: 'How much better/worse the portfolio performed vs the benchmark.',
  },
  {
    title: 'Tracking Error',
    description: 'How consistently the portfolio follows the benchmark.',
  },
  {
    title: 'Information Ratio',
    description: 'Risk-adjusted excess return (alpha per unit of tracking error).',
  },
];

interface StatCardProps {
  theme: ReturnType<typeof useTheme>['theme'];
  label: string;
  value: string;
  valueColor?: string;
}

function StatCard({ theme, label, value, valueColor }: StatCardProps) {
  return (
    <View style={[styles.card, { backgroundColor: theme.surface }]}>
      <Text style={[styles.cardLabel, { color: theme.textSecondary }]} numberOfLines={2}>
        {label}
      </Text>
      <Text style={[styles.cardValue, { color: valueColor ?? theme.text }]}>{value}</Text>
    </View>
  );
}

export default function BenchmarkScreen() {
  const navigation = useNavigation<BenchmarkNavProp>();
  const route = useRoute<BenchmarkRouteProp>();
  const { theme } = useTheme();
  const { portfolioId, benchmarkTicker: initialTicker } = route.params;

  const [activeBenchmark, setActiveBenchmark] = useState<string>(initialTicker ?? 'SPY');
  const [data, setData] = useState<BenchmarkComparison | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetchBenchmark = useCallback(
    async (ticker: string, isRefresh = false) => {
      if (isRefresh) {
        setRefreshing(true);
      } else {
        setLoading(true);
      }
      setError(null);

      try {
        const result = await portfolioService.getBenchmark(portfolioId, ticker);
        setData(result);
      } catch {
        setError('Unable to load benchmark data.');
      } finally {
        setLoading(false);
        setRefreshing(false);
      }
    },
    [portfolioId],
  );

  useEffect(() => {
    fetchBenchmark(activeBenchmark);
  }, [activeBenchmark, fetchBenchmark]);

  const handleRefresh = useCallback(() => {
    fetchBenchmark(activeBenchmark, true);
  }, [activeBenchmark, fetchBenchmark]);

  const toggleBenchmark = useCallback((ticker: string) => {
    setActiveBenchmark(ticker);
  }, []);

  const formatPct = (value: number | null | undefined): string =>
    value != null ? `${value.toFixed(2)}%` : 'N/A';

  const renderContent = () => {
    if (loading && !data) {
      return (
        <View style={styles.center}>
          <ActivityIndicator size="large" color={theme.primary} />
        </View>
      );
    }

    if ((error || !data) && !loading) {
      return (
        <View style={styles.center}>
          <Text style={[styles.emptyText, { color: theme.textSecondary }]}>
            Add holdings and prices to see benchmark comparison.
          </Text>
        </View>
      );
    }

    if (!data) return null;

    const alpha = data.excess_return_alpha;
    const ir = data.information_ratio;
    const te = data.tracking_error;
    const alphaColor = alpha != null && alpha >= 0 ? brandColors.green : brandColors.red;
    const irColor = ir != null && ir >= 0 ? brandColors.green : brandColors.red;

    return (
      <ScrollView
        style={styles.scroll}
        contentContainerStyle={styles.scrollContent}
        showsVerticalScrollIndicator={false}
        refreshControl={
          <RefreshControl
            refreshing={refreshing}
            onRefresh={handleRefresh}
            tintColor={theme.primary}
          />
        }
      >
        {loading && data && (
          <ActivityIndicator size="small" color={theme.primary} style={styles.switchLoader} />
        )}

        {data && (
          <Text style={[styles.periodRow, { color: theme.textSecondary }]}>
            {data.period_start} → {data.period_end} · {data.daily_returns_count} trading days
          </Text>
        )}

        <View style={styles.pickerRow}>
          {BENCHMARK_TICKERS.map((ticker) => {
            const isActive = activeBenchmark === ticker;
            return (
              <TouchableOpacity
                key={ticker}
                style={[
                  styles.pickerButton,
                  {
                    backgroundColor: isActive ? theme.primary : theme.surface,
                    borderColor: isActive ? theme.primary : theme.border,
                  },
                ]}
                onPress={() => toggleBenchmark(ticker)}
                disabled={loading && !!data}
              >
                <Text
                  style={[styles.pickerButtonText, { color: isActive ? '#ffffff' : theme.text }]}
                >
                  {ticker}
                </Text>
              </TouchableOpacity>
            );
          })}
        </View>

        {data.daily_returns_count === 0 && (
          <Text style={[styles.insufficientData, { color: theme.textSecondary }]}>
            (insufficient data)
          </Text>
        )}

        <View style={styles.cardsRow}>
          <StatCard
            theme={theme}
            label="Excess Return (Alpha)"
            value={formatPct(data.excess_return_alpha)}
            valueColor={alphaColor}
          />
          <StatCard
            theme={theme}
            label="Tracking Error"
            value={formatPct(te != null ? Math.abs(te) : null)}
          />
          <StatCard
            theme={theme}
            label="Information Ratio"
            value={ir != null ? ir.toFixed(2) : 'N/A'}
            valueColor={irColor}
          />
        </View>

        <View
          style={[
            styles.comparisonBox,
            { backgroundColor: theme.surface, borderColor: theme.border },
          ]}
        >
          <View style={styles.comparisonCol}>
            <Text style={[styles.comparisonLabel, { color: theme.textSecondary }]}>
              Portfolio TWR
            </Text>
            <Text style={[styles.comparisonValue, { color: theme.text }]}>
              {formatPct(data.portfolio_return)}
            </Text>
          </View>
          <Text style={[styles.comparisonVs, { color: theme.textSecondary }]}>vs</Text>
          <View style={styles.comparisonCol}>
            <Text style={[styles.comparisonLabel, { color: theme.textSecondary }]}>
              {data.benchmark_ticker} Return
            </Text>
            <Text style={[styles.comparisonValue, { color: theme.text }]}>
              {formatPct(data.benchmark_return)}
            </Text>
          </View>
        </View>

        <View style={styles.infoSection}>
          {INFO_ITEMS.map((item) => (
            <View key={item.title} style={styles.infoRow}>
              <Text style={[styles.infoTitle, { color: theme.text }]}>{item.title}</Text>
              <Text style={[styles.infoDescription, { color: theme.textSecondary }]}>
                {item.description}
              </Text>
            </View>
          ))}
        </View>
      </ScrollView>
    );
  };

  return (
    <SafeAreaView style={[styles.container, { backgroundColor: theme.background }]}>
      <StatusBar style={theme.background === '#000000' ? 'light' : 'dark'} />
      <View style={styles.header}>
        <TouchableOpacity onPress={() => navigation.goBack()}>
          <Text style={[styles.headerButton, { color: theme.primary }]}>Back</Text>
        </TouchableOpacity>
        <Text style={[styles.headerTitle, { color: theme.text }]}>Benchmark Comparison</Text>
        <View style={styles.headerButton} />
      </View>
      {renderContent()}
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
  },
  header: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingHorizontal: 16,
    paddingVertical: 12,
  },
  headerButton: {
    width: 60,
  },
  headerTitle: {
    fontSize: 18,
    fontWeight: '600',
    textAlign: 'center',
  },
  center: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
    paddingHorizontal: 32,
  },
  emptyText: {
    fontSize: 15,
    textAlign: 'center',
    lineHeight: 22,
  },
  scroll: {
    flex: 1,
  },
  scrollContent: {
    paddingHorizontal: 16,
    paddingBottom: 32,
  },
  switchLoader: {
    marginBottom: 8,
  },
  periodRow: {
    fontSize: 12,
    textAlign: 'center',
    marginBottom: 8,
  },
  pickerRow: {
    flexDirection: 'row',
    gap: 12,
    marginBottom: 16,
  },
  pickerButton: {
    flex: 1,
    borderWidth: 1,
    borderRadius: 12,
    paddingVertical: 12,
    alignItems: 'center',
  },
  pickerButtonText: {
    fontSize: 15,
    fontWeight: '700',
  },
  insufficientData: {
    fontSize: 12,
    fontStyle: 'italic',
    textAlign: 'center',
    marginBottom: 12,
  },
  cardsRow: {
    flexDirection: 'row',
    gap: 10,
    marginBottom: 20,
  },
  card: {
    flex: 1,
    borderRadius: 12,
    paddingVertical: 16,
    paddingHorizontal: 6,
    alignItems: 'center',
    shadowColor: '#000',
    shadowOffset: { width: 0, height: 1 },
    shadowOpacity: 0.08,
    shadowRadius: 4,
    elevation: 2,
  },
  cardLabel: {
    fontSize: 10,
    fontWeight: '500',
    textAlign: 'center',
    marginBottom: 8,
  },
  cardValue: {
    fontSize: 16,
    fontWeight: '700',
  },
  comparisonBox: {
    flexDirection: 'row',
    alignItems: 'center',
    borderRadius: 12,
    borderWidth: 1,
    paddingVertical: 20,
    paddingHorizontal: 16,
    marginBottom: 24,
  },
  comparisonCol: {
    flex: 1,
    alignItems: 'center',
  },
  comparisonLabel: {
    fontSize: 12,
    fontWeight: '500',
    marginBottom: 4,
  },
  comparisonValue: {
    fontSize: 18,
    fontWeight: '700',
  },
  comparisonVs: {
    fontSize: 14,
    fontWeight: '600',
    marginHorizontal: 12,
  },
  infoSection: {
    gap: 16,
  },
  infoRow: {
    gap: 4,
  },
  infoTitle: {
    fontSize: 14,
    fontWeight: '600',
  },
  infoDescription: {
    fontSize: 13,
    lineHeight: 19,
  },
});
