/**
 * ReceiptDetailsScreen
 *
 * Detailed view for a single receipt with investment projections.
 *
 * State lives in four hooks — `useReceiptDetail` (OCR data load/normalise),
 * `useReceiptEdits` (edit form state + submit/validation), `useDepositFlow`
 * (deposit-into-portfolio) and `useReceiptProjections` (projection maths) — and
 * the OCR extraction affordance is the `ReceiptExtractionDetails` component.
 */

import React, { useCallback, useMemo, useState } from 'react';
import {
  View,
  Text,
  StyleSheet,
  Alert,
  ScrollView,
  TouchableOpacity,
  RefreshControl,
} from 'react-native';
import type { TextStyle, ViewStyle } from 'react-native';
import ScreenContainer from '../components/ScreenContainer';
import BackButton from '../components/BackButton';
import { RouteProp, useNavigation, useRoute } from '@react-navigation/native';
import { Ionicons } from '@expo/vector-icons';
import type { RootStackParamList } from '../navigation/types';
import { brandColors, useTheme } from '../contexts/ThemeContext';
import { radii, spacing, typography } from '../styles/theme';
import { useBreakpoint } from '../hooks/useBreakpoint';
import DangerButton from '../components/DangerButton';
import ResponsiveContainer from '../components/ResponsiveContainer';
import { receiptService } from '../services/receipts';
import { emit } from '../services/eventBus';
import { formatCurrencyGBP, formatRelativeDate } from '../utils/formatters';
import StockCard from '../components/StockCard';
import ReceiptCard from '../components/ReceiptCard';
import ProjectionCarouselSection from '../components/ProjectionCarouselSection';
import EditValueModal from '../components/EditValueModal';
import CategoryPickerModal from '../components/CategoryPickerModal';
import DepositModal from '../components/DepositModal';
import ReceiptMetaPanel from '../components/ReceiptMetaPanel';
import ReceiptItemsCard from '../components/ReceiptItemsCard';
import ReceiptExtractionDetails from '../components/ReceiptExtractionDetails';
import type { SourceBadgeKey } from '../components/ReceiptCard';

import useReceiptDetail from '../hooks/useReceiptDetail';
import useReceiptEdits from '../hooks/useReceiptEdits';
import useDepositFlow from '../hooks/useDepositFlow';
import useReceiptProjections from '../hooks/useReceiptProjections';

// Route prop for receipt details screen
type ReceiptDetailsRouteProp = RouteProp<RootStackParamList, 'ReceiptDetails'>;

/** Receipt details and projection screen. */
export default function ReceiptDetailsScreen() {
  const navigation = useNavigation<any>();
  const route = useRoute<ReceiptDetailsRouteProp>();
  const {
    receiptId,
    totalAmount: initialAmount,
    date,
    image,
    confidence,
    processingTimeMs,
    merchantName: initialMerchant,
    lineItems: initialItems,
  } = route.params;
  const source = route.params.source as SourceBadgeKey | undefined;
  const confidencePct = confidence != null ? Math.round(confidence * 100) : null;

  const {
    receipt,
    setReceipt,
    categories,
    categoryName,
    totalAmount,
    merchantName,
    lineItems,
    itemsSubtotal,
    totalMismatch,
    loadReceiptDetail,
    loadCategories,
  } = useReceiptDetail({
    receiptId,
    totalAmount: initialAmount,
    merchantName: initialMerchant,
    lineItems: initialItems,
  });

  const formattedAmount = formatCurrencyGBP(totalAmount || 0);

  const {
    categoryModalVisible,
    setCategoryModalVisible,
    categorySaving,
    merchantModalVisible,
    setMerchantModalVisible,
    merchantEditValue,
    setMerchantEditValue,
    merchantSaving,
    amountModalVisible,
    setAmountModalVisible,
    amountEditValue,
    setAmountEditValue,
    amountSaving,
    dateModalVisible,
    setDateModalVisible,
    dateEditValue,
    setDateEditValue,
    dateSaving,
    handleSelectCategory,
    handleUpdateMerchant,
    handleUpdateAmount,
    handleUpdateDate,
  } = useReceiptEdits({ receiptId, setReceipt });

  const {
    depositModalVisible,
    setDepositModalVisible,
    portfolioList,
    portfoliosLoading,
    depositingPid,
    handleOpenDeposit,
    handleSelectPortfolio,
  } = useDepositFlow({ totalAmount, receiptId, formattedAmount });

  const {
    selectedYears,
    setSelectedYears,
    selectedFutureYears,
    setSelectedFutureYears,
    investmentOptions,
    futureInvestmentOptions,
    formattedYearsLabel,
    formattedFutureYearsLabel,
    loadHistoricalForYears,
    loadPredictions,
    loadFutureRates,
    computeProjectionView,
  } = useReceiptProjections(totalAmount);

  const { contentHorizontalPadding, sectionVerticalSpacing, isSmallPhone, isTablet, width } =
    useBreakpoint();
  const { theme } = useTheme();

  const [refreshing, setRefreshing] = useState(false);

  const handleRefresh = useCallback(async () => {
    setRefreshing(true);
    await Promise.allSettled([
      loadReceiptDetail(),
      loadCategories(),
      loadHistoricalForYears(selectedYears),
      loadPredictions(),
      loadFutureRates(selectedFutureYears),
    ]);
    setRefreshing(false);
  }, [
    loadReceiptDetail,
    loadCategories,
    loadHistoricalForYears,
    loadPredictions,
    loadFutureRates,
    selectedYears,
    selectedFutureYears,
  ]);

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

  const renderStockCard = (
    investmentValue: (typeof investmentOptions)[number],
    isLastItem: boolean,
    years: string,
    mode: 'past' | 'future',
  ) => {
    const view = computeProjectionView(investmentValue, years, mode);
    return (
      <StockCard
        name={investmentValue.name}
        ticker={investmentValue.ticker}
        futureDisplay={view.futureDisplay}
        formattedAmount={formattedAmount}
        percentDisplay={view.percentDisplay}
        gainDisplay={view.gainDisplay}
        valueColor={view.valueColor}
        isLast={isLastItem}
        onPress={() => {}}
        cardWidth={cardWidth}
        badgeText={view.badgeText}
        badgeColor={view.badgeColor}
      />
    );
  };

  // Main render
  return (
    <ScreenContainer contentStyle={{ paddingVertical: sectionVerticalSpacing }}>
      <ScrollView
        contentContainerStyle={[styles.content, isSmallPhone && styles.contentCompact]}
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
        <View style={[styles.headerRow, isSmallPhone && styles.headerRowCompact]}>
          <BackButton />
        </View>

        <ResponsiveContainer maxWidth={width - contentHorizontalPadding * 2}>
          <>
            <View style={{ width: '100%' }}>
              <ReceiptCard
                image={image}
                amount={formattedAmount}
                label={formatRelativeDate(date)}
                time={new Date(date).toLocaleString()}
                onPress={() => {}}
                source={source}
                confidence={confidence}
              />
            </View>

            {/* Total Amount — tappable to edit */}
            <ReceiptMetaPanel
              label="Total Amount"
              value={formatCurrencyGBP(totalAmount || 0)}
              onPress={() => {
                setAmountEditValue(totalAmount > 0 ? totalAmount.toFixed(2) : '');
                setAmountModalVisible(true);
              }}
              accessibilityLabel="Edit total amount"
            />

            {/* Date — tappable to edit */}
            <ReceiptMetaPanel
              label="Date"
              value={formatRelativeDate(receipt?.transaction_date ?? date)}
              onPress={() => {
                setDateEditValue(receipt?.transaction_date ?? date ?? '');
                setDateModalVisible(true);
              }}
              accessibilityLabel="Edit transaction date"
            />

            {merchantName && (
              <ReceiptMetaPanel
                label="Merchant"
                value={merchantName}
                onPress={() => {
                  setMerchantEditValue(merchantName);
                  setMerchantModalVisible(true);
                }}
                accessibilityLabel="Edit merchant name"
              />
            )}

            {lineItems.length > 0 && (
              <ReceiptItemsCard
                items={lineItems}
                subtotal={itemsSubtotal}
                totalAmount={totalAmount}
                mismatch={totalMismatch}
              />
            )}

            <ReceiptMetaPanel
              label="Category"
              value={categoryName ?? 'Uncategorised'}
              onPress={() => setCategoryModalVisible(true)}
              accessibilityLabel="Edit category"
            />

            <ReceiptExtractionDetails
              source={source}
              confidencePct={confidencePct}
              processingTimeMs={processingTimeMs}
            />

            {/* Spacer before investment projections */}
            <View style={{ height: spacing.xl }} />

            <ProjectionCarouselSection
              title={`Your ${formattedAmount} could have been...`}
              subtitle={`If invested ${formattedYearsLabel} ago`}
              periodValue={selectedYears}
              onPeriodChange={setSelectedYears}
              compact={isSmallPhone}
              carouselTitle="Investment Outlook"
              carouselSubtitle="Swipe to explore different stocks"
              data={investmentOptions}
              keyExtractor={(item: any) => item.ticker}
              renderItem={({ item, index }) =>
                renderStockCard(item, index === investmentOptions.length - 1, selectedYears, 'past')
              }
              snapInterval={snapInterval}
            />

            <View style={[styles.sectionSpacing, { height: sectionVerticalSpacing }]} />

            <ProjectionCarouselSection
              title={`Your ${formattedAmount} could become...`}
              subtitle={`If invested today for ${formattedFutureYearsLabel}`}
              periodValue={selectedFutureYears}
              onPeriodChange={setSelectedFutureYears}
              compact={isSmallPhone}
              carouselTitle="Potential Growth"
              carouselSubtitle="LSTM badge = model's predicted direction + confidence (5 trading days)"
              data={futureInvestmentOptions}
              keyExtractor={(item: any) => `future-${item.ticker}`}
              renderItem={({ item, index }) =>
                renderStockCard(
                  item,
                  index === futureInvestmentOptions.length - 1,
                  selectedFutureYears,
                  'future',
                )
              }
              snapInterval={snapInterval}
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
            Projections are hypothetical and generated by a deep-learning (LSTM) model that predicts
            each stock's likely direction and confidence. The projected growth rate reflects the
            selected period's historical performance and is not a guarantee of future results. Past
            performance does not predict future returns.
          </Text>
        </View>
      </ScrollView>

      <DepositModal
        visible={depositModalVisible}
        formattedAmount={formattedAmount}
        portfolios={portfolioList}
        loading={portfoliosLoading}
        depositingPid={depositingPid}
        onSelectPortfolio={handleSelectPortfolio}
        onClose={() => setDepositModalVisible(false)}
      />

      <CategoryPickerModal
        visible={categoryModalVisible}
        categories={categories}
        selectedCategoryId={receipt?.category_id ?? null}
        saving={categorySaving}
        onSelectCategory={handleSelectCategory}
        onClose={() => setCategoryModalVisible(false)}
      />

      <EditValueModal
        visible={merchantModalVisible}
        title="Edit merchant name"
        value={merchantEditValue}
        onChangeText={setMerchantEditValue}
        onSave={handleUpdateMerchant}
        onClose={() => setMerchantModalVisible(false)}
        saving={merchantSaving}
        placeholder="Enter merchant name"
      />

      <EditValueModal
        visible={amountModalVisible}
        title="Edit total amount"
        value={amountEditValue}
        onChangeText={setAmountEditValue}
        onSave={handleUpdateAmount}
        onClose={() => setAmountModalVisible(false)}
        saving={amountSaving}
        placeholder="0.00"
        keyboardType="decimal-pad"
      />

      <EditValueModal
        visible={dateModalVisible}
        title="Edit transaction date"
        value={dateEditValue}
        onChangeText={setDateEditValue}
        onSave={handleUpdateDate}
        onClose={() => setDateModalVisible(false)}
        saving={dateSaving}
        placeholder="YYYY-MM-DD"
      />
    </ScreenContainer>
  );
}

// Styles
type Styles = {
  content: ViewStyle;
  contentCompact: ViewStyle;
  headerRow: ViewStyle;
  headerRowCompact: ViewStyle;
  sectionSpacing: ViewStyle;
  warningBox: ViewStyle;
  warningBoxCompact: ViewStyle;
  warningIcon: ViewStyle;
  warningText: TextStyle;
  depositButton: ViewStyle;
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
  sectionSpacing: {
    height: spacing.xxl,
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
});
