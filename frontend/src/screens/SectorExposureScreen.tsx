/**
 * SectorExposureScreen
 *
 * Custom bar chart showing sector allocation for a portfolio.
 * Data from GET /agent/sector-exposure/{portfolio_id} (Redis-cached 5min).
 * Each sector shows: horizontal bar, allocation %, value, and ticker list.
 */

import React, { useState, useEffect, useCallback, useRef } from 'react';
import {
  View,
  Text,
  ScrollView,
  RefreshControl,
  ActivityIndicator,
  TouchableOpacity,
  StyleSheet,
} from 'react-native';
import { useRoute, RouteProp } from '@react-navigation/native';
import { Ionicons } from '@expo/vector-icons';

import BackButton from '../components/BackButton';
import ScreenContainer from '../components/ScreenContainer';
import ResponsiveContainer from '../components/ResponsiveContainer';
import PageHeader from '../components/PageHeader';
import SectorBar from '../components/analysis/SectorBar';
import { useTheme } from '../contexts/ThemeContext';
import { PortfolioStackParamList } from '../navigation/AppNavigator';
import { portfolioService, SectorExposureData } from '../services/portfolios';
import { formatCurrencyGBP } from '../utils/formatters';
import { spacing, typography, radii, shadows } from '../styles/theme';

type SectorExposureRouteProp = RouteProp<PortfolioStackParamList, 'SectorExposure'>;

export default function SectorExposureScreen() {
  const route = useRoute<SectorExposureRouteProp>();
  const { theme, isDark } = useTheme();
  const { portfolioId } = route.params;

  const [data, setData] = useState<SectorExposureData | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [expandedSector, setExpandedSector] = useState<string | null>(null);
  const mountedRef = useRef(true);

  const fetchData = useCallback(
    async (isRefresh = false) => {
      try {
        if (isRefresh) setRefreshing(true);
        else setLoading(true);
        setError(null);
        const result = await portfolioService.getSectorExposure(portfolioId);
        if (mountedRef.current) setData(result);
      } catch (err: any) {
        if (mountedRef.current) setError(err?.message || 'Failed to load sector exposure');
      } finally {
        if (mountedRef.current) {
          setLoading(false);
          setRefreshing(false);
        }
      }
    },
    [portfolioId],
  );

  useEffect(() => {
    mountedRef.current = true;
    fetchData();
    return () => {
      mountedRef.current = false;
    };
  }, [fetchData]);

  const handleRefresh = useCallback(() => fetchData(true), [fetchData]);

  if (loading) {
    return (
      <ScreenContainer>
        <View style={styles.centered}>
          <ActivityIndicator size="large" color={theme.primary} />
        </View>
      </ScreenContainer>
    );
  }

  if (error) {
    return (
      <ScreenContainer>
        <View style={styles.centered}>
          <Ionicons name="alert-circle-outline" size={48} color={theme.error} />
          <Text style={[styles.errorText, { color: theme.error }]}>{error}</Text>
          <TouchableOpacity
            style={[styles.retryButton, { backgroundColor: theme.primary }]}
            onPress={() => fetchData()}
          >
            <Text style={styles.retryButtonText}>Retry</Text>
          </TouchableOpacity>
        </View>
      </ScreenContainer>
    );
  }

  if (!data || data.sectors.length === 0) {
    return (
      <ScreenContainer>
        <View style={styles.centered}>
          <Ionicons name="bar-chart-outline" size={48} color={theme.textSecondary} />
          <Text style={[styles.emptyText, { color: theme.textSecondary }]}>
            No sector data available
          </Text>
        </View>
      </ScreenContainer>
    );
  }

  const maxPct = Math.max(...data.sectors.map((s) => s.allocation_pct));

  return (
    <ScreenContainer>
      <ResponsiveContainer>
        <ScrollView
          showsVerticalScrollIndicator={false}
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

          <PageHeader subtitle={`${data.sectors.length} sectors`}>Sector Exposure</PageHeader>

          {/* Total value card */}
          <View style={[styles.totalCard, { backgroundColor: theme.surface, ...shadows.level2 }]}>
            <Text style={[styles.totalLabel, { color: theme.textSecondary }]}>
              Total Portfolio Value
            </Text>
            <Text style={[styles.totalValue, { color: theme.text }]}>
              {formatCurrencyGBP(data.total_value_gbp)}
            </Text>
          </View>

          {/* Sector bars */}
          <View style={[styles.barsCard, { backgroundColor: theme.surface, ...shadows.level2 }]}>
            {data.sectors.map((sector, i) => {
              const isExpanded = expandedSector === sector.sector;
              return (
                <View key={sector.sector}>
                  <TouchableOpacity
                    activeOpacity={0.7}
                    onPress={() => setExpandedSector(isExpanded ? null : sector.sector)}
                  >
                    <SectorBar
                      sector={sector.sector}
                      allocationPct={sector.allocation_pct}
                      valueGbp={sector.value_gbp}
                      maxPct={maxPct}
                      index={i}
                    />
                  </TouchableOpacity>

                  {/* Expanded ticker list */}
                  {isExpanded && (
                    <View
                      style={[
                        styles.tickerList,
                        { backgroundColor: isDark ? '#1a1a2e' : '#f8f9fa' },
                      ]}
                    >
                      <Text style={[styles.tickerListTitle, { color: theme.textSecondary }]}>
                        Holdings
                      </Text>
                      <View style={styles.tickerChips}>
                        {sector.tickers.map((ticker) => (
                          <View
                            key={ticker}
                            style={[styles.tickerChip, { backgroundColor: theme.border }]}
                          >
                            <Text style={[styles.tickerChipText, { color: theme.text }]}>
                              {ticker}
                            </Text>
                          </View>
                        ))}
                      </View>
                    </View>
                  )}
                </View>
              );
            })}
          </View>

          {/* Legend hint */}
          <Text style={[styles.legendHint, { color: theme.textSecondary }]}>
            Tap a sector to see its holdings
          </Text>
        </ScrollView>
      </ResponsiveContainer>
    </ScreenContainer>
  );
}

const styles = StyleSheet.create({
  centered: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
    padding: spacing.xl,
  },
  errorText: {
    fontSize: 16,
    textAlign: 'center',
    marginTop: spacing.md,
    marginBottom: spacing.md,
  },
  retryButton: {
    paddingHorizontal: 24,
    paddingVertical: 10,
    borderRadius: radii.md,
  },
  retryButtonText: {
    color: '#fff',
    fontSize: 16,
    fontWeight: '600',
  },
  emptyText: {
    fontSize: 16,
    textAlign: 'center',
    marginTop: spacing.md,
  },
  scrollContent: {
    paddingBottom: spacing.xxl,
  },
  totalCard: {
    borderRadius: radii.md,
    padding: spacing.lg,
    marginBottom: spacing.md,
    alignItems: 'center',
  },
  totalLabel: {
    ...typography.caption,
    marginBottom: spacing.xs,
  },
  totalValue: {
    ...typography.metric,
    fontWeight: '700',
  },
  barsCard: {
    borderRadius: radii.md,
    padding: spacing.lg,
    marginBottom: spacing.sm,
  },
  tickerList: {
    borderRadius: radii.sm,
    padding: spacing.md,
    marginTop: -8,
    marginBottom: 16,
  },
  tickerListTitle: {
    ...typography.caption,
    fontWeight: '600',
    marginBottom: spacing.sm,
  },
  tickerChips: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 6,
  },
  tickerChip: {
    borderRadius: 12,
    paddingHorizontal: 10,
    paddingVertical: 4,
  },
  tickerChipText: {
    fontSize: 12,
    fontWeight: '600',
  },
  legendHint: {
    ...typography.caption,
    textAlign: 'center',
    marginTop: spacing.sm,
  },
});
