/**
 * EmptyState
 *
 * Reusable centered empty-state UI with icon, title, optional subtitle and action.
 */

import React from 'react';
import { View, TouchableOpacity, StyleSheet } from 'react-native';
import AppText from './AppText';
import { Ionicons } from '@expo/vector-icons';
import { brandColors, useTheme } from '../contexts/ThemeContext';
import { radii, spacing, typography, shadows } from '../styles/theme';

type Props = {
  iconName?: string;
  title: string;
  subtitle?: string;
  primaryText?: string;
  onPrimaryPress?: () => void;
};

/** Centered empty-state UI component. */
export default function EmptyState({
  iconName = 'checkmark-circle',
  title,
  subtitle,
  primaryText,
  onPrimaryPress,
}: Props) {
  const { theme } = useTheme();
  return (
    <View style={styles.container}>
      <Ionicons name={iconName as any} size={96} color={brandColors.green} />
      <AppText style={[styles.title, { color: theme.text }]}>{title}</AppText>
      {subtitle ? (
        <AppText style={[styles.subtitle, { color: theme.textSecondary }]}>{subtitle}</AppText>
      ) : null}
      {primaryText ? (
        <TouchableOpacity style={styles.button} onPress={onPrimaryPress} accessibilityRole="button">
          <AppText style={styles.buttonText}>{primaryText}</AppText>
        </TouchableOpacity>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    alignItems: 'center',
    padding: spacing.lg,
  },
  title: {
    ...typography.pageTitle,
    marginTop: spacing.md,
    marginBottom: spacing.xs,
  },
  subtitle: {
    ...typography.caption,
    textAlign: 'center',
    marginBottom: spacing.md,
  },
  button: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: brandColors.green,
    paddingHorizontal: spacing.lg,
    paddingVertical: spacing.md,
    borderRadius: radii.md,
    ...shadows.level2,
  },
  buttonText: {
    color: brandColors.white,
    ...typography.button,
  },
});
