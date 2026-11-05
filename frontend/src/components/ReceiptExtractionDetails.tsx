/**
 * ReceiptExtractionDetails
 *
 * "Extraction Details" affordance for the OCR cascade: which extractor produced
 * the receipt (source badge), its confidence, and processing time. Presentational
 * — the caller supplies the already-derived values. Renders nothing when there
 * is no source to report.
 */

import React from 'react';
import { View, Text, StyleSheet } from 'react-native';
import type { TextStyle, ViewStyle } from 'react-native';
import { useTheme } from '../contexts/ThemeContext';
import { radii, spacing, typography } from '../styles/theme';
import type { SourceBadgeKey } from './ReceiptCard';

const SOURCE_BADGE: Record<SourceBadgeKey, { label: string; color: string }> = {
  regex: { label: 'Regex', color: '#22c55e' },
  cascade: { label: 'AI Enhanced', color: '#3b82f6' },
  degraded: { label: 'Low Quality', color: '#f97316' },
  failed: { label: 'Failed', color: '#ef4444' },
};

const FALLBACK_BADGE_COLOR = '#6b7280';

type Props = {
  /** OCR extraction source; when absent the panel is not rendered. */
  source?: SourceBadgeKey | string | null;
  /** Confidence as a whole percentage (0-100), or null when unknown. */
  confidencePct?: number | null;
  /** Cascade processing time in milliseconds. */
  processingTimeMs?: number | null;
};

export default function ReceiptExtractionDetails({
  source,
  confidencePct,
  processingTimeMs,
}: Props) {
  const { theme } = useTheme();

  if (!source) return null;

  const badge = SOURCE_BADGE[source as SourceBadgeKey];
  const badgeColor = badge?.color ?? FALLBACK_BADGE_COLOR;

  return (
    <View style={[styles.cascadePanel, { backgroundColor: theme.surface }]}>
      <Text style={[styles.cascadeTitle, { color: theme.text }]}>Extraction Details</Text>
      <View style={styles.cascadeRow}>
        <Text style={[styles.cascadeLabel, { color: theme.textSecondary }]}>Source</Text>
        <View style={[styles.sourceBadge, { backgroundColor: badgeColor + '20' }]}>
          <Text style={[styles.sourceBadgeText, { color: badgeColor }]}>
            {badge?.label || source}
          </Text>
        </View>
      </View>
      {confidencePct != null && confidencePct > 0 && (
        <View style={styles.cascadeRow}>
          <Text style={[styles.cascadeLabel, { color: theme.textSecondary }]}>Confidence</Text>
          <View style={styles.confidenceContainer}>
            <View style={styles.confidenceBarBg}>
              <View
                style={[
                  styles.confidenceBarFill,
                  {
                    width: `${confidencePct}%`,
                    backgroundColor:
                      confidencePct > 70 ? '#22c55e' : confidencePct > 40 ? '#f97316' : '#ef4444',
                  },
                ]}
              />
            </View>
            <Text style={[styles.confidenceText, { color: theme.text }]}>{confidencePct}%</Text>
          </View>
        </View>
      )}
      {processingTimeMs != null && processingTimeMs > 0 && (
        <View style={styles.cascadeRow}>
          <Text style={[styles.cascadeLabel, { color: theme.textSecondary }]}>Processing Time</Text>
          <Text style={[styles.cascadeValue, { color: theme.text }]}>
            {processingTimeMs < 1000
              ? `${Math.round(processingTimeMs)}ms`
              : `${(processingTimeMs / 1000).toFixed(1)}s`}
          </Text>
        </View>
      )}
    </View>
  );
}

type Styles = {
  cascadePanel: ViewStyle;
  cascadeTitle: TextStyle;
  cascadeRow: ViewStyle;
  cascadeLabel: TextStyle;
  cascadeValue: TextStyle;
  sourceBadge: ViewStyle;
  sourceBadgeText: TextStyle;
  confidenceContainer: ViewStyle;
  confidenceBarBg: ViewStyle;
  confidenceBarFill: ViewStyle;
  confidenceText: TextStyle;
};

const styles = StyleSheet.create<Styles>({
  cascadePanel: {
    borderRadius: radii.md,
    padding: spacing.md,
    marginTop: spacing.md,
  },
  cascadeTitle: {
    ...typography.sectionTitle,
    marginBottom: spacing.md,
  },
  cascadeRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    paddingVertical: spacing.sm,
  },
  cascadeLabel: {
    ...typography.body,
  },
  cascadeValue: {
    ...typography.bodyStrong,
  },
  sourceBadge: {
    paddingHorizontal: spacing.sm,
    paddingVertical: 2,
    borderRadius: radii.sm,
  },
  sourceBadgeText: {
    fontSize: 11,
    fontWeight: '600',
    textTransform: 'uppercase',
    letterSpacing: 0.5,
  },
  confidenceContainer: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
  },
  confidenceBarBg: {
    width: 80,
    height: 6,
    borderRadius: 3,
    backgroundColor: '#e5e7eb',
    overflow: 'hidden',
  },
  confidenceBarFill: {
    height: '100%',
    borderRadius: 3,
  },
  confidenceText: {
    ...typography.bodyStrong,
    minWidth: 35,
    textAlign: 'right',
  },
});
