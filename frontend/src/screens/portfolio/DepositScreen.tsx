import React, { useState, useEffect } from 'react';
import {
  View,
  Text,
  TextInput,
  TouchableOpacity,
  FlatList,
  StyleSheet,
  ActivityIndicator,
  KeyboardAvoidingView,
  Platform,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { useNavigation, useRoute, RouteProp } from '@react-navigation/native';
import { StackNavigationProp } from '@react-navigation/stack';

import { brandColors, useTheme } from '../../contexts/ThemeContext';
import { spacing, typography, radii } from '../../styles/theme';
import { PortfolioStackParamList } from '../../navigation/AppNavigator';
import { portfolioService } from '../../services/portfolios';
import { receiptService, Receipt } from '../../services/receipts';
import { formatCurrencyRounded } from '../../utils/formatters';

type DepositRoute = RouteProp<PortfolioStackParamList, 'Deposit'>;
type DepositNav = StackNavigationProp<PortfolioStackParamList, 'Deposit'>;

type TabMode = 'receipt' | 'manual';

export default function DepositScreen() {
  const route = useRoute<DepositRoute>();
  const navigation = useNavigation<DepositNav>();
  const { theme } = useTheme();
  const { portfolioId } = route.params;

  const [tab, setTab] = useState<TabMode>('receipt');

  const [receipts, setReceipts] = useState<Receipt[]>([]);
  const [loading, setLoading] = useState(true);
  const [receiptError, setReceiptError] = useState<string | null>(null);

  const [selectedReceipt, setSelectedReceipt] = useState<Receipt | null>(null);
  const [manualAmount, setManualAmount] = useState('');
  const [manualNotes, setManualNotes] = useState('');

  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);

  useEffect(() => {
    loadReceipts();
  }, []);

  async function loadReceipts() {
    setLoading(true);
    setReceiptError(null);
    try {
      const data = await receiptService.list(20, 0);
      setReceipts(data);
    } catch {
      setReceiptError('Could not load receipts');
    } finally {
      setLoading(false);
    }
  }

  const selectedAmount = selectedReceipt ? selectedReceipt.total_amount : 0;
  const manualAmountNum = parseFloat(manualAmount);
  const depositAmount = tab === 'receipt' ? selectedAmount : manualAmountNum;
  const isValid = tab === 'receipt' ? selectedReceipt !== null : manualAmountNum > 0;
  const depositLabel = isValid ? `Deposit ${formatCurrencyRounded(depositAmount)}` : 'Deposit';

  async function handleConfirm() {
    if (!isValid) return;
    setSubmitting(true);
    setSubmitError(null);
    try {
      if (tab === 'receipt' && selectedReceipt) {
        await portfolioService.createCashFlow(portfolioId, {
          amount: selectedReceipt.total_amount,
          source: 'receipt',
          source_id: selectedReceipt.id,
          notes: selectedReceipt.merchant_name ?? '',
        });
      } else {
        await portfolioService.createCashFlow(portfolioId, {
          amount: manualAmountNum,
          source: 'manual',
          notes: manualNotes || undefined,
        });
      }
      navigation.goBack();
    } catch {
      setSubmitError('Failed to process deposit. Please try again.');
    } finally {
      setSubmitting(false);
    }
  }

  function handleScanNew() {
    const parentNav = navigation.getParent();
    if (parentNav) {
      (parentNav as any).navigate('Scan');
    }
  }

  function renderReceiptItem({ item }: { item: Receipt }) {
    const isSelected = selectedReceipt?.id === item.id;
    return (
      <TouchableOpacity
        style={[
          styles.receiptCard,
          {
            backgroundColor: theme.surface,
            borderColor: isSelected ? brandColors.green : theme.border,
          },
        ]}
        onPress={() => setSelectedReceipt(isSelected ? null : item)}
        activeOpacity={0.7}
      >
        <View style={styles.receiptInfo}>
          <Text style={[styles.receiptMerchant, { color: theme.text }]} numberOfLines={1}>
            {item.merchant_name || 'Unknown Merchant'}
          </Text>
          <Text style={[styles.receiptDate, { color: theme.textSecondary }]}>
            {new Date(item.scanned_at).toLocaleDateString()}
          </Text>
        </View>
        <Text style={[styles.receiptAmount, { color: theme.text }]}>
          {formatCurrencyRounded(item.total_amount)}
        </Text>
        {isSelected ? <View style={styles.selectedDot} /> : null}
      </TouchableOpacity>
    );
  }

  return (
    <SafeAreaView
      style={[styles.container, { backgroundColor: theme.background }]}
      edges={['top', 'bottom']}
    >
      <KeyboardAvoidingView
        style={styles.flex}
        behavior={Platform.OS === 'ios' ? 'padding' : undefined}
      >
        <View style={styles.header}>
          <TouchableOpacity onPress={() => navigation.goBack()}>
            <Text style={[styles.cancelText, { color: theme.secondary }]}>Cancel</Text>
          </TouchableOpacity>
          <Text style={[styles.title, { color: theme.text }]}>Add Deposit</Text>
          <View style={styles.headerSpacer} />
        </View>

        <View style={styles.tabBar}>
          <TouchableOpacity
            style={[
              styles.tab,
              tab === 'receipt' && { borderBottomColor: theme.primary, borderBottomWidth: 2 },
            ]}
            onPress={() => setTab('receipt')}
          >
            <Text
              style={[
                styles.tabText,
                { color: tab === 'receipt' ? theme.primary : theme.textSecondary },
              ]}
            >
              From Receipt
            </Text>
          </TouchableOpacity>
          <TouchableOpacity
            style={[
              styles.tab,
              tab === 'manual' && { borderBottomColor: theme.primary, borderBottomWidth: 2 },
            ]}
            onPress={() => setTab('manual')}
          >
            <Text
              style={[
                styles.tabText,
                { color: tab === 'manual' ? theme.primary : theme.textSecondary },
              ]}
            >
              Manual
            </Text>
          </TouchableOpacity>
        </View>

        {tab === 'receipt' ? (
          <View style={styles.flex}>
            {loading ? (
              <View style={styles.center}>
                <ActivityIndicator size="large" color={theme.primary} />
              </View>
            ) : receiptError ? (
              <View style={styles.center}>
                <Text style={[styles.errorText, { color: theme.error }]}>{receiptError}</Text>
                <TouchableOpacity onPress={loadReceipts}>
                  <Text style={[styles.retryText, { color: theme.secondary }]}>Retry</Text>
                </TouchableOpacity>
              </View>
            ) : receipts.length === 0 ? (
              <View style={styles.center}>
                <Text style={[styles.emptyText, { color: theme.textSecondary }]}>
                  No receipts found. Scan a receipt first.
                </Text>
                <TouchableOpacity
                  style={[styles.scanButton, { backgroundColor: theme.secondary }]}
                  onPress={handleScanNew}
                >
                  <Text style={styles.scanButtonText}>Scan New Receipt</Text>
                </TouchableOpacity>
              </View>
            ) : (
              <FlatList
                data={receipts}
                keyExtractor={(item) => item.id}
                renderItem={renderReceiptItem}
                contentContainerStyle={styles.listContent}
                showsVerticalScrollIndicator={false}
              />
            )}
          </View>
        ) : (
          <View style={[styles.manualContainer, { paddingHorizontal: spacing.lg }]}>
            <Text style={[styles.inputLabel, { color: theme.text }]}>Amount</Text>
            <TextInput
              style={[
                styles.amountInput,
                {
                  backgroundColor: theme.surface,
                  color: theme.text,
                  borderColor: theme.border,
                },
              ]}
              placeholder="0.00"
              placeholderTextColor={theme.textSecondary}
              keyboardType="decimal-pad"
              value={manualAmount}
              onChangeText={setManualAmount}
            />
            <Text style={[styles.inputLabel, { color: theme.text, marginTop: spacing.lg }]}>
              Notes (optional)
            </Text>
            <TextInput
              style={[
                styles.notesInput,
                {
                  backgroundColor: theme.surface,
                  color: theme.text,
                  borderColor: theme.border,
                },
              ]}
              placeholder="e.g. Monthly savings"
              placeholderTextColor={theme.textSecondary}
              value={manualNotes}
              onChangeText={setManualNotes}
              multiline
              numberOfLines={3}
            />
          </View>
        )}

        <View style={[styles.footer, { paddingHorizontal: spacing.lg }]}>
          {submitError ? (
            <Text style={[styles.errorText, { color: theme.error, marginBottom: spacing.sm }]}>
              {submitError}
            </Text>
          ) : null}
          <TouchableOpacity
            style={[
              styles.confirmButton,
              { backgroundColor: brandColors.blue },
              !isValid && styles.confirmButtonDisabled,
            ]}
            onPress={handleConfirm}
            disabled={!isValid || submitting}
          >
            {submitting ? (
              <ActivityIndicator size="small" color={brandColors.white} />
            ) : (
              <Text style={styles.confirmButtonText}>{depositLabel}</Text>
            )}
          </TouchableOpacity>
        </View>
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
  },
  flex: {
    flex: 1,
  },
  header: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingHorizontal: spacing.lg,
    paddingVertical: spacing.md,
  },
  cancelText: {
    ...typography.body,
  },
  title: {
    ...typography.subtitle,
    fontWeight: '700',
  },
  headerSpacer: {
    width: 60,
  },
  tabBar: {
    flexDirection: 'row',
    marginHorizontal: spacing.lg,
  },
  tab: {
    flex: 1,
    paddingVertical: spacing.sm,
    alignItems: 'center',
  },
  tabText: {
    ...typography.bodyStrong,
  },
  center: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
    paddingHorizontal: spacing.xl,
  },
  errorText: {
    ...typography.body,
    textAlign: 'center',
  },
  retryText: {
    ...typography.bodyStrong,
    marginTop: spacing.md,
  },
  emptyText: {
    ...typography.body,
    textAlign: 'center',
    marginBottom: spacing.lg,
  },
  scanButton: {
    borderRadius: radii.md,
    paddingVertical: spacing.sm + 2,
    paddingHorizontal: spacing.xl,
  },
  scanButtonText: {
    ...typography.button,
    color: brandColors.white,
  },
  listContent: {
    padding: spacing.lg,
  },
  receiptCard: {
    flexDirection: 'row',
    alignItems: 'center',
    borderRadius: radii.md,
    borderWidth: 1.5,
    padding: spacing.md,
    marginBottom: spacing.sm,
  },
  receiptInfo: {
    flex: 1,
  },
  receiptMerchant: {
    ...typography.bodyStrong,
  },
  receiptDate: {
    ...typography.caption,
    marginTop: 2,
  },
  receiptAmount: {
    ...typography.bodyStrong,
    marginLeft: spacing.md,
  },
  selectedDot: {
    width: 8,
    height: 8,
    borderRadius: 4,
    backgroundColor: brandColors.green,
    marginLeft: spacing.sm,
  },
  manualContainer: {
    flex: 1,
    paddingTop: spacing.xl,
  },
  inputLabel: {
    ...typography.captionStrong,
    marginBottom: spacing.sm,
  },
  amountInput: {
    ...typography.metric,
    borderRadius: radii.md,
    borderWidth: 1,
    paddingVertical: spacing.md,
    paddingHorizontal: spacing.lg,
    textAlign: 'center',
  },
  notesInput: {
    ...typography.body,
    borderRadius: radii.md,
    borderWidth: 1,
    padding: spacing.md,
    minHeight: 80,
    textAlignVertical: 'top',
  },
  footer: {
    paddingVertical: spacing.lg,
    paddingBottom: 80,
  },
  confirmButton: {
    borderRadius: radii.md,
    paddingVertical: spacing.md + 2,
    alignItems: 'center',
  },
  confirmButtonDisabled: {
    opacity: 0.5,
  },
  confirmButtonText: {
    ...typography.button,
    color: brandColors.white,
  },
});
