/**
 * ReceiptDetailsScreen
 *
 * Detailed view for a single receipt with investment projections.
 */

import React, { useMemo, useState, useEffect } from 'react';
import {
  View,
  Text,
  StyleSheet,
  Alert,
  ScrollView,
  Modal,
  TouchableOpacity,
  FlatList,
  ActivityIndicator,
} from 'react-native';
import type { TextStyle, ViewStyle } from 'react-native';
import ScreenContainer from '../components/ScreenContainer';
import PageHeader from '../components/PageHeader';
import IconButton from '../components/IconButton';
import { RouteProp, useNavigation, useRoute } from '@react-navigation/native';
import { Ionicons } from '@expo/vector-icons';
import type { RootStackParamList } from '../navigation/AppNavigator';
import { brandColors } from '../contexts/ThemeContext';
import { radii, spacing, typography } from '../styles/theme';
import { useBreakpoint } from '../hooks/useBreakpoint';
import DangerButton from '../components/DangerButton';
import ResponsiveContainer from '../components/ResponsiveContainer';
import { receiptService } from '../services/receipts';
import { portfolioService, Portfolio } from '../services/portfolios';
import { useTheme } from '../contexts/ThemeContext';
import { formatCurrencyRounded } from '../utils/formatters';

// Route prop for receipt details screen
type ReceiptDetailsRouteProp = RouteProp<RootStackParamList, 'ReceiptDetails'>;

// Preset options for years to project
type YEAR_OPTIONS = 1 | 3 | 5 | 10 | 20;

import { STOCK_PRESETS } from '../services/stockPresets';

import { subscribe, emit } from '../services/eventBus';
import { getHistoricalCAGRFromToday } from '../services/projectionService';
import { formatCurrencyGBP, formatRelativeDate } from '../utils/formatters';
import YearSelector from '../components/YearSelector';
import StockCard from '../components/StockCard';
import ReceiptCard from '../components/ReceiptCard';
import Carousel from '../components/Carousel';

/** Receipt details and projection screen. */
export default function ReceiptDetailsScreen() {
  const navigation = useNavigation<any>();
  const route = useRoute<ReceiptDetailsRouteProp>();
  const { receiptId, totalAmount: initialAmount, date, image } = route.params;

  const [selectedYears, setSelectedYears] = useState<YEAR_OPTIONS>(5);
  const [selectedFutureYears, setSelectedFutureYears] = useState<YEAR_OPTIONS>(5);
  const [amount] = useState<number>(initialAmount ?? 0);

  const totalAmount = amount;
  const { contentHorizontalPadding, sectionVerticalSpacing, isSmallPhone, isTablet, width } =
    useBreakpoint();
  const { theme } = useTheme();

  const investmentOptions = useMemo(() => {
    return STOCK_PRESETS.map((stock) => {
      // placeholder until live data replaces it asynchronously
      const futureValue = totalAmount * Math.pow(1 + stock.returnRate, selectedYears);
      const gain = futureValue - totalAmount;
      const percentReturn = (futureValue / totalAmount - 1) * 100;

      return {
        ...stock,
        futureValue,
        gain,
        percentReturn,
      };
    });
  }, [selectedYears, totalAmount]);

  const futureInvestmentOptions = useMemo(() => {
    return STOCK_PRESETS.map((stock) => {
      const futureValue = totalAmount * Math.pow(1 + stock.returnRate, selectedFutureYears);
      const gain = futureValue - totalAmount;
      const percentReturn = (futureValue / totalAmount - 1) * 100;

      return {
        ...stock,
        futureValue,
        gain,
        percentReturn,
      };
    });
  }, [selectedFutureYears, totalAmount]);

  // historical CAGRs per ticker and years (e.g. { NVDA: {5: 0.18, 3: 0.22} })
  const [historicalRates, setHistoricalRates] = useState<Record<string, Record<number, number>>>(
    {},
  );
  const [, setRatesLoading] = useState(false);
  const [, setRatesError] = useState<string | null>(null);

  // Deposit into portfolio
  const [depositModalVisible, setDepositModalVisible] = useState(false);
  const [portfolioList, setPortfolioList] = useState<Portfolio[]>([]);
  const [portfoliosLoading, setPortfoliosLoading] = useState(false);
  const [depositingPid, setDepositingPid] = useState<string | null>(null);

  // load historical rates whenever selectedYears changes
  useEffect(() => {
    let mounted = true;
    async function loadHistoricalForYears(years: number) {
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
        if (!mounted) return;
        const map: Record<string, Record<number, number>> = { ...historicalRates };
        results.forEach((r: any) => {
          if (!map[r.ticker]) map[r.ticker] = {};
          if (r.total !== null && r.total !== undefined) map[r.ticker][years] = r.total as number;
        });
        if (mounted) setHistoricalRates(map);
      } catch (err: any) {
        if (mounted) setRatesError(err?.message || String(err));
      } finally {
        if (mounted) setRatesLoading(false);
      }
    }

    loadHistoricalForYears(selectedYears);
    const unsub = subscribe('historical-updated', (payload) => {
      // payload may contain symbol/interval; refresh if it's one of our tracked tickers
      const updatedTicker = payload?.symbol as string | undefined;
      if (!updatedTicker || STOCK_PRESETS.some((s) => s.ticker === updatedTicker)) {
        loadHistoricalForYears(selectedYears).catch(() => {});
      }
    });
    return () => {
      mounted = false;
      unsub();
    };
  }, [selectedYears]);

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

  const formattedEditableAmount = formatCurrencyGBP(amount || 0);

  const formattedYearsLabel = `${selectedYears} ${selectedYears === 1 ? 'year' : 'years'}`;
  const formattedFutureYearsLabel = `${selectedFutureYears} ${selectedFutureYears === 1 ? 'year' : 'years'}`;

  const renderStockCard = (
    investmentValue: (typeof investmentOptions)[number],
    isLastItem: boolean,
    years: number = selectedYears,
    mode: 'past' | 'future' = 'past',
  ) => {
    // Past (historical) uses API-derived total return (last/first - 1) for the selected years when available
    // Future uses preset annual returnRate and the formula amount * (1 + return_rate)^years
    let computedFutureValue: number;
    let computedGain: number;
    let computedPercentReturn: number;

    if (mode === 'past') {
      const cagr = historicalRates[investmentValue.ticker]?.[years];
      if (cagr !== undefined && cagr !== null) {
        // historical CAGR -> compute future value over the period (equivalent to last/first)
        computedFutureValue = totalAmount * Math.pow(1 + cagr, years);
        computedGain = computedFutureValue - totalAmount;
        // show cumulative percent over the whole period (not annualized)
        computedPercentReturn = (Math.pow(1 + cagr, years) - 1) * 100;
      } else {
        // fallback to historical calculation at render time (best-effort) or preset if unavailable
        // use projectUsingHistoricalCAGR synchronously is not possible; fallback to preset rate
        const rate = investmentValue.returnRate;
        computedFutureValue = totalAmount * Math.pow(1 + rate, years);
        computedGain = computedFutureValue - totalAmount;
        computedPercentReturn = (computedFutureValue / totalAmount - 1) * 100;
      }
    } else {
      // future mode — use the unified projectionService (but we already precompute historicalRates for past mode)
      const rate = investmentValue.returnRate;
      computedFutureValue = totalAmount * Math.pow(1 + rate, years);
      computedGain = computedFutureValue - totalAmount;
      computedPercentReturn = (computedFutureValue / totalAmount - 1) * 100;
    }

    const futureDisplay = formatCurrencyGBP(computedFutureValue || 0);

    const gainDisplay = formatCurrencyGBP(computedGain || 0);

    const percentDisplay = `${computedPercentReturn.toFixed(1)}%`;

    // color: green for positive or zero, red for negative
    const valueColor = computedPercentReturn >= 0 ? brandColors.green : brandColors.red;

    // determine badge: show Over/Underperformer for the current mode (past/future)
    let badgeTextToShow: string | undefined = undefined;
    if (mode === 'past') {
      if (investmentValue.ticker === bestPastTicker) badgeTextToShow = 'Overperformer';
      else if (investmentValue.ticker === worstPastTicker) badgeTextToShow = 'Underperformer';
    } else {
      if (investmentValue.ticker === bestFutureTicker) badgeTextToShow = 'Overperformer';
      else if (investmentValue.ticker === worstFutureTicker) badgeTextToShow = 'Underperformer';
    }

    const badgeColorToShow =
      badgeTextToShow === 'Overperformer'
        ? brandColors.green
        : badgeTextToShow === 'Underperformer'
          ? brandColors.red
          : undefined;

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
      const list = investmentOptions.map((it) => {
        const cagr = historicalRates[it.ticker]?.[selectedYears];
        const percent =
          cagr !== undefined && cagr !== null
            ? (Math.pow(1 + cagr, selectedYears) - 1) * 100
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

  // Compute best/worst performers for future based on the currently selected future years
  const { bestFutureTicker, worstFutureTicker } = React.useMemo(() => {
    try {
      const list = futureInvestmentOptions.map((it) => ({
        ticker: it.ticker,
        percent: it.percentReturn,
      }));
      if (list.length === 0) return { bestFutureTicker: undefined, worstFutureTicker: undefined };
      let best = list[0];
      let worst = list[0];
      for (const p of list) {
        if (p.percent > best.percent) best = p;
        if (p.percent < worst.percent) worst = p;
      }
      return { bestFutureTicker: best.ticker, worstFutureTicker: worst.ticker };
    } catch (e) {
      return { bestFutureTicker: undefined, worstFutureTicker: undefined };
    }
  }, [futureInvestmentOptions]);

  // Main render
  return (
    <ScreenContainer contentStyle={{ paddingVertical: sectionVerticalSpacing }}>
      <ScrollView
        contentContainerStyle={[styles.content, isSmallPhone && styles.contentCompact]}
        showsVerticalScrollIndicator={false}
      >
        <View style={[styles.headerRow, isSmallPhone && styles.headerRowCompact]}>
          <IconButton
            name="chevron-back"
            onPress={() => navigation.goBack()}
            accessibilityLabel="Go back"
          />
        </View>

        <ResponsiveContainer maxWidth={width - contentHorizontalPadding * 2}>
          <>
            <View style={{ width: '100%' }}>
              <ReceiptCard
                image={image}
                amount={formattedEditableAmount}
                label={formatRelativeDate(date)}
                time={new Date(date).toLocaleString()}
                onPress={() => {}}
              />
            </View>

            <PageHeader>
              <View>
                <Text style={[styles.projectionTitle, { color: theme.text }]}>
                  Your {formattedAmount} could have been...
                </Text>
              </View>
              <Text style={[styles.projectionSubtitle, { color: theme.textSecondary }]}>
                If invested {formattedYearsLabel} ago
              </Text>
            </PageHeader>

            <YearSelector
              options={[1, 3, 5, 10, 20]}
              value={selectedYears}
              onChange={setSelectedYears}
              compact={isSmallPhone}
              style={{ marginBottom: isSmallPhone ? spacing.xl : spacing.xl + spacing.sm }}
            />

            <View style={styles.carouselHeader}>
              <Text style={[styles.carouselTitle, { color: theme.text }]}>Investment Outlook</Text>
              <Text style={[styles.carouselSubtitle, { color: theme.textSecondary }]}>
                Swipe to explore different stocks
              </Text>
            </View>

            <Carousel
              data={investmentOptions}
              keyExtractor={(item: any) => item.ticker}
              snapInterval={snapInterval}
              contentContainerStyle={styles.carousel}
              renderItem={({ item, index }) =>
                renderStockCard(item, index === investmentOptions.length - 1, selectedYears, 'past')
              }
            />

            <View style={[styles.sectionSpacing, { height: sectionVerticalSpacing }]} />

            <PageHeader>
              <View>
                <Text style={[styles.futureTitle, { color: theme.text }]}>
                  Your {formattedAmount} could become...
                </Text>
              </View>
              <Text style={[styles.futureSubtitle, { color: theme.textSecondary }]}>
                If invested today for {formattedFutureYearsLabel}
              </Text>
            </PageHeader>

            <YearSelector
              options={[1, 3, 5, 10, 20]}
              value={selectedFutureYears}
              onChange={setSelectedFutureYears}
              compact={isSmallPhone}
              style={{ marginBottom: isSmallPhone ? spacing.xl : spacing.xl + spacing.sm }}
            />

            <View style={styles.carouselHeader}>
              <Text style={[styles.carouselTitle, { color: theme.text }]}>Potential Growth</Text>
              <Text style={[styles.carouselSubtitle, { color: theme.textSecondary }]}>
                Compare returns if you started now
              </Text>
            </View>

            <Carousel
              data={futureInvestmentOptions}
              keyExtractor={(item: any) => `future-${item.ticker}`}
              snapInterval={snapInterval}
              contentContainerStyle={styles.carousel}
              renderItem={({ item, index }) =>
                renderStockCard(
                  item,
                  index === futureInvestmentOptions.length - 1,
                  selectedFutureYears,
                  'future',
                )
              }
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
            Projections are hypothetical. Past performance does not guarantee future results. All
            projections are simply made using the CAGR formula.
          </Text>
        </View>
      </ScrollView>

      <Modal
        visible={depositModalVisible}
        transparent
        animationType="fade"
        onRequestClose={() => setDepositModalVisible(false)}
      >
        <View style={styles.modalOverlay}>
          <View style={[styles.modalCard, { backgroundColor: theme.surface }]}>
            <Text style={[styles.modalTitle2, { color: theme.text }]}>
              Deposit {formattedAmount} into…
            </Text>

            {portfoliosLoading ? (
              <View style={styles.modalLoading}>
                <ActivityIndicator size="large" color={theme.primary} />
              </View>
            ) : portfolioList.length === 0 ? (
              <View style={styles.modalLoading}>
                <Text style={[{ color: theme.textSecondary }]}>
                  No portfolios yet. Create one first.
                </Text>
              </View>
            ) : (
              <FlatList
                data={portfolioList}
                keyExtractor={(item) => item.id}
                renderItem={({ item }) => {
                  const isProcessing = depositingPid === item.id;
                  return (
                    <TouchableOpacity
                      style={[styles.modalPortfolioItem, { backgroundColor: theme.background }]}
                      onPress={() => handleSelectPortfolio(item.id)}
                      disabled={depositingPid !== null}
                      activeOpacity={0.7}
                    >
                      <Text style={[styles.modalPortfolioName, { color: theme.text }]}>
                        {item.name}
                      </Text>
                      {isProcessing ? (
                        <ActivityIndicator size="small" color={theme.primary} />
                      ) : (
                        <Ionicons name="chevron-forward" size={18} color={theme.textSecondary} />
                      )}
                    </TouchableOpacity>
                  );
                }}
              />
            )}

            <TouchableOpacity
              style={[styles.modalCloseBtn, { backgroundColor: theme.background }]}
              onPress={() => setDepositModalVisible(false)}
            >
              <Text style={[styles.modalCloseText, { color: theme.secondary }]}>Cancel</Text>
            </TouchableOpacity>
          </View>
        </View>
      </Modal>
    </ScreenContainer>
  );
}

// Styles
type Styles = {
  content: ViewStyle;
  contentCompact: ViewStyle;
  headerRow: ViewStyle;
  headerRowCompact: ViewStyle;
  projectionTitle: TextStyle;
  projectionSubtitle: TextStyle;
  carouselHeader: ViewStyle;
  carouselTitle: TextStyle;
  carouselSubtitle: TextStyle;
  carousel: ViewStyle;
  sectionSpacing: ViewStyle;
  futureTitle: TextStyle;
  futureSubtitle: TextStyle;
  stockCardLast: ViewStyle;
  stockCardHeader: ViewStyle;
  stockName: TextStyle;
  stockTicker: TextStyle;
  stockValueContainer: ViewStyle;
  stockValue: TextStyle;
  stockValueCaption: TextStyle;
  divider: ViewStyle;
  stockFooter: ViewStyle;
  stockFooterItem: ViewStyle;
  footerLabel: TextStyle;
  footerValue: TextStyle;
  verticalDivider: ViewStyle;
  warningBox: ViewStyle;
  warningBoxCompact: ViewStyle;
  warningIcon: ViewStyle;
  warningText: TextStyle;
  depositButton: ViewStyle;
  modalOverlay: ViewStyle;
  modalCard: ViewStyle;
  modalTitle2: TextStyle;
  modalPortfolioItem: ViewStyle;
  modalPortfolioName: TextStyle;
  modalLoading: ViewStyle;
  modalCloseBtn: ViewStyle;
  modalCloseText: TextStyle;
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
  projectionTitle: {
    ...typography.sectionTitle,
    marginBottom: spacing.sm,
  },
  projectionSubtitle: {
    ...typography.body,
    opacity: 0.7,
  },
  carouselHeader: {
    marginBottom: spacing.md,
  },
  carouselTitle: {
    ...typography.bodyStrong,
  },
  carouselSubtitle: {
    ...typography.caption,
    marginTop: spacing.xs,
  },
  carousel: {
    paddingBottom: spacing.md,
  },
  sectionSpacing: {
    height: spacing.xxl,
  },
  futureTitle: {
    ...typography.sectionTitle,
    marginBottom: spacing.sm,
  },
  futureSubtitle: {
    ...typography.body,
    opacity: 0.7,
  },
  stockCardLast: {
    marginRight: 0,
  },
  stockCardHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: spacing.md,
  },
  stockName: {
    ...typography.bodyStrong,
  },
  stockTicker: {
    ...typography.captionStrong,
    color: brandColors.blue,
  },
  stockValueContainer: {
    alignItems: 'flex-start',
    marginBottom: spacing.md,
  },
  stockValue: {
    ...typography.sectionTitle,
  },
  stockValueCaption: {
    ...typography.caption,
    marginTop: spacing.xs,
  },
  divider: {
    height: StyleSheet.hairlineWidth,
    marginBottom: spacing.md,
  },
  stockFooter: {
    flexDirection: 'row',
    alignItems: 'stretch',
    justifyContent: 'space-between',
  },
  stockFooterItem: {
    flex: 1,
  },
  footerLabel: {
    ...typography.overline,
    marginBottom: spacing.sm,
  },
  footerValue: {
    ...typography.metricSm,
    color: brandColors.green,
  },
  verticalDivider: {
    width: 1,
    marginHorizontal: spacing.md,
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
  modalOverlay: {
    flex: 1,
    justifyContent: 'center',
    backgroundColor: 'rgba(0,0,0,0.6)',
    paddingHorizontal: spacing.lg,
  },
  modalCard: {
    borderRadius: radii.lg,
    padding: spacing.lg,
    maxHeight: '60%',
  },
  modalTitle2: {
    ...typography.sectionTitle,
    marginBottom: spacing.lg,
    textAlign: 'center',
  },
  modalPortfolioItem: {
    paddingVertical: spacing.md,
    paddingHorizontal: spacing.md,
    borderRadius: radii.md,
    marginBottom: spacing.sm,
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
  },
  modalPortfolioName: {
    ...typography.bodyStrong,
  },
  modalLoading: {
    paddingVertical: spacing.xl,
    alignItems: 'center',
  },
  modalCloseBtn: {
    alignSelf: 'center',
    marginTop: spacing.lg,
    paddingVertical: spacing.sm,
    paddingHorizontal: spacing.xl,
  },
  modalCloseText: {
    ...typography.button,
  },
});
