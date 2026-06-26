import React from 'react';
import { Text, TextProps } from 'react-native';

type Props = TextProps & {
  /** Cap the system font scaling to avoid extreme layout breakage when needed */
  maxFontSizeMultiplier?: number | null;
};

/**
 * AppText
 *
 * Small wrapper around React Native `Text` that enables consistent font-scaling.
 */
export default function AppText({
  children,
  maxFontSizeMultiplier = undefined,
  style,
  ...rest
}: Props) {
  return (
    <Text
      allowFontScaling
      maxFontSizeMultiplier={maxFontSizeMultiplier ?? undefined}
      style={style}
      {...rest}
    >
      {children}
    </Text>
  );
}
