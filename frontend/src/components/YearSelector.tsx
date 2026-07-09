/**
 * YearSelector
 *
 * Animated segmented control for selecting time periods (1M, 3M, 6M, 1Y, 3Y, 5Y, 10Y, 20Y, YTD).
 */

import React, { useRef, useEffect, useState, Dispatch, SetStateAction } from 'react';
import { View, TouchableOpacity, Animated, ViewStyle, StyleProp } from 'react-native';
import AppText from './AppText';
import { spacing, typography, radii } from '../styles/theme';
import { brandColors, useTheme } from '../contexts/ThemeContext';

type Props = {
  /** Array of period labels (e.g., ['1M', '3M', '6M', '1Y', '3Y', '5Y', '10Y', '20Y', 'YTD']) */
  options: string[];
  /** Currently selected period label */
  value: string;
  /** Callback or setState function triggered when selection changes */
  onChange: ((v: string) => void) | Dispatch<SetStateAction<string>>;
  /** When true, uses smaller padding and sizing */
  compact?: boolean;
  /** Optional custom styling for the container */
  style?: StyleProp<ViewStyle>;
};

export default function YearSelector({ options, value, onChange, compact = false, style }: Props) {
  const { theme } = useTheme();
  const containerWidthRef = useRef<number>(0);
  const containerHeightRef = useRef<number>(0);
  const animatedX = useRef(new Animated.Value(0)).current;
  const [measured, setMeasured] = useState(false);

  useEffect(() => {
    if (!measured) return;
    const width = containerWidthRef.current;
    const pad = spacing.xs;
    const totalMargins = spacing.xs * options.length;
    const segmentWidth = (width - pad * 2 - totalMargins) / options.length;
    const idx = options.indexOf(value);
    if (idx < 0) return;
    const target = idx * (segmentWidth + spacing.xs) + pad;
    Animated.timing(animatedX, { toValue: target, duration: 220, useNativeDriver: true }).start();
  }, [value]);

  const pad = spacing.xs;
  const segPadVert = compact ? spacing.xs : spacing.sm;
  const width = containerWidthRef.current;
  const totalMargins = spacing.xs * options.length;
  const segmentWidth = width > 0 ? (width - pad * 2 - totalMargins) / options.length : 0;
  const height = Math.max(compact ? 28 : 32, containerHeightRef.current - pad * 2);

  return (
    <View
      style={[
        {
          flexDirection: 'row',
          borderRadius: radii.pill,
          backgroundColor: theme.surface,
          padding: pad,
          alignItems: 'center',
        },
        style,
      ]}
      onLayout={(e) => {
        const { width: w, height: h } = e.nativeEvent.layout;
        containerWidthRef.current = w;
        containerHeightRef.current = h;
        const idx = options.indexOf(value);
        if (w > 0 && idx >= 0) {
          const padInner = spacing.xs;
          const totalMarginsInner = spacing.xs * options.length;
          const segmentWidthInner = (w - padInner * 2 - totalMarginsInner) / options.length;
          const target = idx * (segmentWidthInner + spacing.xs) + padInner;
          animatedX.setValue(target);
          setMeasured(true);
        }
      }}
    >
      <Animated.View
        pointerEvents="none"
        style={{
          position: 'absolute',
          left: 0,
          top: pad,
          width: segmentWidth,
          height,
          borderRadius: radii.pill,
          backgroundColor: brandColors.green,
          shadowColor: brandColors.green,
          shadowOffset: { width: 0, height: 4 },
          shadowOpacity: 0.15,
          shadowRadius: 6,
          elevation: 2,
          transform: [{ translateX: animatedX }],
          opacity: measured ? 1 : 0,
        }}
      />

      {options.map((o) => (
        <TouchableOpacity
          key={o}
          onPress={() => onChange(o)}
          style={{
            flex: 1,
            alignItems: 'center',
            justifyContent: 'center',
            paddingVertical: segPadVert,
            marginHorizontal: spacing.xs / 2,
          }}
        >
          <AppText
            style={[
              typography.captionStrong,
              {
                color: o === value ? brandColors.white : theme.text,
                opacity: o === value ? 1 : 0.8,
              },
            ]}
          >
            {o}
          </AppText>
        </TouchableOpacity>
      ))}
    </View>
  );
}
