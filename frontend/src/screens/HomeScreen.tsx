/**
 * HomeScreen
 *
 * Dashboard showing spending stats and recent receipts.
 */

import React, { useMemo, useState, useEffect } from 'react';
import { View, Text, StyleSheet, TouchableOpacity, ScrollView } from 'react-native';
import { useNavigation, CompositeNavigationProp } from '@react-navigation/native';
import { BottomTabNavigationProp } from '@react-navigation/bottom-tabs';
import { StackNavigationProp } from '@react-navigation/stack';

import { brandColors, useTheme } from '../contexts/ThemeContext';
import { radii, spacing, typography } from '../styles/theme';
import ScreenContainer from '../components/ScreenContainer';
import ResponsiveContainer from '../components/ResponsiveContainer';
import PageHeader from '../components/PageHeader';
import StatCard from '../components/StatCard';
import ReceiptCard from '../components/ReceiptCard';
import { EmptyStateWithOnboarding } from '../components/EmptyStateWithOnboarding';
import IconValue from '../components/IconValue';
import { useBreakpoint } from '../hooks/useBreakpoint';
import useReceipts from '../hooks/useReceipts';
import { ActivityIndicator } from 'react-native';
import { formatCurrencyRounded } from '../utils/formatters';
import { portfolioService } from '../services/portfolios';

import { useAuth } from '../contexts/AuthContext';
import type { MainTabParamList, RootStackParamList } from '../navigation/AppNavigator';
import ReceiptsSorter, { SortBy, SortDirection } from '../components/ReceiptsSorter';

type HomeNavigationProp = CompositeNavigationProp<
  BottomTabNavigationProp<MainTabParamList, 'Dashboard'>,
  StackNavigationProp<RootStackParamList>
>;

/** Main dashboard screen. */
export default function HomeScreen() {
  const navigation = useNavigation<HomeNavigationProp>();
  const [showAllHistory, setShowAllHistory] = useState(false);
  const [sortBy, setSortBy] = useState<SortBy>('date');
  const [sortDirection, setSortDirection] = useState<SortDirection>('desc');
  const { theme } = useTheme();

  const { receipts: allScans, loading: receiptsLoading } = useReceipts();

  const [portfolioAgg, setPortfolioAgg] = useState<{
    total_market_value: number;
    total_unrealised_pl: number;
  } | null>(null);
  const [portfolioLoading, setPortfolioLoading] = useState(true);

  useEffect(() => {
    let mounted = true;
    (async () => {
      try {
        const portfolios = await portfolioService.listPortfolios();
        if (!mounted || portfolios.length === 0) {
          if (mounted) setPortfolioLoading(false);
          return;
        }
        const results = await Promise.allSettled(
          portfolios.map((p) => portfolioService.getPerformance(p.id)),
        );
        if (!mounted) return;
        let totalMV = 0;
        let totalPL = 0;
        for (const r of results) {
          if (r.status === 'fulfilled') {
            totalMV += r.value.total_market_value ?? 0;
            totalPL += r.value.total_unrealised_pl ?? 0;
          }
        }
        if (totalMV > 0) {
          setPortfolioAgg({ total_market_value: totalMV, total_unrealised_pl: totalPL });
        }
      } catch {
        // Silently fail
      } finally {
        if (mounted) setPortfolioLoading(false);
      }
    })();
    return () => {
      mounted = false;
    };
  }, []);

  const { userProfile } = useAuth();
  const firstName = useMemo(() => {
    return userProfile?.first_name || '';
  }, [userProfile?.first_name]);

  const hasScans = allScans.length > 0;

  const { contentHorizontalPadding, sectionVerticalSpacing, width } = useBreakpoint();

  const formatAmount = (amount: number) => formatCurrencyRounded(amount || 0);

  const totalMoneySpentDerived = useMemo(() => {
    return allScans.reduce((s, r) => s + (r.amount || 0), 0);
  }, [allScans]);

  const sortedReceipts = useMemo(() => {
    const sorted = [...allScans].sort((a, b) => {
      let comparison = 0;
      switch (sortBy) {
        case 'date':
          comparison = new Date(a.date).getTime() - new Date(b.date).getTime();
          break;
        case 'amount':
          comparison = a.amount - b.amount;
          break;
      }
      return sortDirection === 'asc' ? comparison : -comparison;
    });
    return sorted;
  }, [allScans, sortBy, sortDirection]);

  return (
    <ScreenContainer contentStyle={{ paddingVertical: sectionVerticalSpacing }}>
      <ScrollView style={styles.scrollView} showsVerticalScrollIndicator={false}>
        {receiptsLoading ? (
          <View style={{ padding: spacing.xl, alignItems: 'center' }}>
            <ActivityIndicator size="large" color="#888" />
          </View>
        ) : hasScans ? (
          <>
            <ResponsiveContainer maxWidth={width - contentHorizontalPadding * 2}>
              <PageHeader>
                <View style={styles.titleContainer}>
                  <Text style={[styles.titlePrefix, { color: theme.text }]}>{firstName}'s </Text>
                  <Text style={[styles.titleStock, { color: theme.text }]}>Stock</Text>
                  <Text style={[styles.titleLens, { color: theme.primary }]}>Lens</Text>
                </View>
                <Text style={[styles.subtitle, { color: theme.textSecondary }]}>
                  What if you invested instead?
                </Text>
              </PageHeader>

              <View style={styles.statsContainer}>
                <StatCard
                  value={
                    <IconValue
                      iconName="cash-outline"
                      iconSize={28}
                      iconColor={brandColors.white}
                      value={formatAmount(totalMoneySpentDerived)}
                      valueStyle={{ color: brandColors.white, fontSize: 28, fontWeight: '700' }}
                    />
                  }
                  label="Total Money Spent"
                  subtitle="Across all scanned receipts"
                  variant="green"
                />
                <StatCard
                  value={
                    <IconValue
                      iconName="document-text-outline"
                      iconSize={28}
                      iconColor={brandColors.white}
                      value={allScans.length}
                      valueStyle={{ color: brandColors.white, fontSize: 28, fontWeight: '700' }}
                    />
                  }
                  label="Receipts Scanned"
                  variant="blue"
                />
              </View>

              {!portfolioLoading && portfolioAgg && (
                <TouchableOpacity
                  onPress={() => navigation.navigate('MainTabs' as any, { screen: 'Portfolio' })}
                  activeOpacity={0.7}
                  style={styles.portfolioSection}
                >
                  <View style={styles.statsContainer}>
                    <StatCard
                      value={
                        <IconValue
                          iconName="briefcase-outline"
                          iconSize={28}
                          iconColor={brandColors.white}
                          value={formatAmount(portfolioAgg.total_market_value)}
                          valueStyle={{ color: brandColors.white, fontSize: 28, fontWeight: '700' }}
                        />
                      }
                      label="Portfolio Value"
                      subtitle={`${portfolioAgg.total_unrealised_pl >= 0 ? '+' : ''}${formatAmount(portfolioAgg.total_unrealised_pl)} P&L`}
                      variant="green"
                    />
                  </View>
                </TouchableOpacity>
              )}

              <View style={styles.recentScans}>
                <View style={styles.sectionHeader}>
                  <Text style={[styles.sectionTitle, { color: theme.text }]}>Recent Scans</Text>
                </View>

                <ReceiptsSorter
                  sortBy={sortBy}
                  sortDirection={sortDirection}
                  onSortChange={(by, dir) => {
                    setSortBy(by);
                    setSortDirection(dir);
                  }}
                />
                {(() => {
                  const preview = sortedReceipts.slice(0, 3);
                  const list = showAllHistory ? sortedReceipts : preview;
                  const cols = 1;

                  return (
                    <View style={{ flexDirection: 'row', flexWrap: 'wrap' }}>
                      {list.map((scan) => {
                        return (
                          <View
                            key={scan.id}
                            style={
                              { flexBasis: `${100 / cols}%`, paddingHorizontal: spacing.xs } as any
                            }
                          >
                            <ReceiptCard
                              image={scan.image}
                              amount={formatAmount(scan.amount)}
                              label={scan.label}
                              time={scan.time}
                              onPress={() =>
                                navigation.navigate('ReceiptDetails', {
                                  receiptId: scan.id,
                                  totalAmount: scan.amount,
                                  date: scan.date,
                                  image: scan.image,
                                })
                              }
                            />
                          </View>
                        );
                      })}
                    </View>
                  );
                })()}

                {allScans.length >= 4 && (
                  <TouchableOpacity
                    style={styles.viewAllButton}
                    onPress={() => setShowAllHistory(!showAllHistory)}
                  >
                    <Text style={[styles.viewAllText, { color: theme.text }]}>
                      {showAllHistory ? 'Show Less' : 'View all receipts'}
                    </Text>
                  </TouchableOpacity>
                )}
              </View>
            </ResponsiveContainer>
          </>
        ) : (
          <>
            <ResponsiveContainer maxWidth={width - contentHorizontalPadding * 2}>
              <PageHeader>
                <View style={styles.titleContainer}>
                  <Text style={[styles.titlePrefix, { color: theme.text }]}>{firstName}'s </Text>
                  <Text style={[styles.titleStock, { color: theme.text }]}>Stock</Text>
                  <Text style={[styles.titleLens, { color: theme.primary }]}>Lens</Text>
                </View>
                <Text style={[styles.subtitle, { color: theme.textSecondary }]}>
                  What if you invested instead?
                </Text>
              </PageHeader>

              <View style={styles.emptyStateContainer}>
                <EmptyStateWithOnboarding
                  title="No Receipts Yet"
                  subtitle="Scan your first receipt to discover what your purchases could have been worth"
                  primaryText="Scan Your First Receipt"
                  onPrimaryPress={() => navigation.navigate('MainTabs' as any, { screen: 'Scan' })}
                />
              </View>
            </ResponsiveContainer>
          </>
        )}
      </ScrollView>
    </ScreenContainer>
  );
}

// Styles
const styles = StyleSheet.create({
  scrollView: {
    flex: 1,
  },
  titleContainer: {
    flexDirection: 'row',
    alignItems: 'center',
    marginBottom: spacing.sm,
  },
  titlePrefix: {
    ...typography.pageTitle,
  },
  titleStock: {
    ...typography.pageTitle,
  },
  titleLens: {
    ...typography.pageTitle,
  },
  subtitle: {
    ...typography.pageSubtitle,
  },
  statsContainer: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    paddingBottom: spacing.md,
  },
  sectionTitle: {
    ...typography.sectionTitle,
    opacity: 0.85,
    marginBottom: spacing.md,
  },
  recentScans: {
    paddingBottom: spacing.xl,
  },
  viewAllButton: {
    borderRadius: radii.md,
    paddingVertical: spacing.md,
    alignItems: 'center',
    marginTop: spacing.md,
  },
  viewAllText: {
    ...typography.button,
  },
  emptyStateContainer: {
    paddingBottom: spacing.xxl,
    alignItems: 'center',
  },
  sectionHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: spacing.md,
  },
  portfolioSection: {
    paddingBottom: spacing.md,
  },
});
