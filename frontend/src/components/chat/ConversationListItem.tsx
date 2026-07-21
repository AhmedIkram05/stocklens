/**
 * ConversationListItem
 *
 * A single row in the conversation history list.
 * Shows title, message count, relative timestamp.
 * Swipe-left reveals a delete button.
 */

import React from 'react';
import { View, Text, TouchableOpacity, StyleSheet } from 'react-native';
import { Swipeable } from 'react-native-gesture-handler';
import { Ionicons } from '@expo/vector-icons';

import { useTheme, brandColors } from '../../contexts/ThemeContext';
import { spacing, typography } from '../../styles/theme';
import { formatRelativeDate } from '../../utils/formatters';
import type { ConversationSummary } from '../../services/agent';

interface ConversationListItemProps {
  conversation: ConversationSummary;
  onPress: () => void;
  onDelete: () => void;
}

export default function ConversationListItem({
  conversation,
  onPress,
  onDelete,
}: ConversationListItemProps) {
  const { theme } = useTheme();

  const renderRightActions = () => (
    <TouchableOpacity
      style={styles.deleteAction}
      onPress={onDelete}
      accessibilityLabel="Delete conversation"
      accessibilityRole="button"
    >
      <Ionicons name="trash-outline" size={22} color={brandColors.white} />
      <Text style={styles.deleteText}>Delete</Text>
    </TouchableOpacity>
  );

  const label = `${conversation.messageCount} message${conversation.messageCount === 1 ? '' : 's'}`;
  const title = conversation.title ?? 'New Conversation';

  return (
    <Swipeable renderRightActions={renderRightActions} overshootRight={false}>
      <TouchableOpacity
        style={[styles.container, { backgroundColor: theme.surface }]}
        onPress={onPress}
        onLongPress={onDelete}
        delayLongPress={600}
        activeOpacity={0.7}
        accessibilityLabel={title}
        accessibilityRole="button"
      >
        <View style={styles.iconWrap}>
          <Ionicons name="chatbubble-ellipses-outline" size={20} color={theme.primary} />
        </View>
        <View style={styles.content}>
          <Text style={[styles.title, { color: theme.text }]} numberOfLines={1}>
            {title}
          </Text>
          <View style={styles.meta}>
            <Text style={[styles.count, { color: theme.textSecondary }]}>{label}</Text>
            <View style={[styles.dot, { backgroundColor: theme.textSecondary }]} />
            <Text style={[styles.time, { color: theme.textSecondary }]}>
              {formatRelativeDate(conversation.updatedAt)}
            </Text>
          </View>
        </View>
        <Ionicons name="chevron-forward" size={18} color={theme.textSecondary} />
      </TouchableOpacity>
    </Swipeable>
  );
}

const styles = StyleSheet.create({
  container: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.md,
  },
  iconWrap: {
    width: 36,
    height: 36,
    borderRadius: 18,
    justifyContent: 'center',
    alignItems: 'center',
    marginRight: spacing.md,
  },
  content: {
    flex: 1,
  },
  title: {
    ...typography.bodyStrong,
    marginBottom: 2,
  },
  meta: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.xs,
  },
  count: {
    ...typography.caption,
  },
  dot: {
    width: 3,
    height: 3,
    borderRadius: 1.5,
  },
  time: {
    ...typography.caption,
  },
  deleteAction: {
    backgroundColor: brandColors.red,
    justifyContent: 'center',
    alignItems: 'center',
    width: 80,
    gap: 2,
  },
  deleteText: {
    color: brandColors.white,
    fontSize: 12,
    fontWeight: '600',
  },
});
