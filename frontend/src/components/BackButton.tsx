/**
 * BackButton
 *
 * Shared navigation-back control. Replaces the scattered back affordances
 * (chevron IconButtons, raw TouchableOpacity+chevron, "Cancel" text buttons).
 *
 * Variants:
 *  - 'icon' (default): chevron-back glyph in a transparent circular hit area.
 *  - 'text': labelled text (e.g. "Cancel") for form screens that discard on leave.
 *
 * Defaults to navigation.goBack(); pass `onPress` to override (e.g. SignUp's
 * canGoBack -> navigate('Login') fallback).
 */

import React from 'react';
import { TouchableOpacity, StyleSheet, ViewStyle, Text } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { useNavigation } from '@react-navigation/native';
import { useTheme } from '../contexts/ThemeContext';
import { radii, spacing, sizes } from '../styles/theme';

type Props = {
  /** 'icon' renders a chevron; 'text' renders a labelled button. Default 'icon'. */
  variant?: 'icon' | 'text';
  /** Label for the 'text' variant. Default 'Cancel'. */
  label?: string;
  /** Override the default goBack behaviour. */
  onPress?: () => void;
  /** Disable presses (e.g. while a form is submitting). */
  disabled?: boolean;
  /** Override the icon/text color (defaults to theme.text / theme.primary). */
  color?: string;
  /** Screen-reader label. Default 'Go back'. */
  accessibilityLabel?: string;
  style?: ViewStyle | ViewStyle[];
};

export default function BackButton({
  variant = 'icon',
  label = 'Cancel',
  onPress,
  disabled = false,
  color,
  accessibilityLabel = 'Go back',
  style,
}: Props) {
  const navigation = useNavigation();
  const { theme } = useTheme();

  const handlePress = () => {
    if (disabled) return;
    if (onPress) onPress();
    else navigation.goBack();
  };

  if (__DEV__ && !accessibilityLabel) {
    // Ensure icon/text back controls are reachable by screen readers during development
    console.warn(
      'BackButton missing accessibilityLabel — add accessibilityLabel for screen readers',
    );
  }

  if (variant === 'text') {
    return (
      <TouchableOpacity
        onPress={handlePress}
        disabled={disabled}
        accessibilityRole="button"
        accessibilityLabel={accessibilityLabel}
        hitSlop={{ top: 10, bottom: 10, left: 10, right: 10 }}
        style={style}
      >
        <Text style={[styles.text, { color: color ?? theme.primary }, disabled && styles.disabled]}>
          {label}
        </Text>
      </TouchableOpacity>
    );
  }

  return (
    <TouchableOpacity
      onPress={handlePress}
      disabled={disabled}
      accessibilityRole="button"
      accessibilityLabel={accessibilityLabel}
      hitSlop={{ top: 10, bottom: 10, left: 10, right: 10 }}
      style={[styles.iconButton, style]}
    >
      <Ionicons name="chevron-back" size={24} color={color ?? theme.text} />
    </TouchableOpacity>
  );
}

const styles = StyleSheet.create({
  iconButton: {
    width: sizes.controlMd,
    height: sizes.controlMd,
    borderRadius: radii.pill,
    justifyContent: 'center',
    alignItems: 'center',
    margin: spacing.xs / 2,
  },
  text: {
    fontSize: 16,
    fontWeight: '600',
  },
  disabled: {
    opacity: 0.4,
  },
});
