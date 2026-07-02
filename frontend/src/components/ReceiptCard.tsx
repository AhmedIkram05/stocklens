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
};

export default function ReceiptCard({ image, amount, label, time, onPress, style }: Props) {
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
    </TouchableOpacity>
  );
}

const styles = StyleSheet.create({
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
