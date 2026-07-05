/**
 * SummaryScreen
 *
 * Analytics view showing spending statistics and insights.
 */

import React from 'react';
import { View, Text, StyleSheet } from 'react-native';
import ScreenContainer from '../components/ScreenContainer';
import PageHeader from '../components/PageHeader';
import { brandColors, useTheme } from '../contexts/ThemeContext';
import { radii, spacing, typography } from '../styles/theme';
import { useBreakpoint } from '../hooks/useBreakpoint';
import { useEffect, useState } from 'react';
import { ScrollView } from 'react-native';
import { subscribe } from '../services/eventBus';
import useReceipts, { ReceiptShape } from '../hooks/useReceipts';
import { ActivityIndicator } from 'react-native';
import { formatCurrencyRounded } from '../utils/formatters';
import { useAuth } from '../contexts/AuthContext';
import { useNavigation } from '@react-navigation/native';
import { Ionicons } from '@expo/vector-icons';
import StatCard from '../components/StatCard';
import ResponsiveContainer from '../components/ResponsiveContainer';
import { EmptyStateWithOnboarding } from '../components/EmptyStateWithOnboarding';
import IconValue from '../components/IconValue';
import ExpandableCard from '../components/ExpandableCard';
import { getCombinedProjection } from '../services/projectionService';
import { STOCK_PRESETS } from '../services/stockPresets';

/** Summary/analytics screen. */
export default function SummaryScreen() {
  const { user } = useAuth();
  const { theme, isDark } = useTheme();
  const [totalMoneySpent, setTotalMoneySpent] = useState<number>(0);
  const [receiptsScanned, setReceiptsScanned] = useState<number>(0);
  const [highestImpactReceipt, setHighestImpactReceipt] = useState<ReceiptShape | null>(null);
  const [avgPerReceipt, setAvgPerReceipt] = useState<number>(0);
  const [mostActiveMonth, setMostActiveMonth] = useState<string | null>(null);
  const [expandedInsight, setExpandedInsight] = useState<string | null>(null);
  const [expandedDefinition, setExpandedDefinition] = useState<string | null>(null);
  // LSTM prediction state
  const [lstmRate, setLstmRate] = useState<number>(0.1);
  const [lstmDirection, setLstmDirection] = useState<'UP' | 'FLAT' | 'DOWN'>('UP');

  const { receipts, loading: receiptsLoading } = useReceipts();

  useEffect(() => {
    let mounted = true;
    async function loadTotals() {
      try {
        const r = receipts || [];
        const total = r.reduce((s, it) => s + (it.amount || 0), 0);
        if (!mounted) return;
        setTotalMoneySpent(total);
        setReceiptsScanned(r.length);
        setAvgPerReceipt(r.length > 0 ? total / r.length : 0);

        const highest = r.slice().sort((a, b) => (b.amount || 0) - (a.amount || 0))[0] ?? null;
        setHighestImpactReceipt(highest ?? null);

        if (r.length > 0) {
          const counts: Record<string, number> = {};
          r.forEach((rr) => {
            const d = rr.date ? new Date(rr.date) : new Date();
            const key = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`;
            counts[key] = (counts[key] || 0) + 1;
          });
          const sortedMonths = Object.keys(counts).sort((a, b) => counts[b] - counts[a]);
          if (sortedMonths.length > 0) {
            const top = sortedMonths[0];
            const [y, m] = top.split('-');
            const monthName = new Date(Number(y), Number(m) - 1, 1).toLocaleString('en-GB', {
              month: 'short',
              year: 'numeric',
            });
            setMostActiveMonth(monthName);
          }
        }
      } catch (err) {}
    }

    loadTotals();
    const unsubHist = subscribe('historical-updated', () => {
      loadTotals().catch(() => {});
    });
    return () => {
      mounted = false;
      try {
        unsubHist();
      } catch (e) {}
    };
  }, [user?.uid, receipts]);

  // Fetch LSTM predictions for all stock presets to get average projected rate
  useEffect(() => {
    let mounted = true;
    async function loadPredictions() {
      try {
        const results = await Promise.allSettled(
          STOCK_PRESETS.map(async (stock) => {
            const proj = await getCombinedProjection(stock.ticker);
            return { ticker: stock.ticker, ...proj };
          }),
        );
        if (!mounted) return;
        const successful = results
          .filter(
            (
              r,
            ): r is PromiseFulfilledResult<{
              ticker: string;
              direction: 'UP' | 'FLAT' | 'DOWN';
              rate: number;
              confidence: number;
              model_version: string;
            }> =>
              r.status === 'fulfilled' &&
              r.value !== null &&
              r.value !== undefined &&
              typeof r.value.rate === 'number' &&
              !isNaN(r.value.rate),
          )
          .map((r) => r.value);
        if (successful.length > 0) {
          const avgRate = successful.reduce((s, p) => s + p.rate, 0) / successful.length;
          // Pick the most common direction
          const dirCounts: Record<string, number> = {};
          successful.forEach((p) => {
            dirCounts[p.direction] = (dirCounts[p.direction] || 0) + 1;
          });
          const topDir = Object.entries(dirCounts).sort((a, b) => b[1] - a[1])[0][0] as
            | 'UP'
            | 'FLAT'
            | 'DOWN';
          setLstmRate(avgRate);
          setLstmDirection(topDir);
        }
      } catch {
        // Keep defaults (10% CAGR)
      }
    }
    loadPredictions();
    return () => {
      mounted = false;
    };
  }, []);

  const formatCurrency = (value: number) => formatCurrencyRounded(value);

  const getDynamicInsights = () => {
    const dynamicInsights = [];

    if (totalMoneySpent > 0) {
      dynamicInsights.push({
        icon: 'wallet-outline',
        title: 'Your Spending Could Be Investing',
        description: `You've spent ${formatCurrency(totalMoneySpent)} that could be working for you`,
      });
    }

    // Lower thresholds so insights appear quickly for small test datasets
    if (totalMoneySpent > 1) {
      dynamicInsights.push({
        icon: 'alert-circle-outline',
        title: 'High Spending Opportunity',
        description: `Even 20% invested could transform your future`,
      });
    }

    if (receiptsScanned >= 2 && avgPerReceipt < 50) {
      dynamicInsights.push({
        icon: 'cash-outline',
        title: 'Small Purchases Add Up',
        description: `${receiptsScanned} small purchases total ${formatCurrency(totalMoneySpent)}`,
      });
    }

    if (receiptsScanned >= 2 && receiptsScanned <= 3) {
      dynamicInsights.push({
        icon: 'trending-up',
        title: 'Consistent Spending Pattern',
        description: `${receiptsScanned} transactions show investment potential`,
      });
    }
    dynamicInsights.push({
      icon: 'time-outline',
      title: 'Time is Your Superpower',
      description: 'Every year you wait costs exponentially more',
    });

    dynamicInsights.push({
      icon: 'pulse-outline',
      title: 'Inflation is Eating Your Cash',
      description: 'Cash loses purchasing power—investments can beat inflation',
    });

    return dynamicInsights;
  };

  const insights = getDynamicInsights();

  const definitions = [
    {
      term: 'Compound Interest',
      icon: 'trending-up-outline',
      shortDescription: 'Earnings on your initial investment plus accumulated interest',
    },
    {
      term: 'CAGR',
      icon: 'stats-chart-outline',
      shortDescription: 'Compound Annual Growth Rate - the rate of return over time',
    },
    {
      term: 'Diversification',
      icon: 'grid-outline',
      shortDescription: 'Spreading investments across different assets to reduce risk',
    },
    {
      term: 'Portfolio',
      icon: 'briefcase-outline',
      shortDescription: 'A collection of financial investments like stocks and bonds',
    },
    {
      term: 'Risk Tolerance',
      icon: 'shield-outline',
      shortDescription: 'Your ability and willingness to withstand investment losses',
    },
    {
      term: 'Asset Allocation',
      icon: 'pie-chart-outline',
      shortDescription: 'How you divide investments among stocks, bonds, and cash',
    },
    {
      term: 'ETF',
      icon: 'layers-outline',
      shortDescription: 'Exchange-Traded Fund - a basket of stocks traded like a single stock',
    },
    {
      term: 'Dividend',
      icon: 'cash-outline',
      shortDescription: 'A portion of company profits paid to shareholders',
    },
    {
      term: 'Bull vs Bear Market',
      icon: 'swap-horizontal-outline',
      shortDescription: 'Bull = rising prices (optimism), Bear = falling prices (pessimism)',
    },
    {
      term: 'Index Fund',
      icon: 'list-outline',
      shortDescription: 'A fund tracking a market index like the S&P 500',
    },
  ];

  const insightDetails: Record<string, { bullets: string[]; example: string }> = {
    'Your Spending Could Be Investing': {
      bullets: [
        `Instead of ${receiptsScanned} receipts, you could have ${receiptsScanned} investment contributions`,
        `Your average purchase of ${formatCurrency(avgPerReceipt)} could become a recurring investment`,
        'Even small amounts compound significantly over decades',
      ],
      example: `If you invested just half your spending (${formatCurrency(totalMoneySpent / 2)}) today at 8% annual return, you'd have ${formatCurrency((totalMoneySpent / 2) * Math.pow(1.08, 30))} in 30 years.`,
    },
    'High Spending Opportunity': {
      bullets: [
        `Redirecting 20% (${formatCurrency(totalMoneySpent * 0.2)}) to investments could yield significant returns`,
        'High earners who invest aggressively often retire 10-15 years earlier',
        'Consider automatic transfers to investment accounts before spending',
      ],
      example: `${formatCurrency(totalMoneySpent * 0.2)} invested monthly at 8% for 20 years = ${formatCurrency((totalMoneySpent * 0.2 * (Math.pow(1.08, 20) - 1)) / 0.08)}.`,
    },
    'Small Purchases Add Up': {
      bullets: [
        `Your average spend is ${formatCurrency(avgPerReceipt)} over ${receiptsScanned} purchases`,
        'Small frequent expenses are the #1 wealth killer',
        'Cutting just 30% of these could fund a retirement account',
      ],
      example: `Reducing spending by 30% saves ${formatCurrency(totalMoneySpent * 0.3)}/year. Over 25 years at 7%, that's ${formatCurrency((totalMoneySpent * 0.3 * (Math.pow(1.07, 25) - 1)) / 0.07)}.`,
    },
    'Consistent Spending Pattern': {
      bullets: [
        'Predictable spending patterns are perfect for investment planning',
        'Set up automatic investments during consistent periods',
        'Awareness is the first step to financial optimization',
      ],
      example: `With consistent spending of ${formatCurrency(avgPerReceipt)} per purchase, redirecting 25% monthly (${formatCurrency((avgPerReceipt * 0.25 * receiptsScanned) / 12)}) for 20 years at 7% = ${formatCurrency((((avgPerReceipt * 0.25 * receiptsScanned) / 12) * 12 * (Math.pow(1.07, 20) - 1)) / 0.07)}.`,
    },

    'Time is Your Superpower': {
      bullets: [
        'Starting at 25 vs 35 can mean 2-3x more wealth by retirement',
        'A 25-year-old investing £200/month reaches £500k+ by 65',
        'The same £200/month starting at 35 only reaches £250k',
      ],
      example: `Starting today with ${formatCurrency(avgPerReceipt)}/month vs waiting 5 years could mean ${formatCurrency((avgPerReceipt * 12 * (Math.pow(1.08, 25) - Math.pow(1.08, 20))) / 0.08)} more wealth.`,
    },
    'Inflation is Eating Your Cash': {
      bullets: [
        'At 3% inflation, £1,000 today is worth £744 in 10 years',
        'Savings accounts (~1-2%) lose value after inflation',
        'The S&P 500 historically return 7-10%, beating inflation by 4-7%',
      ],
      example: `Your ${formatCurrency(totalMoneySpent)} in cash may have the buying power of only ${formatCurrency(totalMoneySpent * Math.pow(0.97, 10))} in 10 years. Invested at 8%, it becomes ${formatCurrency(totalMoneySpent * Math.pow(1.08, 10))}.`,
    },
  };

  const definitionDetails: Record<string, { explanation: string; example: string }> = {
    'Compound Interest': {
      explanation:
        'Compound interest is when you earn interest not just on your initial investment, but also on the interest you\'ve already earned. This creates exponential growth over time, often called the "snowball effect".',
      example:
        'If you invest £1,000 at 10% annually: Year 1 = £1,100, Year 2 = £1,210 (not £1,200), Year 10 = £2,594. The extra £94 in year 10 comes from compounding.',
    },
    CAGR: {
      explanation:
        "CAGR (Compound Annual Growth Rate) smooths out year-to-year volatility to show the average rate at which an investment grows annually. It's more accurate than simple averages for long-term returns.",
      example:
        'If an investment goes from £1,000 to £2,000 in 5 years, the CAGR is 14.87%, not 20% (which would be the simple average).',
    },
    Diversification: {
      explanation:
        'Diversification means not putting all your eggs in one basket. By spreading investments across different companies, sectors, and asset types, you reduce the risk that one poor performer will hurt your entire portfolio.',
      example:
        "If you invest £1,000 across 5 sectors and one drops 50%, you only lose £100 total. If all £1,000 was in that one sector, you'd lose £500.",
    },
    Portfolio: {
      explanation:
        'A portfolio is your complete collection of investments. It can include stocks, bonds, ETFs, mutual funds, and other assets. A well-balanced portfolio matches your risk tolerance and financial goals.',
      example:
        'A moderate portfolio might be: 60% stocks (growth), 30% bonds (stability), 10% cash (liquidity).',
    },
    'Risk Tolerance': {
      explanation:
        'Risk tolerance is your psychological and financial ability to handle investment losses without panicking. It depends on your age, income stability, financial goals, and personality. Higher risk tolerance allows for more aggressive (growth-focused) investments.',
      example:
        'Conservative investor: Loses sleep over 5% drops, prefers bonds. Aggressive investor: Comfortable with 20% swings, invests heavily in stocks.',
    },
    'Asset Allocation': {
      explanation:
        "Asset allocation is the strategy of dividing your portfolio among different asset categories (stocks, bonds, cash, real estate, etc.). It's the most important factor affecting portfolio risk and return. Your allocation should match your goals and timeline.",
      example:
        'Young investor (30+ years to retirement): 80% stocks, 15% bonds, 5% cash. Near retiree: 40% stocks, 50% bonds, 10% cash.',
    },
    ETF: {
      explanation:
        "An Exchange-Traded Fund (ETF) holds many stocks or bonds in one package, trading on exchanges like individual stocks. ETFs offer instant diversification, low fees, and flexibility. They're ideal for beginners wanting broad market exposure.",
      example:
        'Vanguard S&P 500 ETF (VUSA) holds all 500 companies in the S&P 500. Buying one share gives you tiny pieces of Apple, Microsoft, Amazon, and 497 others.',
    },
    Dividend: {
      explanation:
        'A dividend is a cash payment companies make to shareholders from profits. Dividend-paying stocks provide regular income plus potential growth. Reinvesting dividends accelerates compounding. Dividend yield = annual dividend ÷ stock price.',
      example:
        'If a £100 stock pays £4/year in dividends, the yield is 4%. Owning 100 shares = £400/year passive income. Reinvested over 20 years, this dramatically boosts returns.',
    },
    'Bull vs Bear Market': {
      explanation:
        'Bull markets are prolonged periods of rising prices (typically 20%+ gains), driven by optimism and economic growth. Bear markets are extended declines (20%+ drops), triggered by pessimism or recession. Both are normal cycles.',
      example:
        'Bull: 2009-2020 (stocks tripled after financial crisis). Bear: 2022 (stocks fell 25% due to inflation fears). Long-term investors buy during bears, hold through bulls.',
    },
    'Index Fund': {
      explanation:
        'An index fund passively tracks a market index (like FTSE 100 or S&P 500) by holding the same stocks in the same proportions. They offer instant diversification, minimal fees, and historically beat 90% of actively managed funds over 15+ years.',
      example:
        "Instead of picking individual stocks, invest £1,000 in a FTSE 100 index fund. You own pieces of the UK's 100 largest companies automatically rebalanced.",
    },
  };

  const {
    contentHorizontalPadding,
    cardsPerRow,
    width: screenWidth,
    isTablet,
    sectionVerticalSpacing,
  } = useBreakpoint();
  const cardsGap = cardsPerRow === 3 ? spacing.xl : spacing.md;
  const cardsGridStyle = React.useMemo(() => ({ marginHorizontal: -(cardsGap / 2) }), [cardsGap]);
  const cardWidth = React.useMemo(() => {
    const containerWidth = Math.max(screenWidth - contentHorizontalPadding * 2, 240);
    const totalGap = cardsGap * (cardsPerRow - 1);
    const rawWidth = (containerWidth - totalGap) / cardsPerRow;
    const desiredMin = isTablet ? 220 : 140;
    const minWidth = Math.min(rawWidth, desiredMin);
    const maxWidth = isTablet ? 280 : 220;
    return Math.max(minWidth, Math.min(maxWidth, rawWidth));
  }, [cardsPerRow, cardsGap, contentHorizontalPadding, isTablet, screenWidth]);
  const cardLayoutStyle = React.useMemo(
    () => ({ width: cardWidth, marginHorizontal: cardsGap / 2 }),
    [cardWidth, cardsGap],
  );
  const navigation = useNavigation();

  const getReceiptSubtitle = (r: any) => {
    if (!r) return 'No receipts yet';
    try {
      const d = r.date ? new Date(r.date) : null;
      if (d)
        return d.toLocaleDateString(undefined, { day: 'numeric', month: 'short', year: 'numeric' });
    } catch (e) {}
    return 'Receipt';
  };

  return (
    <ScreenContainer contentStyle={{ paddingVertical: sectionVerticalSpacing }}>
      <ScrollView
        contentContainerStyle={styles.contentContainer}
        showsVerticalScrollIndicator={false}
      >
        <PageHeader>
          <View>
            <Text style={[styles.title, { color: theme.text }]}>Summary</Text>
          </View>
          <Text style={[styles.subtitle, { color: theme.textSecondary }]}>
            Your investment insights at a glance
          </Text>
        </PageHeader>

        {receiptsLoading ? (
          <ResponsiveContainer maxWidth={screenWidth - contentHorizontalPadding * 2}>
            <View style={{ padding: spacing.xl, alignItems: 'center' }}>
              <ActivityIndicator size="large" color={theme.primary} />
            </View>
          </ResponsiveContainer>
        ) : receiptsScanned === 0 ? (
          <ResponsiveContainer maxWidth={screenWidth - contentHorizontalPadding * 2}>
            <EmptyStateWithOnboarding
              iconName="stats-chart-outline"
              title="No Data Yet"
              subtitle="Start scanning receipts to see your investment insights and projections"
              primaryText="Scan Your First Receipt"
              onPrimaryPress={() => navigation.navigate('Scan' as never)}
            />
          </ResponsiveContainer>
        ) : (
          <>
            <ResponsiveContainer maxWidth={screenWidth - contentHorizontalPadding * 2}>
              {/* Full-width 20-year projection card */}
              <StatCard
                value={
                  <IconValue
                    iconName="trending-up"
                    iconSize={28}
                    iconColor={theme.primary}
                    value={formatCurrency(totalMoneySpent * Math.pow(1 + lstmRate, 20))}
                    valueStyle={[styles.projectionValue, { color: theme.text }]}
                  />
                }
                label="20-Year Portfolio Projection"
                subtitle={`If your ${formatCurrency(totalMoneySpent)} grew at ${(lstmRate * 100).toFixed(1)}% per year (LSTM ${lstmDirection})`}
                variant="white"
                style={{ width: '100%', marginBottom: spacing.md, marginHorizontal: 0 }}
              />

              {/* Two cards from Dashboard */}
              <View style={[styles.cardsGrid, cardsGridStyle, styles.statsRow]}>
                <StatCard
                  value={
                    <IconValue
                      iconName="cash-outline"
                      iconSize={28}
                      iconColor={brandColors.white}
                      value={formatCurrency(totalMoneySpent)}
                      valueStyle={[
                        styles.projectionValue,
                        { color: brandColors.white, fontSize: 28 },
                      ]}
                    />
                  }
                  label="Total Money Spent"
                  subtitle="Across all scanned receipts"
                  variant="green"
                  style={cardLayoutStyle}
                />
                <StatCard
                  value={
                    <IconValue
                      iconName="document-text-outline"
                      iconSize={28}
                      iconColor={brandColors.white}
                      value={receiptsScanned}
                      valueStyle={[
                        styles.projectionValue,
                        { color: brandColors.white, fontSize: 28 },
                      ]}
                    />
                  }
                  label="Receipts Scanned"
                  variant="blue"
                  style={cardLayoutStyle}
                />
              </View>

              <View style={[styles.cardsGrid, cardsGridStyle]}>
                <StatCard
                  value={
                    <IconValue
                      iconName="receipt-outline"
                      iconSize={22}
                      iconColor={brandColors.white}
                      value={
                        highestImpactReceipt?.amount
                          ? formatCurrency(highestImpactReceipt.amount)
                          : '—'
                      }
                      valueStyle={[styles.cardValueText, { color: brandColors.white }]}
                    />
                  }
                  label="Highest value receipt"
                  subtitle={
                    highestImpactReceipt
                      ? getReceiptSubtitle(highestImpactReceipt)
                      : 'No receipts yet'
                  }
                  variant="green"
                  style={cardLayoutStyle}
                />

                <StatCard
                  value={
                    <IconValue
                      iconName="calculator-outline"
                      iconSize={22}
                      iconColor={brandColors.white}
                      value={formatCurrency(avgPerReceipt || 0)}
                      valueStyle={[styles.cardValueText, { color: brandColors.white }]}
                    />
                  }
                  label="Average per receipt"
                  variant="blue"
                  style={cardLayoutStyle}
                />

                <StatCard
                  value={
                    <IconValue
                      iconName="calendar-outline"
                      iconSize={22}
                      iconColor={brandColors.white}
                      value={mostActiveMonth ?? '—'}
                      valueStyle={[styles.cardValueText, { color: brandColors.white }]}
                    />
                  }
                  label="Most active month"
                  variant="green"
                  style={cardLayoutStyle}
                />
              </View>

              <View style={styles.sectionHeader}>
                <Text style={[styles.sectionTitle, { color: theme.text }]}>
                  Investment Insights
                </Text>
              </View>

              <View>
                {insights.map((item) => {
                  const isExpanded = expandedInsight === item.title;
                  const details = insightDetails[item.title];
                  return (
                    <ExpandableCard
                      key={item.title}
                      icon={item.icon as any}
                      iconColor={theme.primary}
                      title={item.title}
                      description={item.description}
                      isExpanded={isExpanded}
                      onToggle={() => setExpandedInsight(isExpanded ? null : item.title)}
                      expandedContent={
                        details ? (
                          <>
                            {details.bullets.map((bullet, index) => (
                              <Text
                                key={index}
                                style={[styles.bulletPoint, { color: theme.textSecondary }]}
                              >
                                • {bullet}
                              </Text>
                            ))}
                            <View
                              style={[
                                styles.exampleBox,
                                { backgroundColor: isDark ? '#1a1a1a' : '#f9f9f9' },
                              ]}
                            >
                              <Text style={[styles.exampleLabel, { color: theme.text }]}>
                                Example
                              </Text>
                              <Text style={[styles.exampleText, { color: theme.textSecondary }]}>
                                {details.example}
                              </Text>
                            </View>
                          </>
                        ) : undefined
                      }
                    />
                  );
                })}
              </View>

              <View style={[styles.warningBox, { backgroundColor: theme.surface }]}>
                <Ionicons
                  name="warning"
                  size={28}
                  color={brandColors.red}
                  style={styles.warningIcon}
                />
                <Text style={[styles.warningText, { color: theme.text }]}>
                  This is not financial advice. If you are considering investing, please consult a
                  qualified financial advisor for professional guidance.
                </Text>
              </View>

              <View style={styles.sectionHeader}>
                <Text style={[styles.sectionTitle, { color: theme.text }]}>Key Definitions</Text>
              </View>

              <View style={styles.definitionsList}>
                {definitions.map((item) => {
                  const isExpanded = expandedDefinition === item.term;
                  const details = definitionDetails[item.term];
                  return (
                    <ExpandableCard
                      key={item.term}
                      icon={item.icon as any}
                      iconColor={theme.secondary}
                      title={item.term}
                      description={item.shortDescription}
                      isExpanded={isExpanded}
                      onToggle={() => setExpandedDefinition(isExpanded ? null : item.term)}
                      expandedContent={
                        details ? (
                          <>
                            <Text style={[styles.definitionExplanation, { color: theme.text }]}>
                              {details.explanation}
                            </Text>
                            <View
                              style={[
                                styles.exampleBox,
                                { backgroundColor: isDark ? '#1a1a1a' : '#f9f9f9' },
                              ]}
                            >
                              <Text style={[styles.exampleLabel, { color: theme.text }]}>
                                Example
                              </Text>
                              <Text style={[styles.exampleText, { color: theme.textSecondary }]}>
                                {details.example}
                              </Text>
                            </View>
                          </>
                        ) : undefined
                      }
                    />
                  );
                })}
              </View>
            </ResponsiveContainer>
          </>
        )}
      </ScrollView>
    </ScreenContainer>
  );
}

const styles = StyleSheet.create({
  contentContainer: {
    paddingTop: 0,
    paddingBottom: spacing.xxl,
  },
  title: {
    ...typography.pageTitle,
  },
  subtitle: {
    marginTop: spacing.sm,
    ...typography.pageSubtitle,
  },
  cardsGrid: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    justifyContent: 'flex-start',
  },
  cardValueText: {
    ...typography.metricSm,
    fontWeight: '700',
    textAlign: 'center',
  },
  sectionHeader: {
    marginTop: spacing.xl,
    marginBottom: spacing.md,
  },
  sectionTitle: {
    ...typography.sectionTitle,
  },
  projectionValue: {
    ...typography.metric,
    textAlign: 'center',
  },
  bulletPoint: {
    ...typography.caption,
    marginBottom: spacing.sm,
    paddingLeft: spacing.sm,
  },
  exampleBox: {
    borderRadius: radii.md,
    padding: spacing.md,
    marginTop: spacing.md,
    marginBottom: spacing.md,
  },
  exampleLabel: {
    ...typography.bodyStrong,
    marginBottom: spacing.xs,
  },
  exampleText: {
    ...typography.caption,
    fontStyle: 'italic',
  },
  definitionsList: {
    marginBottom: spacing.xl,
  },
  definitionExplanation: {
    ...typography.body,
    marginBottom: spacing.sm,
  },
  statsRow: {
    marginBottom: spacing.md,
  },
  warningBox: {
    marginTop: spacing.md,
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
});
