/**
 * ReceiptCard
 *
 * Pressable receipt preview card with thumbnail, amount and time.
 */

import React from 'react';
import useDecryptedImage from '@/hooks/useDecryptedImage';
import { View, Image, TouchableOpacity, StyleSheet, StyleProp, ViewStyle } from 'react-native';
import AppText from './AppText';
import { useTheme } from '../contexts/ThemeContext';
import { radii, spacing, typography, shadows, sizes } from '../styles/theme';

export type SourceBadgeKey = 'regex' | 'cascade' | 'degraded' | 'failed';

type Props = {
  /** Unique identifier for the receipt (optional, for tracking) */
  id?: string | number;
  /** URI string for the receipt image thumbnail */
  image?: string | undefined;
  /** Receipt amount (can be number, string, or formatted React element) */
  amount?: number | string | React.ReactNode;
  /** Display label (e.g., "2 hours ago", "Yesterday") */
  label?: string;
  /** Timestamp or date string (e.g., "2 hours ago", "Nov 9, 2025") */
  time?: string;
  /** Callback triggered when the card is pressed */
  onPress?: () => void;
  /** Optional custom styling for the card container */
  style?: StyleProp<ViewStyle>;
  /* * OCR extraction source: "regex" | "cascade" | "degraded" | "failed" */
  source?: SourceBadgeKey;
  /** OCR extraction confidence 0-100 */
  confidence?: number;
};

const SOURCE_BADGE: Record<string, { label: string; color: string }> = {
  regex: { label: 'Regex', color: '#22c55e' },
  cascade: { label: 'AI Enhanced', color: '#3b82f6' },
  degraded: { label: 'Low Quality', color: '#f97316' },
  failed: { label: 'Failed', color: '#ef4444' },
};

export default function ReceiptCard({ image, amount, label, time, onPress, style, source }: Props) {
  const { theme } = useTheme();
  const resolvedImage = useDecryptedImage(image);

  return (
    <TouchableOpacity
      testID="receipt-card"
      style={[styles.card, { backgroundColor: theme.surface }, style]}
      onPress={onPress}
      activeOpacity={0.85}
    >
      {resolvedImage ? (
        <Image testID="receipt-card-image" source={{ uri: resolvedImage }} style={styles.image} />
      ) : (
        <View testID="receipt-card-placeholder" style={styles.placeholder} />
      )}
      <View style={styles.info}>
        <AppText style={[styles.amount, { color: theme.text }]}>{amount}</AppText>
        <AppText style={[styles.label, { color: theme.textSecondary }]}>{label}</AppText>
        <AppText style={[styles.time, { color: theme.textSecondary }]}>{time}</AppText>
      </View>
      <AppText style={[styles.chevron, { color: theme.textSecondary }]}>›</AppText>
      {source && (
        <View
          style={[
            styles.badge,
            { backgroundColor: (SOURCE_BADGE[source]?.color ?? '#6b7280') + '20' },
          ]}
        >
          <AppText style={[styles.badgeText, { color: SOURCE_BADGE[source]?.color ?? '#6b7280' }]}>
            {SOURCE_BADGE[source]?.label ?? source}
          </AppText>
        </View>
      )}
    </TouchableOpacity>
  );
}

const styles = StyleSheet.create({
  badge: {
    paddingHorizontal: spacing.xs + 2,
    paddingVertical: 2,
    borderRadius: radii.sm,
    marginLeft: spacing.sm,
  },
  badgeText: {
    fontSize: 10,
    fontWeight: '600',
    textTransform: 'uppercase',
    letterSpacing: 0.5,
  },
  card: {
    flexDirection: 'row',
    alignItems: 'center',
    borderRadius: radii.md,
    padding: spacing.md,
    marginBottom: spacing.md,
    ...shadows.level1,
    alignSelf: 'stretch',
    minWidth: 0,
  },
  image: {
    width: sizes.avatarMd,
    height: sizes.avatarMd,
    borderRadius: 8,
    marginRight: spacing.md,
  },
  placeholder: {
    width: sizes.avatarMd,
    height: sizes.avatarMd,
    borderRadius: 8,
    marginRight: spacing.md,
    backgroundColor: '#f0f0f0',
  },
  info: {
    flex: 1,
  },
  amount: {
    ...typography.bodyStrong,
  },
  label: {
    ...typography.caption,
  },
  time: {
    ...typography.caption,
  },
  chevron: {
    ...typography.metricSm,
    marginLeft: spacing.sm,
  },
});
