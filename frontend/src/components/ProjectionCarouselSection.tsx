/**
 * ProjectionCarouselSection
 *
 * Titled projection block: header, period selector and stock carousel.
 * Presentational — data, period state and card rendering are owned by the caller.
 */

import React from 'react';
import { View, Text, StyleSheet } from 'react-native';
import PageHeader from './PageHeader';
import YearSelector from './YearSelector';
import Carousel from './Carousel';
import { useTheme } from '../contexts/ThemeContext';
import { spacing, typography } from '../styles/theme';
import { PERIOD_OPTIONS } from '../constants/periods';

type Props = {
  /** Section title (e.g. "Your £250.00 could have been...") */
  title: string;
  /** Section subtitle (e.g. "If invested 5 years ago") */
  subtitle: string;
  /** Currently selected period label */
  periodValue: string;
  /** Called when the period selection changes */
  onPeriodChange: (value: string) => void;
  /** Small-screen layout flag for the period selector and spacing */
  compact: boolean;
  /** Carousel header title */
  carouselTitle: string;
  /** Carousel header subtitle */
  carouselSubtitle: string;
  /** Carousel data */
  data: any[];
  /** Key extractor for carousel items */
  keyExtractor: (item: any) => string;
  /** Carousel item renderer */
  renderItem: (info: { item: any; index: number }) => React.ReactElement | null;
  /** Snap interval passed to the carousel */
  snapInterval: number;
};

export default function ProjectionCarouselSection({
  title,
  subtitle,
  periodValue,
  onPeriodChange,
  compact,
  carouselTitle,
  carouselSubtitle,
  data,
  keyExtractor,
  renderItem,
  snapInterval,
}: Props) {
  const { theme } = useTheme();

  return (
    <>
      <PageHeader>
        <View>
          <Text style={[styles.projectionTitle, { color: theme.text }]}>{title}</Text>
        </View>
        <Text style={[styles.projectionSubtitle, { color: theme.textSecondary }]}>{subtitle}</Text>
      </PageHeader>

      <YearSelector
        options={[...PERIOD_OPTIONS]}
        value={periodValue}
        onChange={onPeriodChange}
        compact={compact}
        style={{ marginBottom: compact ? spacing.xl : spacing.xl + spacing.sm }}
      />

      <View style={styles.carouselHeader}>
        <Text style={[styles.carouselTitle, { color: theme.text }]}>{carouselTitle}</Text>
        <Text style={[styles.carouselSubtitle, { color: theme.textSecondary }]}>
          {carouselSubtitle}
        </Text>
      </View>

      <Carousel
        data={data}
        keyExtractor={keyExtractor}
        snapInterval={snapInterval}
        contentContainerStyle={styles.carousel}
        renderItem={renderItem}
      />
    </>
  );
}

const styles = StyleSheet.create({
  projectionTitle: {
    ...typography.sectionTitle,
    marginBottom: spacing.sm,
  },
  projectionSubtitle: {
    ...typography.body,
    opacity: 0.7,
  },
  carouselHeader: {
    marginBottom: spacing.md,
  },
  carouselTitle: {
    ...typography.bodyStrong,
  },
  carouselSubtitle: {
    ...typography.caption,
    marginTop: spacing.xs,
  },
  carousel: {
    paddingBottom: spacing.md,
  },
});
