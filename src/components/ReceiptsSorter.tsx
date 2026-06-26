/**
 * ReceiptsSorter
 *
 * Sorting control for receipts (Date / Amount) with direction toggles.
 */

import React from 'react';
import { View, StyleSheet, TouchableOpacity } from 'react-native';
import AppText from './AppText';
import { useTheme } from '../contexts/ThemeContext';
import { brandColors } from '../contexts/ThemeContext';
import { radii, spacing, typography } from '../styles/theme';

export type SortBy = 'date' | 'amount';
export type SortDirection = 'asc' | 'desc';

interface ReceiptsSorterProps {
  /** Currently active sort field */
  sortBy: SortBy;
  /** Current sort direction (ascending or descending) */
  sortDirection: SortDirection;
  /** Callback triggered when sort changes with new sortBy and sortDirection */
  onSortChange: (sortBy: SortBy, sortDirection: SortDirection) => void;
}

const sortOptions: { key: SortBy; label: string }[] = [
  { key: 'date', label: 'Date' },
  { key: 'amount', label: 'Amount' },
];

export default function ReceiptsSorter({
  sortBy,
  sortDirection,
  onSortChange,
}: ReceiptsSorterProps) {
  const { theme } = useTheme();

  const handleSortByChange = (newSortBy: SortBy) => {
    if (newSortBy === sortBy) {
      const newDirection = sortDirection === 'asc' ? 'desc' : 'asc';
      onSortChange(newSortBy, newDirection);
    } else {
      const defaultDirection = newSortBy === 'date' ? 'desc' : 'asc';
      onSortChange(newSortBy, defaultDirection);
    }
  };

  return (
    <View style={styles.container}>
      <AppText style={[styles.label, { color: theme.textSecondary }]}>Sort by:</AppText>
      <View style={styles.optionsContainer}>
        {sortOptions.map((option) => (
          <TouchableOpacity
            key={option.key}
            style={[
              styles.optionButton,
              sortBy === option.key && styles.optionButtonActive,
              { borderColor: theme.border },
            ]}
            onPress={() => handleSortByChange(option.key)}
          >
            <AppText
              style={[
                styles.optionText,
                { color: sortBy === option.key ? brandColors.white : theme.text },
              ]}
            >
              {option.label}
            </AppText>
            {sortBy === option.key && (
              <AppText style={[styles.directionText, { color: brandColors.white }]}>
                {sortDirection === 'asc' ? '↑' : '↓'}
              </AppText>
            )}
          </TouchableOpacity>
        ))}
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flexDirection: 'row',
    alignItems: 'center',
    marginBottom: spacing.md,
    flexWrap: 'wrap',
  },
  label: {
    ...typography.caption,
    marginRight: spacing.sm,
  },
  optionsContainer: {
    flexDirection: 'row',
    flexWrap: 'wrap',
  },
  optionButton: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingVertical: spacing.xs,
    paddingHorizontal: spacing.sm,
    borderRadius: radii.md,
    borderWidth: 1,
    marginRight: spacing.xs,
    marginBottom: spacing.xs,
    backgroundColor: 'transparent',
  },
  optionButtonActive: {
    backgroundColor: brandColors.green,
    borderColor: brandColors.green,
  },
  optionText: {
    ...typography.bodyStrong,
  },
  directionText: {
    ...typography.bodyStrong,
    marginLeft: spacing.xs,
  },
});
