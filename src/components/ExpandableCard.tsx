/**
 * ExpandableCard
 *
 * Reusable collapsible card with header and expandable content.
 */

import React from 'react';
import { View, StyleSheet, Pressable, StyleProp, ViewStyle } from 'react-native';
import AppText from './AppText';
import { Ionicons } from '@expo/vector-icons';
import { useTheme } from '../contexts/ThemeContext';
import { radii, spacing, typography, shadows, sizes } from '../styles/theme';

type Props = {
  /** Ionicon name to display on the left side of the card */
  icon: keyof typeof Ionicons.glyphMap;
  /** Color for the icon (typically theme.primary or theme.accent) */
  iconColor: string;
  /** Main heading text displayed prominently */
  title: string;
  /** Subtitle/description text displayed below the title */
  description: string;
  /** Controls whether the expandable content is visible */
  isExpanded: boolean;
  /** Callback function triggered when the card is pressed */
  onToggle: () => void;
  /** Optional content to display when the card is expanded */
  expandedContent?: React.ReactNode;
  /** Optional custom styling for the card container */
  style?: StyleProp<ViewStyle>;
};

export default function ExpandableCard({
  icon,
  iconColor,
  title,
  description,
  isExpanded,
  onToggle,
  expandedContent,
  style,
}: Props) {
  const { theme } = useTheme();

  return (
    <Pressable onPress={onToggle} style={[styles.card, { backgroundColor: theme.surface }, style]}>
      <Ionicons name={icon} size={22} color={iconColor} style={styles.icon} />
      <View style={styles.content}>
        <View style={styles.header}>
          <AppText style={[styles.title, { color: theme.text }]}>{title}</AppText>
          <Ionicons
            name={isExpanded ? 'chevron-up' : 'chevron-down'}
            size={20}
            color={theme.textSecondary}
          />
        </View>
        <AppText style={[styles.description, { color: theme.textSecondary }]}>
          {description}
        </AppText>

        {isExpanded && expandedContent && (
          <View style={styles.expandedContent}>{expandedContent}</View>
        )}
      </View>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  card: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    borderRadius: radii.lg,
    padding: spacing.lg,
    marginBottom: spacing.md,
    ...shadows.level1,
  },
  icon: {
    marginRight: spacing.md,
    width: sizes.avatarSm,
    textAlign: 'center',
  },
  content: {
    flex: 1,
  },
  header: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: spacing.xs,
  },
  title: {
    ...typography.bodyStrong,
  },
  description: {
    ...typography.caption,
  },
  expandedContent: {
    marginTop: spacing.md,
    paddingTop: spacing.md,
    borderTopWidth: StyleSheet.hairlineWidth,
    borderTopColor: '#e0e0e0',
  },
});
