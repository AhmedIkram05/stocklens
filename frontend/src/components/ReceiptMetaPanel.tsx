/**
 * ReceiptMetaPanel
 *
 * Tappable label/value row for receipt fields (amount, date, merchant, category).
 * Presentational — the caller owns the value and press handler.
 */

import React from 'react';
import { View, Text, StyleSheet, TouchableOpacity } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { radii, spacing, typography } from '../styles/theme';
import { useTheme } from '../contexts/ThemeContext';

type Props = {
  /** Field label shown on the left (e.g. "Total Amount") */
  label: string;
  /** Formatted value shown on the right (e.g. "£12.50") */
  value: string;
  /** Called when the panel is pressed */
  onPress: () => void;
  /** Accessibility label describing the action (e.g. "Edit total amount") */
  accessibilityLabel: string;
};

export default function ReceiptMetaPanel({ label, value, onPress, accessibilityLabel }: Props) {
  const { theme } = useTheme();

  return (
    <TouchableOpacity
      style={[styles.metaPanel, { backgroundColor: theme.surface }]}
      onPress={onPress}
      activeOpacity={0.7}
      accessibilityLabel={accessibilityLabel}
    >
      <Text style={[styles.metaLabel, { color: theme.textSecondary }]}>{label}</Text>
      <View style={styles.valueRow}>
        <Text style={[styles.metaValue, { color: theme.text }]}>{value}</Text>
        <Ionicons name="chevron-forward" size={16} color={theme.textSecondary} />
      </View>
    </TouchableOpacity>
  );
}

const styles = StyleSheet.create({
  metaPanel: {
    borderRadius: radii.md,
    padding: spacing.md,
    marginTop: spacing.md,
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
  },
  metaLabel: {
    ...typography.body,
  },
  metaValue: {
    ...typography.bodyStrong,
  },
  valueRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.xs,
  },
});
