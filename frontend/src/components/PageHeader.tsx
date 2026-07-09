/**
 * PageHeader
 *
 * Page title with optional subtitle and consistent spacing.
 */

import React from 'react';
import { View, StyleSheet, ViewStyle } from 'react-native';
import AppText from './AppText';
import { typography, spacing } from '../styles/theme';
import { useTheme } from '../contexts/ThemeContext';

type Props = {
  /** Title content (can be text or custom React elements) */
  children?: React.ReactNode;
  /** Optional subtitle displayed below the title */
  subtitle?: React.ReactNode;
  /** Optional custom styling for the header container */
  style?: ViewStyle;
  /** Optional content displayed on the right side (e.g., buttons, icons) */
  headerRight?: React.ReactNode;
};

export default function PageHeader({ children, subtitle, style }: Props) {
  const { theme } = useTheme();

  return (
    <View style={[styles.header, style]}>
      <View style={styles.left}>
        {typeof children === 'string' ? (
          <AppText style={typography.sectionTitle}>{children}</AppText>
        ) : (
          children
        )}
      </View>
      {subtitle ? (
        <AppText style={[styles.subtitle, { color: theme.text, opacity: 0.7 }]}>{subtitle}</AppText>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  header: {
    marginBottom: spacing.sm,
  },
  left: {},
  subtitle: {
    marginTop: spacing.xs,
    ...typography.pageSubtitle,
  },
});
