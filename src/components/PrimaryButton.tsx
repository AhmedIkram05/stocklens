/**
 * PrimaryButton
 *
 * Themed primary CTA button.
 */

import React from 'react';
import { Pressable, StyleSheet, StyleProp, ViewStyle, TextStyle } from 'react-native';
import AppText from './AppText';
import { brandColors } from '../contexts/ThemeContext';
import { radii, spacing, typography, shadows } from '../styles/theme';
import { useTheme } from '../contexts/ThemeContext';

type Props = {
  /** Callback triggered when button is pressed */
  onPress?: () => void;
  /** Button text content (can also be React elements) */
  children?: React.ReactNode;
  /** Optional custom styling for the button container */
  style?: StyleProp<ViewStyle>;
  /** Optional custom styling for the button text */
  textStyle?: StyleProp<TextStyle>;
  /** When true, button is non-interactive with reduced opacity */
  disabled?: boolean;
  /** Accessibility label for screen readers */
  accessibilityLabel?: string;
};

/**
 * Renders a styled primary action button with theme-aware text color.
 * Text color automatically switches between white (light mode) and black (dark mode).
 * Uses Pressable with platform-specific press feedback for native feel.
 */
export default function PrimaryButton({
  onPress,
  children,
  style,
  textStyle,
  disabled,
  accessibilityLabel,
}: Props) {
  const { isDark } = useTheme();

  return (
    <Pressable
      onPress={onPress}
      style={({ pressed }) => [
        styles.button,
        disabled && styles.disabled,
        pressed && { opacity: 0.6 },
        style,
      ]}
      disabled={disabled}
      accessibilityRole="button"
      accessibilityLabel={accessibilityLabel}
    >
      <AppText
        style={[styles.text, { color: isDark ? brandColors.black : brandColors.white }, textStyle]}
      >
        {children}
      </AppText>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  button: {
    backgroundColor: brandColors.green,
    borderRadius: radii.xl,
    paddingVertical: spacing.lg,
    alignItems: 'center',
    justifyContent: 'center',
    ...shadows.level2,
  },
  text: {
    color: brandColors.white,
    ...typography.button,
  },
  disabled: {
    opacity: 0.45,
  },
});
