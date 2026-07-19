import React, { useState, useCallback } from 'react';
import {
  View,
  Text,
  FlatList,
  TouchableOpacity,
  StyleSheet,
  ActivityIndicator,
  RefreshControl,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { StatusBar } from 'expo-status-bar';
import { useNavigation, useFocusEffect, CompositeNavigationProp } from '@react-navigation/native';
import { StackNavigationProp } from '@react-navigation/stack';
import { Ionicons } from '@expo/vector-icons';

import { brandColors, useTheme } from '../../contexts/ThemeContext';
import type { PortfolioStackParamList } from '../../navigation/AppNavigator';
import { portfolioService, Portfolio, PortfolioPerformance } from '../../services/portfolios';
import { formatCurrencyRounded, formatRelativeDate } from '../../utils/formatters';
import { spacing, radii, typography, shadows } from '../../styles/theme';
import AgentChatScreen from '../AgentChatScreen';

type ScreenNavProp = CompositeNavigationProp<
  StackNavigationProp<PortfolioStackParamList, 'PortfolioList'>,
  StackNavigationProp<PortfolioStackParamList>
>;

interface PortfolioWithPerformance extends Portfolio {
  performance?: PortfolioPerformance;
}

export default function PortfolioListScreen() {
  const navigation = useNavigation<ScreenNavProp>();
  const { theme } = useTheme();
  const [portfolios, setPortfolios] = useState<PortfolioWithPerformance[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [chatVisible, setChatVisible] = useState(false);

  const fetchData = useCallback(async (isRefresh = false) => {
    if (isRefresh) setRefreshing(true);
    else setLoading(true);
    setError(null);
    try {
      const list = await portfolioService.listPortfolios();
      const perfResults = await Promise.allSettled(
        list.map((p) => portfolioService.getPerformance(p.id)),
      );
      const withPerf = list.map((p, i) => ({
        ...p,
        performance: perfResults[i].status === 'fulfilled' ? perfResults[i].value : undefined,
      }));
      setPortfolios(withPerf);
    } catch (e) {
      setError('Failed to load portfolios');
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  useFocusEffect(
    useCallback(() => {
      fetchData();
    }, [fetchData]),
  );

  const handleRefresh = () => fetchData(true);

  const renderPortfolioItem = ({ item }: { item: PortfolioWithPerformance }) => {
    const perf = item.performance;
    const pnl = perf?.total_unrealised_pl;
    const pnlPct = perf?.total_unrealised_pl_pct;
    const totalValue = perf?.total_market_value;
    const pnlColor =
      pnl == null
        ? theme.textSecondary
        : pnl > 0
          ? brandColors.green
          : pnl < 0
            ? brandColors.red
            : theme.textSecondary;

    return (
      <TouchableOpacity
        style={[styles.card, { backgroundColor: theme.surface }]}
        activeOpacity={0.7}
        onPress={() =>
          navigation.navigate('PortfolioDetail', { portfolioId: item.id, portfolioName: item.name })
        }
      >
        <View style={styles.cardHeader}>
          <Text style={[styles.cardName, { color: theme.text }]} numberOfLines={1}>
            {item.name}
          </Text>
          <Text style={[styles.lastUpdated, { color: theme.textSecondary }]}>
            {formatRelativeDate(item.updated_at)}
          </Text>
        </View>
        <View style={styles.cardMetrics}>
          <View>
            <Text style={[styles.metricLabel, { color: theme.textSecondary }]}>Total Value</Text>
            <Text style={[styles.metricValue, { color: theme.text }]}>
              {totalValue != null ? formatCurrencyRounded(totalValue) : '--'}
            </Text>
          </View>
          <View style={styles.pnlSection}>
            <Text style={[styles.metricLabel, { color: theme.textSecondary, textAlign: 'right' }]}>
              P&L
            </Text>
            <Text style={[styles.metricValue, { color: pnlColor }]}>
              {pnl != null ? formatCurrencyRounded(pnl) : '--'}
            </Text>
            {pnlPct != null && (
              <Text style={[styles.pnlPct, { color: pnlColor }]}>
                {pnlPct > 0 ? '+' : ''}
                {pnlPct.toFixed(2)}%
              </Text>
            )}
          </View>
        </View>
      </TouchableOpacity>
    );
  };

  const renderEmptyState = () => (
    <View style={styles.emptyState}>
      <Text style={[styles.emptyTitle, { color: theme.text }]}>No portfolios yet.</Text>
      <Text style={[styles.emptySubtitle, { color: theme.textSecondary }]}>
        Tap + to create one.
      </Text>
    </View>
  );

  if (loading && !refreshing) {
    return (
      <SafeAreaView style={[styles.container, { backgroundColor: theme.background }]}>
        <StatusBar style="auto" />
        <View style={[styles.header, { backgroundColor: theme.background }]}>
          <Text style={[styles.title, { color: theme.text }]}>My Portfolios</Text>
        </View>
        <View style={styles.loadingContainer}>
          <ActivityIndicator size="large" color={theme.primary} />
        </View>
      </SafeAreaView>
    );
  }

  return (
    <SafeAreaView style={[styles.container, { backgroundColor: theme.background }]}>
      <StatusBar style="auto" />
      <View style={[styles.header, { backgroundColor: theme.background }]}>
        <Text style={[styles.title, { color: theme.text }]}>My Portfolios</Text>
        <View style={styles.headerActions}>
          <TouchableOpacity
            style={[styles.chatBtn, { backgroundColor: theme.primary }]}
            onPress={() => setChatVisible(true)}
            hitSlop={{ top: 8, bottom: 8, left: 8, right: 8 }}
          >
            <Ionicons name="chatbubble-ellipses" size={20} color="#fff" />
          </TouchableOpacity>
          <TouchableOpacity
            style={[styles.fab, { backgroundColor: theme.primary }]}
            onPress={() => navigation.navigate('CreatePortfolio')}
            hitSlop={{ top: 8, bottom: 8, left: 8, right: 8 }}
          >
            <Text style={styles.fabText}>+</Text>
          </TouchableOpacity>
        </View>
      </View>

      <AgentChatScreen visible={chatVisible} onClose={() => setChatVisible(false)} />

      <FlatList
        data={portfolios}
        keyExtractor={(item) => String(item.id)}
        renderItem={renderPortfolioItem}
        contentContainerStyle={[
          styles.listContent,
          portfolios.length === 0 && styles.listContentEmpty,
        ]}
        ListEmptyComponent={!error ? renderEmptyState : null}
        ListHeaderComponent={
          error ? (
            <View style={styles.errorBanner}>
              <Text style={[styles.errorText, { color: theme.error }]}>{error}</Text>
            </View>
          ) : null
        }
        refreshControl={
          <RefreshControl
            refreshing={refreshing}
            onRefresh={handleRefresh}
            tintColor={theme.primary}
            colors={[theme.primary]}
          />
        }
      />
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
  },
  header: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    paddingHorizontal: spacing.lg,
    paddingVertical: spacing.md,
  },
  title: {
    ...typography.pageTitle,
  },
  headerActions: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
  },
  chatBtn: {
    width: 40,
    height: 40,
    borderRadius: 20,
    justifyContent: 'center',
    alignItems: 'center',
  },
  fab: {
    width: 40,
    height: 40,
    borderRadius: 20,
    justifyContent: 'center',
    alignItems: 'center',
  },
  fabText: {
    color: brandColors.white,
    fontSize: 24,
    fontWeight: '600',
    lineHeight: 26,
  },
  loadingContainer: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
  },
  listContent: {
    paddingHorizontal: spacing.lg,
    paddingBottom: spacing.xxl,
  },
  listContentEmpty: {
    flex: 1,
    justifyContent: 'center',
  },
  card: {
    borderRadius: radii.lg,
    padding: spacing.lg,
    marginBottom: spacing.md,
    ...shadows.level2,
  },
  cardHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: spacing.md,
  },
  cardName: {
    ...typography.subtitle,
    flex: 1,
    marginRight: spacing.sm,
  },
  lastUpdated: {
    ...typography.caption,
  },
  cardMetrics: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'flex-start',
  },
  metricLabel: {
    ...typography.overline,
    marginBottom: spacing.xs,
  },
  metricValue: {
    ...typography.metricSm,
  },
  pnlSection: {
    alignItems: 'flex-end',
  },
  pnlPct: {
    ...typography.captionStrong,
    marginTop: 2,
  },
  emptyState: {
    alignItems: 'center',
    paddingVertical: spacing.xxl,
  },
  emptyTitle: {
    ...typography.subtitle,
    marginBottom: spacing.sm,
  },
  emptySubtitle: {
    ...typography.body,
  },
  errorBanner: {
    paddingVertical: spacing.lg,
    alignItems: 'center',
  },
  errorText: {
    ...typography.body,
    textAlign: 'center',
  },
});
