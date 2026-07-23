/**
 * MessageBubble
 *
 * Single chat message bubble for the Agent Chat UI.
 * - User messages: right-aligned with primary background
 * - Assistant messages: left-aligned with surface background
 * - Tool calls rendered below the answer text as a collapsible accordion
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

/**
 * Render the small Markdown subset the agent uses in prose without adding a
 * heavyweight renderer to the mobile bundle.  Text remains selectable and
 * wraps exactly like a regular React Native Text node.
 */
function MarkdownText({ text, style }: { text: string; style: object }) {
  const parts = text.split(/(\*\*[^*]+\*\*|__[^_]+__)/g);
  return (
    <Text style={style}>
      {parts.map((part, index) => {
        const isBold =
          (part.startsWith('**') && part.endsWith('**')) ||
          (part.startsWith('__') && part.endsWith('__'));
        return isBold ? (
          <Text key={index} style={styles.boldText}>
            {part.slice(2, -2)}
          </Text>
        ) : (
          part
        );
      })}
    </Text>
  );
}

export default function MessageBubble({ message }: MessageBubbleProps) {
  const { theme } = useTheme();
  const isUser = message.role === 'user';
  const hasTools = !isUser && (message.toolResults?.length ?? 0) > 0;

  return (
    <View style={[styles.container, isUser ? styles.userContainer : styles.assistantContainer]}>
      {/* Answer text */}
      <View
        style={[
          styles.bubble,
          isUser
            ? [styles.userBubble, { backgroundColor: theme.primary }]
            : [styles.assistantBubble, { backgroundColor: theme.surface }],
        ]}
      >
        {!isUser && message.reasoning ? (
          <View style={[styles.reasoning, { borderBottomColor: theme.border }]}>
            <Text style={[styles.reasoningLabel, { color: theme.textSecondary }]}>Thinking</Text>
            <MarkdownText
              text={message.reasoning}
              style={[styles.reasoningText, { color: theme.textSecondary }]}
            />
          </View>
        ) : null}
        <MarkdownText
          text={message.content}
          style={[styles.bubbleText, { color: isUser ? brandColors.white : theme.text }]}
        />
      </View>

      {/* Tool/thinking section — below answer */}
      {hasTools && (
        <View style={[styles.toolSection, { backgroundColor: theme.surface }]}>
          <ToolResultsAccordion results={message.toolResults!} />
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
  boldText: {
    fontWeight: '700',
  },
  reasoning: {
    borderBottomWidth: StyleSheet.hairlineWidth,
    marginBottom: spacing.sm,
    paddingBottom: spacing.sm,
  },
  reasoningLabel: {
    ...typography.captionStrong,
    fontSize: 11,
    marginBottom: 2,
  },
  reasoningText: {
    ...typography.caption,
    fontStyle: 'italic',
    lineHeight: 18,
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
});
