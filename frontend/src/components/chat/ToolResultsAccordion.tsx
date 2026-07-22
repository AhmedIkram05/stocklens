/**
 * ToolResultsAccordion
 *
 * Tap-to-expand accordion that displays agent tool results.
 * Shows tool name + expand/collapse chevron in the header.
 * Body is rendered by ToolResultRenderer.
 *
 * Multiple results are stacked vertically — each is independently expandable.
 */

import React, { useState, useCallback } from 'react';
import { View, Text, StyleSheet, TouchableOpacity, ScrollView } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { useTheme } from '../../contexts/ThemeContext';
import { spacing, radii, typography } from '../../styles/theme';
import { renderToolResult } from './ToolResultRenderer';

export interface ToolResultEntry {
  toolName: string;
  result: any;
}

interface ToolResultsAccordionProps {
  results: ToolResultEntry[];
}

export default function ToolResultsAccordion({ results }: ToolResultsAccordionProps) {
  const { theme } = useTheme();
  const [expandedIndex, setExpandedIndex] = useState<number | null>(null);

  const toggle = useCallback((idx: number) => {
    setExpandedIndex((prev) => (prev === idx ? null : idx));
  }, []);

  if (!results || results.length === 0) return null;

  return (
    <View style={styles.container}>
      {results.map((entry, idx) => {
        const isExpanded = expandedIndex === idx;
        return (
          <View
            key={`${entry.toolName}-${idx}`}
            style={[
              styles.accordionItem,
              {
                backgroundColor: theme.background,
                borderColor: theme.border,
              },
              idx === 0 && styles.firstItem,
              idx === results.length - 1 && styles.lastItem,
            ]}
          >
            <TouchableOpacity
              style={styles.header}
              onPress={() => toggle(idx)}
              activeOpacity={0.7}
              hitSlop={{ top: 4, bottom: 4, left: 4, right: 4 }}
            >
              <View style={styles.headerLeft}>
                <Ionicons name="code-slash-outline" size={14} color={theme.textSecondary} />
                <Text style={[styles.toolName, { color: theme.textSecondary }]} numberOfLines={1}>
                  {entry.toolName}
                </Text>
              </View>
              <Ionicons
                name={isExpanded ? 'chevron-up' : 'chevron-down'}
                size={16}
                color={theme.textSecondary}
              />
            </TouchableOpacity>

            {isExpanded && (
              <View style={[styles.body, { borderTopColor: theme.border }]}>
                <ScrollView nestedScrollEnabled showsVerticalScrollIndicator>
                  {renderToolResult(entry.toolName, entry.result)}
                </ScrollView>
              </View>
            )}
          </View>
        );
      })}
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    marginTop: spacing.sm,
    gap: 1,
  },
  accordionItem: {
    borderRadius: radii.sm,
    borderWidth: StyleSheet.hairlineWidth,
    overflow: 'hidden',
  },
  firstItem: {
    borderBottomLeftRadius: 0,
    borderBottomRightRadius: 0,
  },
  lastItem: {
    borderTopLeftRadius: 0,
    borderTopRightRadius: 0,
  },
  header: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingHorizontal: spacing.sm,
    paddingVertical: spacing.xs + 2,
  },
  headerLeft: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.xs,
    flex: 1,
  },
  toolName: {
    ...typography.caption,
    fontSize: 11,
    flex: 1,
  },
  body: {
    borderTopWidth: StyleSheet.hairlineWidth,
    maxHeight: 260,
  },
});
