/**
 * SectorBar
 *
 * Custom horizontal bar component for sector allocation display.
 * Renders a label, proportional filled bar, percentage, and value.
 * No charting library — pure View-based.
 */

import React from 'react';
import { View, Text, StyleSheet } from 'react-native';
import { useTheme, brandColors } from '../../contexts/ThemeContext';
import { formatCurrencyGBP } from '../../utils/formatters';

interface SectorBarProps {
  sector: string;
  allocationPct: number;
  valueGbp: number;
  maxPct: number;
  index: number;
}

const BAR_COLORS = [
  brandColors.blue,
  brandColors.green,
  brandColors.red,
  '#FF9500',
  '#AF52DE',
  '#5AC8FA',
  '#FF2D55',
  '#30D158',
  '#FFD60A',
  '#64D2FF',
];

export default function SectorBar({
  sector,
  allocationPct,
  valueGbp,
  maxPct,
  index,
}: SectorBarProps) {
  const { theme } = useTheme();
  const barColor = BAR_COLORS[index % BAR_COLORS.length];
  const barWidth = maxPct > 0 ? (allocationPct / maxPct) * 100 : 0;

  return (
    <View style={styles.container}>
      <View style={styles.header}>
        <Text style={[styles.label, { color: theme.text }]} numberOfLines={1}>
          {sector}
        </Text>
        <Text style={[styles.pct, { color: theme.text }]}>{allocationPct.toFixed(1)}%</Text>
      </View>
      <View style={[styles.track, { backgroundColor: theme.border }]}>
        <View
          style={[
            styles.bar,
            {
              width: `${barWidth}%` as any,
              backgroundColor: barColor,
            },
          ]}
        />
      </View>
      <Text style={[styles.value, { color: theme.textSecondary }]}>
        {formatCurrencyGBP(valueGbp)}
      </Text>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    marginBottom: 16,
  },
  header: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: 4,
  },
  label: {
    fontSize: 14,
    fontWeight: '600',
    flex: 1,
    marginRight: 8,
  },
  pct: {
    fontSize: 14,
    fontWeight: '700',
  },
  track: {
    height: 20,
    borderRadius: 10,
    overflow: 'hidden',
    marginBottom: 2,
  },
  bar: {
    height: '100%',
    borderRadius: 10,
    minWidth: 2,
  },
  value: {
    fontSize: 12,
  },
});
