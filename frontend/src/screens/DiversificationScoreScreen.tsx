/**
 * DiversificationScoreScreen
 *
 * Score algorithm visualization. Shows a 0-100 overall score badge,
 * factor breakdown with custom progress bars, and recommendations.
 *
 * Data: GET /agent/diversification-score/{portfolio_id}
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
import { useTheme, brandColors } from '../contexts/ThemeContext';
import { PortfolioStackParamList } from '../navigation/AppNavigator';
import {
  portfolioService,
  DiversificationScoreData,
  DiversificationBreakdown,
} from '../services/portfolios';
import { spacing, typography, radii, shadows } from '../styles/theme';

type DiversificationRouteProp = RouteProp<PortfolioStackParamList, 'DiversificationScore'>;

// ── Score badge color ──────────────────────────────────────────────────────────

function scoreColor(score: number): string {
  if (score >= 80) return brandColors.green;
  if (score >= 60) return brandColors.blue;
  if (score >= 40) return '#FF9500';
  return brandColors.red;
}

function scoreLabel(score: number): string {
  if (score >= 80) return 'Well Diversified';
  if (score >= 60) return 'Moderately Diversified';
  if (score >= 40) return 'Needs Improvement';
  return 'Highly Concentrated';
}

// ── Factor bar ─────────────────────────────────────────────────────────────────

function FactorBar({
  label,
  score,
  maxScore,
  color,
}: {
  label: string;
  score: number;
  maxScore: number;
  color: string;
}) {
  const { theme } = useTheme();
  const pct = maxScore > 0 ? (score / maxScore) * 100 : 0;

  return (
    <View style={factorStyles.container}>
      <View style={factorStyles.header}>
        <Text style={[factorStyles.label, { color: theme.text }]}>{label}</Text>
        <Text style={[factorStyles.score, { color }]}>
          {score.toFixed(1)} / {maxScore.toFixed(1)}
        </Text>
      </View>
      <View style={[factorStyles.track, { backgroundColor: theme.border }]}>
        <View style={[factorStyles.bar, { width: `${pct}%` as any, backgroundColor: color }]} />
      </View>
    </View>
  );
}

const factorStyles = StyleSheet.create({
  container: {
    marginBottom: 18,
  },
  header: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: 4,
  },
  label: {
    fontSize: 14,
    fontWeight: '500',
    flex: 1,
    marginRight: 8,
  },
  score: {
    fontSize: 13,
    fontWeight: '700',
  },
  track: {
    height: 12,
    borderRadius: 6,
    overflow: 'hidden',
  },
  bar: {
    height: '100%',
    borderRadius: 6,
    minWidth: 2,
  },
});

// ── Main screen ────────────────────────────────────────────────────────────────

export default function DiversificationScoreScreen() {
  const route = useRoute<DiversificationRouteProp>();
  const { theme } = useTheme();
  const { portfolioId } = route.params;

  const [data, setData] = useState<DiversificationScoreData | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const mountedRef = useRef(true);

  const fetchData = useCallback(
    async (isRefresh = false) => {
      try {
        if (isRefresh) setRefreshing(true);
        else setLoading(true);
        setError(null);
        const result = await portfolioService.getDiversificationScore(portfolioId);
        if (mountedRef.current) setData(result);
      } catch (err: any) {
        if (mountedRef.current) setError(err?.message || 'Failed to load diversification score');
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

  if (!data) {
    return (
      <ScreenContainer>
        <View style={styles.centered}>
          <Ionicons name="analytics-outline" size={48} color={theme.textSecondary} />
          <Text style={[styles.emptyText, { color: theme.textSecondary }]}>
            No diversification data available
          </Text>
        </View>
      </ScreenContainer>
    );
  }

  const b = data.breakdown;
  const color = scoreColor(data.overall_score);

  // Build factor items for the breakdown section
  const factors: {
    label: string;
    score: number;
    maxScore: number;
    key: keyof DiversificationBreakdown;
    info?: string;
  }[] = [
    {
      label: 'Holdings Diversity',
      score: b.holdings_diversity_score,
      maxScore: b.holdings_diversity_weight_pct,
      key: 'holdings_diversity_score',
      info: `${data.total_holdings} holdings`,
    },
    {
      label: 'HHI Concentration',
      score: b.hhi_concentration_score,
      maxScore: b.hhi_concentration_weight_pct,
      key: 'hhi_concentration_score',
      info: `HHI: ${b.hhi_raw_value}`,
    },
    {
      label: 'Top Holding Weight',
      score: b.top_holding_weight_score,
      maxScore: b.top_holding_weight_pct,
      key: 'top_holding_weight_score',
      info: `${b.top_holding_ticker} at ${b.top_holding_exposure_pct}%`,
    },
    {
      label: 'Sector Diversity',
      score: b.sector_diversity_score,
      maxScore: b.sector_diversity_weight_pct,
      key: 'sector_diversity_score',
      info: `Sector HHI: ${b.sector_hhi_value}`,
    },
  ];

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

          <PageHeader subtitle="Portfolio diversification analysis">
            Diversification Score
          </PageHeader>

          {/* Score badge */}
          <View style={[styles.scoreCard, { backgroundColor: theme.surface, ...shadows.level2 }]}>
            <View style={[styles.scoreCircle, { borderColor: color }]}>
              <Text style={[styles.scoreNumber, { color }]}>{data.overall_score.toFixed(0)}</Text>
              <Text style={[styles.scoreUnit, { color: theme.textSecondary }]}>/100</Text>
            </View>
            <Text style={[styles.scoreLabel, { color }]}>{scoreLabel(data.overall_score)}</Text>
            <View style={styles.scoreMeta}>
              <Text style={[styles.metaText, { color: theme.textSecondary }]}>
                {data.total_holdings} holdings | {data.effective_holdings} effective
              </Text>
            </View>
          </View>

          {/* Factor breakdown */}
          <View
            style={[styles.breakdownCard, { backgroundColor: theme.surface, ...shadows.level2 }]}
          >
            <Text style={[styles.sectionTitle, { color: theme.text }]}>Factor Breakdown</Text>
            {factors.map((f) => (
              <View key={f.key}>
                <FactorBar label={f.label} score={f.score} maxScore={f.maxScore} color={color} />
                {f.info && (
                  <Text style={[styles.factorInfo, { color: theme.textSecondary }]}>{f.info}</Text>
                )}
              </View>
            ))}
          </View>

          {/* Recommendations */}
          <View style={[styles.recoCard, { backgroundColor: theme.surface, ...shadows.level2 }]}>
            <Text style={[styles.sectionTitle, { color: theme.text }]}>Recommendations</Text>
            {data.recommendations.map((rec, i) => (
              <View key={i} style={styles.recoRow}>
                <Ionicons name="bulb-outline" size={18} color="#FFD60A" style={styles.recoIcon} />
                <Text style={[styles.recoText, { color: theme.text }]}>{rec}</Text>
              </View>
            ))}
          </View>
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
  scoreCard: {
    borderRadius: radii.md,
    padding: spacing.xl,
    marginBottom: spacing.md,
    alignItems: 'center',
  },
  scoreCircle: {
    width: 120,
    height: 120,
    borderRadius: 60,
    borderWidth: 4,
    justifyContent: 'center',
    alignItems: 'center',
    marginBottom: spacing.md,
  },
  scoreNumber: {
    fontSize: 40,
    fontWeight: '800',
  },
  scoreUnit: {
    fontSize: 14,
    fontWeight: '500',
  },
  scoreLabel: {
    fontSize: 18,
    fontWeight: '700',
    marginBottom: spacing.sm,
  },
  scoreMeta: {
    flexDirection: 'row',
    gap: spacing.sm,
  },
  metaText: {
    ...typography.caption,
  },
  breakdownCard: {
    borderRadius: radii.md,
    padding: spacing.lg,
    marginBottom: spacing.md,
  },
  sectionTitle: {
    ...typography.bodyStrong,
    fontSize: 16,
    marginBottom: spacing.md,
  },
  factorInfo: {
    ...typography.caption,
    marginTop: -12,
    marginBottom: 18,
    paddingLeft: 4,
  },
  recoCard: {
    borderRadius: radii.md,
    padding: spacing.lg,
    marginBottom: spacing.md,
  },
  recoRow: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    marginBottom: spacing.md,
    gap: spacing.sm,
  },
  recoIcon: {
    marginTop: 2,
  },
  recoText: {
    ...typography.body,
    flex: 1,
    lineHeight: 20,
  },
});
