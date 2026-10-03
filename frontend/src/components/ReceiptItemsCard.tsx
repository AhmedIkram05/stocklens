/**
 * ReceiptItemsCard
 *
 * Line-item breakdown for a receipt, with a warning when the items subtotal
 * does not match the scanned total. Presentational.
 */

import React from 'react';
import { View, Text, StyleSheet } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { brandColors } from '../contexts/ThemeContext';
import { useTheme } from '../contexts/ThemeContext';
import { radii, spacing, typography } from '../styles/theme';
import { formatCurrencyGBP } from '../utils/formatters';

type Props = {
  /** Line items (name/description + price/amount) */
  items: any[];
  /** Sum of the item prices, formatted for display */
  subtotal: number;
  /** Scanned receipt total, shown in the mismatch warning */
  totalAmount: number;
  /** When true, shows the subtotal-vs-total mismatch warning */
  mismatch: boolean;
};

export default function ReceiptItemsCard({ items, subtotal, totalAmount, mismatch }: Props) {
  const { theme } = useTheme();

  return (
    <View style={[styles.itemsPanel, { backgroundColor: theme.surface }]}>
      <View style={styles.itemHeaderRow}>
        <Text style={[styles.cascadeTitle, { color: theme.text }]}>Items ({items.length})</Text>
        <Text style={[styles.itemSubtotal, { color: theme.text }]}>
          {formatCurrencyGBP(subtotal)}
        </Text>
      </View>
      {items.map((it, i) => (
        <View key={i} style={styles.itemRow}>
          <Text style={[styles.itemName, { color: theme.text }]}>
            {it.name ?? it.description ?? 'Item'}
          </Text>
          <Text style={[styles.itemPrice, { color: theme.text }]}>
            {formatCurrencyGBP(it.price ?? it.amount ?? 0)}
          </Text>
        </View>
      ))}
      {mismatch && (
        <View style={[styles.totalMismatchBox, { backgroundColor: brandColors.red + '14' }]}>
          <Ionicons name="warning" size={16} color={brandColors.red} />
          <Text style={[styles.totalMismatchText, { color: brandColors.red }]}>
            Items total {formatCurrencyGBP(subtotal)} but receipt says{' '}
            {formatCurrencyGBP(totalAmount)}. The scanned total may be incorrect — tap Total Amount
            above to fix it.
          </Text>
        </View>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  itemsPanel: {
    borderRadius: radii.md,
    padding: spacing.md,
    marginTop: spacing.md,
  },
  itemHeaderRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: spacing.md,
  },
  cascadeTitle: {
    ...typography.sectionTitle,
    marginBottom: spacing.md,
  },
  itemSubtotal: {
    ...typography.bodyStrong,
  },
  itemRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    paddingVertical: spacing.sm,
    borderTopWidth: StyleSheet.hairlineWidth,
    borderTopColor: 'rgba(0,0,0,0.08)',
  },
  itemName: {
    ...typography.body,
    flex: 1,
    marginRight: spacing.sm,
  },
  itemPrice: {
    ...typography.bodyStrong,
  },
  totalMismatchBox: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    gap: spacing.sm,
    marginTop: spacing.md,
    padding: spacing.sm,
    borderRadius: radii.sm,
  },
  totalMismatchText: {
    ...typography.caption,
    flex: 1,
    lineHeight: 18,
  },
});
