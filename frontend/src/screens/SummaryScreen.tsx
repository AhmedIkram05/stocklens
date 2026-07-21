/**
 * SummaryScreen
 *
 * Analytics view showing portfolio spending analysis with category breakdown
 * and month-over-month change. Falls back to local receipt computation when
 * no portfolio data is available.
 */

import React from 'react';
import { View, Text, StyleSheet } from 'react-native';
import ScreenContainer from '../components/ScreenContainer';
import PageHeader from '../components/PageHeader';
import { brandColors, useTheme } from '../contexts/ThemeContext';
import { radii, spacing, typography } from '../styles/theme';
import { useBreakpoint } from '../hooks/useBreakpoint';
import { useEffect, useState, useCallback, useRef } from 'react';
import { ScrollView, RefreshControl } from 'react-native';
import { subscribe } from '../services/eventBus';
import useReceipts, { ReceiptShape } from '../hooks/useReceipts';
import { ActivityIndicator } from 'react-native';
import { formatCurrencyRounded, formatCurrencyGBP } from '../utils/formatters';
import { useAuth } from '../contexts/AuthContext';
import { useNavigation } from '@react-navigation/native';
import { Ionicons } from '@expo/vector-icons';
import StatCard from '../components/StatCard';
import ResponsiveContainer from '../components/ResponsiveContainer';
import { EmptyStateWithOnboarding } from '../components/EmptyStateWithOnboarding';
import IconValue from '../components/IconValue';
import ExpandableCard from '../components/ExpandableCard';
import {
  SpendingAnalysisData,
  SpendingCategory,
  SpendingMonthOverMonth,
} from '../services/portfolios';
import { categoryService } from '../services/categories';

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
  // ponytail: fixed 12% CAGR — full-history average of 10 hand-picked winners
  // is survivorship-biased (~20%); 12% is a reasonable broad-market baseline.
  const LSTMRATE = 0.12;

  // ── Spending analysis (API data source) ──
  const [spendingAnalysis, setSpendingAnalysis] = useState<SpendingAnalysisData | null>(null);
  const [, setPortfolioLoading] = useState(true);
  const [, setPortfolioError] = useState<string | null>(null);
  const portfolioLoadedRef = useRef(false);

  const { receipts, loading: receiptsLoading, refetch } = useReceipts();
  const [refreshing, setRefreshing] = useState(false);

  const loadSpendingAnalysis = useCallback(async () => {
    try {
      setPortfolioError(null);
      const r = receipts || [];
      if (r.length === 0) {
        setSpendingAnalysis(null);
        setPortfolioLoading(false);
        return;
      }

      // Build category name lookup
      const catList = await categoryService.listCategories();
      const categoryMap = new Map<string, string>();
      catList.forEach((c) => categoryMap.set(c.id, c.name));

      // Group receipts by category — compute total + count per group
      const groups: Record<string, { total: number; count: number }> = {};
      let totalSpent = 0;
      r.forEach((receipt) => {
        const catKey = receipt.categoryId || '__uncategorised__';
        const amt = receipt.amount || 0;
        totalSpent += amt;
        if (!groups[catKey]) groups[catKey] = { total: 0, count: 0 };
        groups[catKey].total += amt;
        groups[catKey].count += 1;
      });

      const spendingCategories: SpendingCategory[] = Object.entries(groups)
        .map(([catKey, data]) => ({
          category:
            catKey === '__uncategorised__' ? 'Uncategorised' : categoryMap.get(catKey) || 'Unknown',
          category_id: catKey === '__uncategorised__' ? null : catKey,
          transaction_count: data.count,
          total_spend_gbp: Math.round(data.total * 100) / 100,
          pct_of_total: totalSpent > 0 ? Math.round((data.total / totalSpent) * 10000) / 100 : 0,
        }))
        .sort((a, b) => b.total_spend_gbp - a.total_spend_gbp);

      // Month-over-month: compare last full month with previous
      const monthBuckets: Record<string, { byCat: Record<string, number> }> = {};
      r.forEach((receipt) => {
        const d = receipt.date ? new Date(receipt.date) : new Date();
        const mk = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`;
        const catKey = receipt.categoryId || '__uncategorised__';
        const amt = receipt.amount || 0;
        if (!monthBuckets[mk]) monthBuckets[mk] = { byCat: {} };
        monthBuckets[mk].byCat[catKey] = (monthBuckets[mk].byCat[catKey] || 0) + amt;
      });

      const sortedMonths = Object.keys(monthBuckets).sort();
      const monthOverMonth: Record<string, SpendingMonthOverMonth> = {};
      if (sortedMonths.length >= 2) {
        const cur = sortedMonths[sortedMonths.length - 1];
        const prev = sortedMonths[sortedMonths.length - 2];
        const allCatKeys = new Set([
          ...Object.keys(monthBuckets[cur].byCat),
          ...Object.keys(monthBuckets[prev].byCat),
        ]);
        allCatKeys.forEach((catKey) => {
          const curAmt = monthBuckets[cur].byCat[catKey] || 0;
          const prevAmt = monthBuckets[prev].byCat[catKey] || 0;
          const change = curAmt - prevAmt;
          const changePct = prevAmt > 0 ? Math.round((change / prevAmt) * 10000) / 100 : 0;
          const catName =
            catKey === '__uncategorised__' ? 'Uncategorised' : categoryMap.get(catKey) || 'Unknown';
          monthOverMonth[catName] = {
            current_month_spend_gbp: Math.round(curAmt * 100) / 100,
            previous_month_spend_gbp: Math.round(prevAmt * 100) / 100,
            change_gbp: Math.round(change * 100) / 100,
            change_pct: changePct,
          };
        });
      }

      setSpendingAnalysis({
        portfolio_name: 'All Receipts',
        period_months: 6,
        total_spent_gbp: Math.round(totalSpent * 100) / 100,
        categories: spendingCategories,
        month_over_month: monthOverMonth,
      });
      portfolioLoadedRef.current = true;
    } catch (err) {
      setPortfolioError('Failed to analyse spending');
    } finally {
      setPortfolioLoading(false);
    }
  }, [receipts]);

  const loadReceiptTotals = useCallback(async () => {
    try {
      const r = receipts || [];
      const total = r.reduce((s, it) => s + (it.amount || 0), 0);
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
  }, [receipts, user?.uid]);

  useEffect(() => {
    loadSpendingAnalysis().catch(() => {});
    const unsubHist = subscribe('historical-updated', () => {
      loadReceiptTotals().catch(() => {});
    });
    return () => {
      try {
        unsubHist();
      } catch (e) {}
    };
  }, [loadSpendingAnalysis]);

  // Separate effect: compute receipt totals when receipts arrive
  useEffect(() => {
    if (!receiptsLoading) {
      loadReceiptTotals().catch(() => {});
    }
  }, [loadReceiptTotals, receiptsLoading]);

  const handleRefresh = useCallback(async () => {
    setRefreshing(true);
    portfolioLoadedRef.current = false;
    await Promise.allSettled([refetch(), loadSpendingAnalysis(), loadReceiptTotals()]);
    setRefreshing(false);
  }, [refetch, loadSpendingAnalysis, loadReceiptTotals]);

  const formatCurrency = (value: number) => formatCurrencyRounded(value);

  const getDynamicInsights = () => {
    const dynamicInsights = [];

    if (totalMoneySpent > 0) {
      dynamicInsights.push({
        icon: 'wallet-outline',
        title: 'Your Spending Could Be Investing',
        description: `You've spent ${formatCurrency(
          totalMoneySpent,
        )} that could be working for you`,
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
    {
      term: 'Time-Weighted Return (TWR)',
      icon: 'trending-up-outline',
      shortDescription:
        'Your investment performance, stripping out the effect of deposits and withdrawals',
    },
    {
      term: 'Annualised TWR',
      icon: 'calendar-outline',
      shortDescription:
        'TWR scaled to a one-year equivalent, so different time periods are comparable',
    },
    {
      term: 'Unrealised P&L',
      icon: 'cash-outline',
      shortDescription: 'Profit or loss on holdings you still own, based on current prices',
    },
    {
      term: 'Day Change',
      icon: 'swap-vertical-outline',
      shortDescription: "How much your portfolio's value moved since the previous close",
    },
    {
      term: 'Free Cash Balance',
      icon: 'wallet-outline',
      shortDescription: 'Uninvested money sitting in the portfolio, ready to invest',
    },
    {
      term: 'Market Value',
      icon: 'pricetag-outline',
      shortDescription: "The current total value of your holdings at today's prices",
    },
    {
      term: 'Cost Basis',
      icon: 'calculator-outline',
      shortDescription: 'The original amount you paid for your holdings, used to compute profit',
    },
  ];

  const insightDetails: Record<string, { bullets: string[]; example: string }> = {
    'Your Spending Could Be Investing': {
      bullets: [
        `Instead of ${receiptsScanned} receipts, you could have ${receiptsScanned} investment contributions`,
        `Your average purchase of ${formatCurrency(
          avgPerReceipt,
        )} could become a recurring investment`,
        'Even small amounts compound significantly over decades',
      ],
      example: `If you invested just half your spending (${formatCurrency(
        totalMoneySpent / 2,
      )}) today at 8% annual return, you'd have ${formatCurrency(
        (totalMoneySpent / 2) * Math.pow(1.08, 30),
      )} in 30 years.`,
    },
    'High Spending Opportunity': {
      bullets: [
        `Redirecting 20% (${formatCurrency(
          totalMoneySpent * 0.2,
        )}) to investments could yield significant returns`,
        'High earners who invest aggressively often retire 10-15 years earlier',
        'Consider automatic transfers to investment accounts before spending',
      ],
      example: `${formatCurrency(
        totalMoneySpent * 0.2,
      )} invested monthly at 8% for 20 years = ${formatCurrency(
        (totalMoneySpent * 0.2 * (Math.pow(1.08, 20) - 1)) / 0.08,
      )}.`,
    },
    'Small Purchases Add Up': {
      bullets: [
        `Your average spend is ${formatCurrency(avgPerReceipt)} over ${receiptsScanned} purchases`,
        'Small frequent expenses are the #1 wealth killer',
        'Cutting just 30% of these could fund a retirement account',
      ],
      example: `Reducing spending by 30% saves ${formatCurrency(
        totalMoneySpent * 0.3,
      )}/year. Over 25 years at 7%, that's ${formatCurrency(
        (totalMoneySpent * 0.3 * (Math.pow(1.07, 25) - 1)) / 0.07,
      )}.`,
    },
    'Consistent Spending Pattern': {
      bullets: [
        'Predictable spending patterns are perfect for investment planning',
        'Set up automatic investments during consistent periods',
        'Awareness is the first step to financial optimization',
      ],
      example: `With consistent spending of ${formatCurrency(
        avgPerReceipt,
      )} per purchase, redirecting 25% monthly (${formatCurrency(
        (avgPerReceipt * 0.25 * receiptsScanned) / 12,
      )}) for 20 years at 7% = ${formatCurrency(
        (((avgPerReceipt * 0.25 * receiptsScanned) / 12) * 12 * (Math.pow(1.07, 20) - 1)) / 0.07,
      )}.`,
    },

    'Time is Your Superpower': {
      bullets: [
        'Starting at 25 vs 35 can mean 2-3x more wealth by retirement',
        'A 25-year-old investing £200/month reaches £500k+ by 65',
        'The same £200/month starting at 35 only reaches £250k',
      ],
      example: `Starting today with ${formatCurrency(
        avgPerReceipt,
      )}/month vs waiting 5 years could mean ${formatCurrency(
        (avgPerReceipt * 12 * (Math.pow(1.08, 25) - Math.pow(1.08, 20))) / 0.08,
      )} more wealth.`,
    },
    'Inflation is Eating Your Cash': {
      bullets: [
        'At 3% inflation, £1,000 today is worth £744 in 10 years',
        'Savings accounts (~1-2%) lose value after inflation',
        'The S&P 500 historically return 7-10%, beating inflation by 4-7%',
      ],
      example: `Your ${formatCurrency(
        totalMoneySpent,
      )} in cash may have the buying power of only ${formatCurrency(
        totalMoneySpent * Math.pow(0.97, 10),
      )} in 10 years. Invested at 8%, it becomes ${formatCurrency(
        totalMoneySpent * Math.pow(1.08, 10),
      )}.`,
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
    'Time-Weighted Return (TWR)': {
      explanation:
        'Time-Weighted Return (TWR) measures how well your investments performed, independent of when and how much money you added or withdrew. It links the return of each sub-period between cash flows, so a large deposit cannot make your return look artificially good or bad.',
      example:
        'You deposit £10,000, markets rise 5% (+£500), then you add £90,000. TWR still shows +5% for that period — the later deposit doesn’t flatter or hurt the result.',
    },
    'Annualised TWR': {
      explanation:
        'Annualised TWR converts a TWR over any window into a yearly rate using (1 + TWR)^(365 / days) − 1. This lets you compare a 3-month return against a 5-year return on equal footing. For a window of exactly one year it equals the raw TWR.',
      example:
        'A +2% return over 6 months annualises to about +4.04% per year. Over exactly 1 year, annualised TWR is identical to TWR.',
    },
    'Unrealised P&L': {
      explanation:
        'Unrealised (paper) profit or loss is the difference between your holdings’ current market value and what you paid (cost basis). It becomes “realised” only when you sell, and it swings daily with prices.',
      example:
        'You bought 100 shares at £10 (cost £1,000). At £12 today they’re worth £1,200, so unrealised P&L is +£200 (+20%).',
    },
    'Day Change': {
      explanation:
        'Day Change is how much your total portfolio value moved from the previous trading close to now, shown in both currency and percent. It reflects price moves on the shares you hold, not new deposits.',
      example:
        'Portfolio worth £50,000 at yesterday’s close, £51,500 now → Day Change +£1,500 (+3.0%).',
    },
    'Free Cash Balance': {
      explanation:
        'Free Cash Balance is uninvested money in the portfolio. It earns no market return but is available to buy more shares. It is excluded from holdings-based return math so it doesn’t distort TWR.',
      example:
        'You deposited £100,000 and invested £60,000. Free cash balance is £40,000, ready to deploy.',
    },
    'Market Value': {
      explanation:
        'Market Value is the current total worth of your holdings, calculated as shares × current price. It updates with live prices and is the figure shown as your portfolio’s total value.',
      example:
        '50 shares of a £20 stock + 10 shares of a £30 stock = £1,000 + £300 = £1,300 market value.',
    },
    'Cost Basis': {
      explanation:
        'Cost Basis is the total amount you originally paid for your holdings (shares × average purchase price), before fees. It is the reference point used to calculate unrealised profit or loss.',
      example:
        'Bought 100 shares at £10 and 100 more at £14 → cost basis £2,400 (average £12/share).',
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
        refreshControl={
          <RefreshControl
            refreshing={refreshing}
            onRefresh={handleRefresh}
            tintColor={theme.primary}
            colors={[theme.primary]}
          />
        }
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
        ) : receiptsScanned === 0 && !spendingAnalysis ? (
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
                    value={formatCurrency(totalMoneySpent * Math.pow(1 + LSTMRATE, 20))}
                    valueStyle={[styles.projectionValue, { color: theme.text }]}
                  />
                }
                label="20-Year Portfolio Projection"
                subtitle={`If your ${formatCurrency(totalMoneySpent)} grew at ${(
                  LSTMRATE * 100
                ).toFixed(1)}% per year`}
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

              {/* Third row: receipt cards */}
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

              {/* Spending analysis (API data) — extra section below receipt cards */}
              {spendingAnalysis && (
                <>
                  <View
                    style={[
                      styles.spendingSection,
                      { marginTop: spacing.xl, marginBottom: spacing.xs },
                    ]}
                  >
                    <Text
                      style={[styles.sectionTitle, { color: theme.text, marginBottom: spacing.md }]}
                    >
                      Spending by Category
                    </Text>
                    {spendingAnalysis.categories.map((cat) => (
                      <View key={cat.category_id || cat.category} style={styles.categoryRow}>
                        <View style={styles.categoryHeader}>
                          <Text
                            style={[styles.categoryLabel, { color: theme.text }]}
                            numberOfLines={1}
                          >
                            {cat.category}
                          </Text>
                          <Text style={[styles.categoryValue, { color: theme.text }]}>
                            {formatCurrencyGBP(cat.total_spend_gbp)}
                          </Text>
                        </View>
                        <View style={[styles.categoryTrack, { backgroundColor: theme.border }]}>
                          <View
                            style={[
                              styles.categoryBar,
                              {
                                width: `${cat.pct_of_total}%` as any,
                                backgroundColor: theme.primary,
                              },
                            ]}
                          />
                        </View>
                        <Text style={[styles.categoryPct, { color: theme.textSecondary }]}>
                          {cat.pct_of_total.toFixed(1)}% · {cat.transaction_count} transaction
                          {cat.transaction_count !== 1 ? 's' : ''}
                        </Text>
                      </View>
                    ))}
                  </View>

                  {Object.keys(spendingAnalysis.month_over_month).length > 0 && (
                    <View style={[styles.momCard, { backgroundColor: theme.surface }]}>
                      <Text style={[styles.momTitle, { color: theme.text }]}>
                        Month-over-Month Change
                      </Text>
                      {Object.entries(spendingAnalysis.month_over_month).map(([catName, mom]) => {
                        const isPositive = mom.change_gbp >= 0;
                        return (
                          <View key={catName} style={styles.momRow}>
                            <Text
                              style={[styles.momLabel, { color: theme.text }]}
                              numberOfLines={1}
                            >
                              {catName}
                            </Text>
                            <Text
                              style={[
                                styles.momValue,
                                { color: isPositive ? brandColors.red : brandColors.green },
                              ]}
                            >
                              {isPositive ? '+' : ''}
                              {formatCurrencyGBP(mom.change_gbp)}
                              {mom.change_pct !== 0
                                ? ` (${mom.change_pct > 0 ? '+' : ''}${mom.change_pct.toFixed(1)}%)`
                                : ''}
                            </Text>
                          </View>
                        );
                      })}
                    </View>
                  )}
                </>
              )}

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
  spendingSection: {
    marginBottom: spacing.md,
  },
  // ── Spending analysis styles ──
  portfolioSpendingCard: {
    borderRadius: radii.md,
    padding: spacing.lg,
    marginBottom: spacing.md,
    alignItems: 'center',
  },
  spendingTitle: {
    ...typography.bodyStrong,
    fontSize: 18,
    marginBottom: spacing.xs,
  },
  spendingTotal: {
    ...typography.metric,
    fontWeight: '700',
    marginBottom: spacing.xs,
  },
  spendingPeriod: {
    ...typography.caption,
  },
  sectionSubtitle: {
    ...typography.bodyStrong,
    fontSize: 15,
    marginBottom: spacing.md,
  },
  categoryRow: {
    marginBottom: 14,
  },
  categoryHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    marginBottom: 4,
  },
  categoryLabel: {
    fontSize: 14,
    fontWeight: '500',
    flex: 1,
    marginRight: 8,
  },
  categoryValue: {
    fontSize: 14,
    fontWeight: '700',
  },
  categoryTrack: {
    height: 8,
    borderRadius: 4,
    overflow: 'hidden',
    marginBottom: 2,
  },
  categoryBar: {
    height: '100%',
    borderRadius: 4,
    minWidth: 2,
  },
  categoryPct: {
    fontSize: 11,
  },
  momCard: {
    borderRadius: radii.md,
    padding: spacing.lg,
    marginBottom: spacing.md,
  },
  momTitle: {
    ...typography.bodyStrong,
    fontSize: 15,
    marginBottom: spacing.md,
  },
  momRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: spacing.sm,
  },
  momLabel: {
    fontSize: 14,
    fontWeight: '500',
    flex: 1,
    marginRight: 8,
  },
  momValue: {
    fontSize: 14,
    fontWeight: '700',
  },
});
