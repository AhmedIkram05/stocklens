/**
 * MessageBubble
 *
 * Single chat message bubble for the Agent Chat UI.
 * - User messages: right-aligned with primary background
 * - Assistant messages: left-aligned with surface background
 * - Tool calls (thinking/pre-answer) rendered ABOVE the answer text
 * - Answer text below
 */

import React from 'react';
import { View, Text, StyleSheet } from 'react-native';
import { useTheme, brandColors } from '../../contexts/ThemeContext';
import { spacing, radii, typography } from '../../styles/theme';
import type { AgentMessage } from '../../services/agent';
import ToolResultsAccordion from './ToolResultsAccordion';

interface MessageBubbleProps {
  message: AgentMessage;
}

export default function MessageBubble({ message }: MessageBubbleProps) {
  const { theme } = useTheme();
  const isUser = message.role === 'user';
  const hasTools = !isUser && (message.toolResults?.length ?? 0) > 0;

  return (
    <View style={[styles.container, isUser ? styles.userContainer : styles.assistantContainer]}>
      {/* Tool/thinking section — above answer */}
      {hasTools && (
        <View style={[styles.toolSection, { backgroundColor: theme.surface }]}>
          <Text style={[styles.toolSectionLabel, { color: theme.textSecondary }]}>Steps taken</Text>
          <ToolResultsAccordion results={message.toolResults!} />
        </View>
      )}

      {/* Answer text */}
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
  toolSection: {
    borderRadius: radii.md,
    paddingHorizontal: spacing.sm,
    paddingTop: spacing.sm,
    paddingBottom: spacing.xs,
    marginBottom: spacing.xs,
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: '#333',
  },
  toolSectionLabel: {
    ...typography.caption,
    fontSize: 11,
    marginBottom: spacing.xs,
    opacity: 0.6,
  },
});
