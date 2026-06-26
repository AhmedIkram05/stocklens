/**
 * FormInput
 *
 * Themed text input with optional password visibility toggle.
 */

import React, { useEffect, useState } from 'react';
import {
  View,
  TextInput,
  StyleSheet,
  TextInputProps,
  TextStyle,
  ViewStyle,
  TouchableOpacity,
} from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { radii, spacing, typography, shadows } from '../styles/theme';
import { useTheme } from '../contexts/ThemeContext';

type Props = TextInputProps & {
  /** Optional custom styling for the container View */
  containerStyle?: ViewStyle;
  /** Optional custom styling for the TextInput itself */
  inputStyle?: TextStyle;
  /** Whether to render an in-field eye icon to toggle password visibility */
  showPasswordToggle?: boolean;
};

/**
 * Renders a themed text input with consistent styling.
 * Inherits all standard TextInput props (value, onChangeText, placeholder, etc.).
 */
export default function FormInput({
  containerStyle,
  inputStyle,
  style,
  showPasswordToggle = false,
  secureTextEntry,
  ...rest
}: Props) {
  const { theme } = useTheme();
  const shouldShowToggle = !!(showPasswordToggle && secureTextEntry);
  const [isSecure, setIsSecure] = useState(!!secureTextEntry);

  useEffect(() => {
    setIsSecure(!!secureTextEntry);
  }, [secureTextEntry]);

  const accessibilityLabel = isSecure ? 'Show password' : 'Hide password';

  return (
    <View style={[styles.container, containerStyle]}>
      <View style={styles.inputWrapper}>
        <TextInput
          {...rest}
          secureTextEntry={shouldShowToggle ? isSecure : secureTextEntry}
          allowFontScaling
          accessibilityLabel={rest.accessibilityLabel ?? rest.placeholder}
          style={[
            styles.input,
            shouldShowToggle && styles.inputWithToggle,
            inputStyle,
            style,
            { backgroundColor: theme.surface, color: theme.text, borderColor: theme.textSecondary },
          ]}
          placeholderTextColor={theme.textSecondary}
        />
        {shouldShowToggle && (
          <TouchableOpacity
            onPress={() => setIsSecure((prev) => !prev)}
            style={styles.toggleButton}
            accessibilityRole="button"
            accessibilityLabel={accessibilityLabel}
            hitSlop={{ top: 12, bottom: 12, left: 12, right: 12 }}
          >
            <Ionicons name={isSecure ? 'eye' : 'eye-off'} size={20} color={theme.textSecondary} />
          </TouchableOpacity>
        )}
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    marginBottom: spacing.md,
  },
  inputWrapper: {
    position: 'relative',
  },
  input: {
    borderWidth: 1,
    borderRadius: radii.md,
    padding: spacing.md,
    ...typography.body,
    ...shadows.level1,
  },
  inputWithToggle: {
    paddingRight: spacing.xxl,
  },
  toggleButton: {
    position: 'absolute',
    right: spacing.md,
    top: 0,
    bottom: 0,
    justifyContent: 'center',
    alignItems: 'center',
  },
});
