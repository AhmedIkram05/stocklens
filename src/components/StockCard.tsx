/**
 * StockCard
 *
 * Investment projection card showing name, future value and returns.
 */

import React from 'react';
import { View, StyleSheet, TouchableOpacity } from 'react-native';
import AppText from './AppText';
import { LinearGradient } from 'expo-linear-gradient';
import { brandColors } from '../contexts/ThemeContext';
import { radii, spacing, typography, shadows } from '../styles/theme';
import { useBreakpoint } from '../hooks/useBreakpoint';
import { useTheme } from '../contexts/ThemeContext';

type Props = {
  /** Stock/investment name (e.g., "Apple Inc.", "S&P 500 Index") */
  name: string;
  /** Optional ticker symbol (e.g., "AAPL", "SPY") */
  ticker?: string;
  /** Formatted future value projection (e.g., "$1,234.56") */
  futureDisplay: string;
  /** Original investment amount formatted (e.g., "$1,000.00") */
  formattedAmount: string;
  /** Return percentage formatted (e.g., "+23.5%", "-5.2%") */
  percentDisplay: string;
  /** Gained/lost amount formatted (e.g., "+$234.56") */
  gainDisplay: string;
  /** Color for value/gain text (typically green for positive, red for negative) */
  valueColor?: string;
  /** Callback triggered when the card is pressed */
  onPress?: () => void;
  /** When true, removes right margin (for last card in horizontal scroll) */
  isLast?: boolean;
  /** Optional fixed width for the card (overrides responsive width calculation) */
  cardWidth?: number;
  /** Optional badge text displayed at top-right (e.g., "Popular") */
  badgeText?: string;
  /** Optional badge background color (defaults to theme.primary) */
  badgeColor?: string;
};

export default function StockCard({
  name,
  ticker,
  futureDisplay,
  formattedAmount: _formattedAmount,
  percentDisplay,
  gainDisplay,
  valueColor = brandColors.green,
  onPress,
  isLast,
  cardWidth,
  badgeText,
  badgeColor,
}: Props) {
  const { isTablet, width } = useBreakpoint();
  const { theme } = useTheme();
  const pixelWidth = cardWidth ?? Math.max(200, Math.round(isTablet ? width * 0.4 : width * 0.82));

  return (
    <TouchableOpacity
      onPress={onPress}
      activeOpacity={0.9}
      style={[
        styles.card,
        { width: pixelWidth, backgroundColor: theme.surface },
        isLast && styles.cardLast,
      ]}
    >
      {badgeText ? (
        <View style={styles.badgeContainer}>
          <LinearGradient
            colors={[badgeColor ?? theme.primary, badgeColor ?? theme.primary]}
            start={{ x: 0, y: 0 }}
            end={{ x: 1, y: 1 }}
            style={styles.badge}
          >
            <AppText style={styles.badgeText}>{badgeText}</AppText>
          </LinearGradient>
        </View>
      ) : null}
      <View style={styles.headerRow}>
        <View style={styles.headerLeft}>
          <AppText
            style={[styles.name, { color: theme.text }]}
            numberOfLines={1}
            ellipsizeMode="tail"
          >
            {name}
          </AppText>
        </View>
        {ticker ? (
          <AppText style={[styles.ticker, { color: brandColors.blue }]}>{ticker}</AppText>
        ) : null}
      </View>

      <View style={styles.valueContainerCentered}>
        <AppText style={[styles.value, { color: theme.text }]}>{futureDisplay}</AppText>
      </View>

      <View style={styles.dividerHorizontal} />

      <View style={styles.footer}>
        <View style={styles.footerItem}>
          <AppText style={[styles.footerLabel, { color: theme.textSecondary }]}>Return</AppText>
          <AppText style={[styles.footerValue, { color: valueColor }]}>{percentDisplay}</AppText>
        </View>

        <View style={styles.dividerVertical} />

        <View style={styles.footerItem}>
          <AppText style={[styles.footerLabel, { color: theme.textSecondary }]}>Gained</AppText>
          <AppText style={[styles.footerValue, { color: valueColor }]}>{gainDisplay}</AppText>
        </View>
      </View>
    </TouchableOpacity>
  );
}

const styles = StyleSheet.create<any>({
  card: {
    position: 'relative',
    borderRadius: radii.lg,
    padding: spacing.lg,
    marginRight: spacing.md,
    ...shadows.level2,
    overflow: 'hidden',
  },
  cardLast: {
    marginRight: 0,
  },
  badgeContainer: {
    position: 'absolute',
    top: spacing.md,
    right: spacing.md,
    zIndex: 1,
  },
  badge: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingHorizontal: spacing.sm + 2,
    paddingVertical: spacing.xs + 2,
    borderRadius: radii.pill,
  },
  badgeText: {
    ...typography.captionStrong,
    color: brandColors.white,
    fontSize: 12,
    fontWeight: 'bold',
  },
  header: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: spacing.md,
  },
  name: {
    ...typography.bodyStrong,
  },
  valueContainer: {
    alignItems: 'flex-start',
    marginBottom: spacing.md,
  },
  value: {
    ...typography.metric,
  },
  caption: {
    ...typography.caption,
    marginTop: spacing.xs,
  },
  dividerHorizontal: {
    height: StyleSheet.hairlineWidth,
    marginBottom: spacing.md,
    backgroundColor: brandColors.black,
  },
  footer: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
  },
  footerItem: {
    flex: 1,
    alignItems: 'center',
  },
  footerLabel: {
    ...typography.overline,
    marginBottom: spacing.sm,
    textAlign: 'center',
    width: '100%',
  },
  footerValue: {
    ...typography.metricSm,
    color: brandColors.green,
  },
  dividerVertical: {
    width: StyleSheet.hairlineWidth,
    marginHorizontal: spacing.md,
    alignSelf: 'stretch',
    backgroundColor: brandColors.black,
  },
  headerRow: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    marginBottom: spacing.sm,
  },
  headerLeft: {
    flex: 1,
    paddingRight: spacing.sm,
  },
  ticker: {
    ...typography.captionStrong,
    color: brandColors.blue,
  },
  valueContainerCentered: {
    alignItems: 'center',
    marginBottom: spacing.md,
  },
});
