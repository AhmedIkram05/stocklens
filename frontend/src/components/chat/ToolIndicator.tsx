/**
 * ToolIndicator
 *
 * Animated indicator showing "Using [tool name]..." with a loading spinner.
 * Disappears when tool completes (when toolName is null).
 */

import React, { useEffect, useRef } from 'react';
import { Text, Animated, StyleSheet, ActivityIndicator } from 'react-native';
import { useTheme } from '../../contexts/ThemeContext';
import { spacing, typography } from '../../styles/theme';

interface ToolIndicatorProps {
  toolName: string | null;
}

export default function ToolIndicator({ toolName }: ToolIndicatorProps) {
  const { theme } = useTheme();
  const opacity = useRef(new Animated.Value(0)).current;

  useEffect(() => {
    Animated.timing(opacity, {
      toValue: toolName ? 1 : 0,
      duration: 200,
      useNativeDriver: true,
    }).start();
  }, [toolName, opacity]);

  if (!toolName) return null;

  return (
    <Animated.View style={[styles.container, { opacity, backgroundColor: theme.background }]}>
      <ActivityIndicator size="small" color={theme.primary} />
      <Text style={[styles.label, { color: theme.textSecondary }]} numberOfLines={1}>
        Using {toolName}...
      </Text>
    </Animated.View>
  );
}

const styles = StyleSheet.create({
  container: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    paddingVertical: spacing.sm,
    paddingHorizontal: spacing.md,
    gap: spacing.sm,
  },
  label: {
    ...typography.caption,
    fontSize: 13,
  },
});
