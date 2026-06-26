/**
 * SettingRow
 *
 * Reusable settings list row with icon, title, subtitle and optional right accessory.
 */

import React from 'react';
import { Pressable, View, StyleSheet, ViewStyle } from 'react-native';
import AppText from './AppText';
import { Ionicons } from '@expo/vector-icons';
import { radii, spacing, typography, shadows, sizes } from '../styles/theme';
import { useTheme } from '../contexts/ThemeContext';

type Props = {
  /** Ionicons icon name to display (e.g., "settings-outline", "notifications") */
  icon?: keyof typeof Ionicons.glyphMap;
  /** Background color for icon container */
  iconBgColor?: string;
  /** Main text displayed in the row */
  title: string;
  /** Optional subtitle displayed below the title */
  subtitle?: string;
  /** Optional content displayed on the right side (e.g., Switch, chevron, value) */
  right?: React.ReactNode;
  /** Callback triggered when the row is pressed (if omitted, row is non-pressable) */
  onPress?: () => void;
  /** When true, applies error/destructive color to title text */
  destructive?: boolean;
  /** Optional custom styling for the row container */
  style?: ViewStyle;
};

export default function SettingRow({
  icon,
  iconBgColor,
  title,
  subtitle,
  right,
  onPress,
  destructive,
  style,
}: Props) {
  const { theme } = useTheme();

  const Title = (
    <AppText style={[styles.title, { color: theme.text }, destructive && { color: theme.error }]}>
      {title}
    </AppText>
  );

  return (
    <Pressable
      onPress={onPress}
      style={({ pressed }) => [
        styles.row,
        { backgroundColor: theme.surface },
        pressed && onPress && { opacity: 0.6 },
        style,
      ]}
      disabled={!onPress}
    >
      {icon ? (
        <View style={[styles.iconContainer, { backgroundColor: iconBgColor }]}>
          <Ionicons name={icon} size={24} color={theme.text} />
        </View>
      ) : null}

      <View style={styles.content}>
        {Title}
        {subtitle ? (
          <AppText style={[styles.subtitle, { color: theme.textSecondary }]}>{subtitle}</AppText>
        ) : null}
      </View>

      <View style={styles.right}>{right}</View>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  row: {
    flexDirection: 'row',
    alignItems: 'center',
    borderRadius: radii.lg,
    paddingHorizontal: spacing.lg,
    paddingVertical: spacing.md,
    marginBottom: spacing.md,
    justifyContent: 'space-between',
    ...shadows.level2,
  },
  iconContainer: {
    width: sizes.controlSm,
    height: sizes.controlSm,
    borderRadius: radii.md,
    justifyContent: 'center',
    alignItems: 'center',
    marginRight: spacing.md,
  },
  content: {
    flex: 1,
  },
  right: {
    marginLeft: spacing.md,
  },
  title: {
    ...typography.bodyStrong,
    marginBottom: spacing.xs,
  },
  subtitle: {
    ...typography.caption,
  },
});
