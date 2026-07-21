/**
 * MessageBubble
 *
 * Single chat message bubble for the Agent Chat UI.
 * - User messages: right-aligned with primary background
 * - Assistant messages: left-aligned with surface background
 * - Shows tool indicators inline below assistant messages
 */

import React from 'react';
import { View, Text, StyleSheet } from 'react-native';
import { useTheme, brandColors } from '../../contexts/ThemeContext';
import { spacing, radii, typography } from '../../styles/theme';
import type { AgentMessage } from '../../services/agent';

interface MessageBubbleProps {
  message: AgentMessage;
}

export default function MessageBubble({ message }: MessageBubbleProps) {
  const { theme } = useTheme();
  const isUser = message.role === 'user';

  return (
    <View style={[styles.container, isUser ? styles.userContainer : styles.assistantContainer]}>
      <View
        style={[
          styles.bubble,
          isUser
            ? [styles.userBubble, { backgroundColor: theme.primary }]
            : [styles.assistantBubble, { backgroundColor: theme.surface }],
        ]}
      >
        <Text style={[styles.bubbleText, { color: isUser ? brandColors.white : theme.text }]}>
          {message.content}
        </Text>
      </View>
      {message.toolCalls && message.toolCalls.length > 0 && (
        <View style={styles.toolsRow}>
          {message.toolCalls.map((tool, idx) => (
            <Text
              key={idx}
              style={[styles.toolLabel, { color: theme.textSecondary }]}
              numberOfLines={1}
            >
              🔧 {typeof tool === 'string' ? tool : (tool.name ?? 'tool')}
            </Text>
          ))}
        </View>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    marginBottom: spacing.sm,
    maxWidth: '85%',
  },
  userContainer: {
    alignSelf: 'flex-end',
  },
  assistantContainer: {
    alignSelf: 'flex-start',
  },
  bubble: {
    borderRadius: radii.lg,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
  },
  userBubble: {
    borderBottomRightRadius: radii.sm,
  },
  assistantBubble: {
    borderBottomLeftRadius: radii.sm,
  },
  bubbleText: {
    ...typography.body,
    lineHeight: 22,
  },
  toolsRow: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: spacing.xs,
    marginTop: spacing.xs,
    paddingHorizontal: spacing.xs,
  },
  toolLabel: {
    ...typography.caption,
    fontSize: 11,
  },
});
