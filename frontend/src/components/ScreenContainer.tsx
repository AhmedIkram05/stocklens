/**
 * ScreenContainer
 *
 * Standard SafeArea wrapper providing responsive padding and theme background.
 */

import React from 'react';
import { SafeAreaView } from 'react-native-safe-area-context';
import { View, ViewStyle } from 'react-native';
import { useBreakpoint } from '../hooks/useBreakpoint';
import { useTheme } from '../contexts/ThemeContext';

type Props = {
  /** Screen content to render within the safe area */
  children: React.ReactNode;
  /** Optional custom styling for the SafeAreaView container */
  style?: ViewStyle;
  /** Optional custom styling for the inner content View */
  contentStyle?: ViewStyle;
  /** When true, removes internal horizontal and vertical padding */
  noPadding?: boolean;
};

export default function ScreenContainer({ children, style, contentStyle, noPadding }: Props) {
  const { contentHorizontalPadding, sectionVerticalSpacing } = useBreakpoint();
  const { theme } = useTheme();

  const baseInnerStyle: ViewStyle = {
    flex: 1,
    justifyContent: 'space-between',
  };

  const horizontalPadding = noPadding ? 0 : contentHorizontalPadding;

  const paddedStyle: ViewStyle = {
    ...baseInnerStyle,
    paddingHorizontal: horizontalPadding,
    paddingVertical: sectionVerticalSpacing,
  };

  const containerStyle = {
    flex: 1,
    backgroundColor: theme.background,
  };

  return (
    <SafeAreaView style={[containerStyle, style]}>
      <View style={[paddedStyle, contentStyle]}>{children}</View>
    </SafeAreaView>
  );
}
