/**
 * IconButton
 *
 * Compact circular icon-only button with hitSlop.
 */

import React from 'react';
import { TouchableOpacity, StyleSheet, ViewStyle } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { brandColors } from '../contexts/ThemeContext';
import { radii, shadows, spacing, sizes } from '../styles/theme';

type Props = {
  /** Ionicon name to display in the button */
  name: React.ComponentProps<typeof Ionicons>['name'];
  /** Size of the icon in pixels. Default: 20 */
  size?: number;
  /** Color of the icon. Default: white */
  color?: string;
  /** Callback triggered when button is pressed */
  onPress?: () => void;
  /** Optional custom styling for the button container */
  style?: ViewStyle | ViewStyle[];
  /** Accessibility label for screen readers */
  accessibilityLabel?: string;
};

/** Render a circular icon button. */
export default function IconButton({
  name,
  size = 20,
  color = brandColors.white,
  onPress,
  style,
  accessibilityLabel,
}: Props) {
  if (__DEV__ && !accessibilityLabel) {
    // Ensure icon-only buttons are reachable by screen readers during development
    console.warn(
      'IconButton missing accessibilityLabel — add accessibilityLabel for screen readers',
    );
  }
  return (
    <TouchableOpacity
      onPress={onPress}
      style={[styles.button, style]}
      accessibilityRole="button"
      accessibilityLabel={accessibilityLabel}
      hitSlop={{ top: 10, bottom: 10, left: 10, right: 10 }}
    >
      <Ionicons name={name} size={size} color={color} />
    </TouchableOpacity>
  );
}

const styles = StyleSheet.create({
  button: {
    width: sizes.controlMd,
    height: sizes.controlMd,
    borderRadius: radii.pill,
    backgroundColor: brandColors.green,
    justifyContent: 'center',
    alignItems: 'center',
    ...shadows.level2,
    margin: spacing.xs / 2,
  },
});
