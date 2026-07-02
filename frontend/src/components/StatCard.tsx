/**
 * StatCard
 *
 * Card for displaying numeric metrics with optional labels and variants.
 */

import React from 'react';
import { View, StyleSheet, ViewStyle, StyleProp } from 'react-native';
import AppText from './AppText';
import { brandColors, useTheme } from '../contexts/ThemeContext';
import { radii, spacing, typography, shadows } from '../styles/theme';

type Props = {
  /** Main value/metric to display (can be text, number, or React element) */
  value: React.ReactNode;
  /** Optional label displayed below the value */
  label?: string;
  /** Optional subtitle displayed below the label */
  subtitle?: string;
  /** Color variant for the card background. Default: 'white' */
  variant?: 'green' | 'blue' | 'white';
  /** Text alignment within the card. Default: 'center' */
  align?: 'center' | 'left';
  /** Optional custom styling for the card container */
  style?: StyleProp<ViewStyle>;
};

export default function StatCard({ value, label, subtitle, variant = 'white', style }: Props) {
  const { theme } = useTheme();

  const bg =
    variant === 'green' ? theme.primary : variant === 'blue' ? theme.secondary : theme.surface;
  const textColor = variant === 'white' ? theme.text : brandColors.white;

  return (
    <View style={[styles.card, { backgroundColor: bg }, style]}>
      <AppText style={[styles.value, { color: textColor }]}>{value}</AppText>
      {label ? <AppText style={[styles.label, { color: textColor }]}>{label}</AppText> : null}
      {subtitle ? (
        <AppText style={[styles.subtitle, { color: textColor, opacity: 0.85 }]}>{subtitle}</AppText>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  card: {
    borderRadius: radii.md,
    padding: spacing.lg,
    marginHorizontal: spacing.xs,
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
    ...shadows.level2,
  },
  value: {
    ...typography.metricSm,
    marginBottom: spacing.sm,
    textAlign: 'center',
  },
  label: {
    ...typography.body,
    textAlign: 'center',
  },
  subtitle: {
    fontSize: 11,
    lineHeight: 14,
    marginTop: spacing.xs,
    textAlign: 'center',
  },
});
