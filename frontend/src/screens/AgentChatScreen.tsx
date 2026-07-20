/**
 * AgentChatScreen
 *
 * Chat modal for the LangGraph ReAct Finance Agent.
 * Renders as a <Modal> on the Portfolio screen.
 *
 * Features:
 * - SSE streaming via agentService.sendMessage()
 * - FlatList of MessageBubble components, auto-scrolls to bottom
 * - Tool indicators during tool execution
 * - TextInput + Send button at bottom
 * - Empty state when no messages
 */

import React, { useState, useRef, useCallback } from 'react';
import {
  View,
  Text,
  TextInput,
  FlatList,
  StyleSheet,
  Modal,
  TouchableOpacity,
  ActivityIndicator,
  KeyboardAvoidingView,
  Platform,
} from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { useTheme, brandColors } from '../contexts/ThemeContext';
import { spacing, radii, typography } from '../styles/theme';
import { agentService, type AgentMessage } from '../services/agent';
import MessageBubble from '../components/chat/MessageBubble';
import ToolIndicator from '../components/chat/ToolIndicator';

interface AgentChatScreenProps {
  visible: boolean;
  onClose: () => void;
}

export default function AgentChatScreen({ visible, onClose }: AgentChatScreenProps) {
  const { theme } = useTheme();
  const insets = useSafeAreaInsets();

  const [messages, setMessages] = useState<AgentMessage[]>([]);
  const [input, setInput] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [currentTool, setCurrentTool] = useState<string | null>(null);
  const [conversationId, setConversationId] = useState<string | undefined>();
  const [traceId, setTraceId] = useState<string>('');
  const [feedbackSubmitted, setFeedbackSubmitted] = useState(false);
  const [submittingFeedback, setSubmittingFeedback] = useState(false);
  const flatListRef = useRef<FlatList>(null);

  const handleSend = useCallback(async () => {
    const text = input.trim();
    if (!text || isLoading) return;

    // Reset feedback state for the new response
    setTraceId('');
    setFeedbackSubmitted(false);
    setInput('');
    setIsLoading(true);

    // Add user message immediately
    const userMessage: AgentMessage = {
      role: 'user',
      content: text,
      createdAt: new Date().toISOString(),
    };
    setMessages((prev) => [...prev, userMessage]);

    // Create placeholder assistant message
    const assistantMessage: AgentMessage = {
      role: 'assistant',
      content: '',
      createdAt: new Date().toISOString(),
    };
    setMessages((prev) => [...prev, assistantMessage]);

    try {
      const result = await agentService.sendMessage(
        text,
        conversationId,
        // onToken
        (token: string) => {
          setMessages((prev) => {
            const updated = [...prev];
            const lastIdx = updated.length - 1;
            if (lastIdx >= 0 && updated[lastIdx].role === 'assistant') {
              updated[lastIdx] = {
                ...updated[lastIdx],
                content: updated[lastIdx].content + token,
              };
            }
            return updated;
          });
        },
        // onToolStart
        (toolName: string) => {
          setCurrentTool(toolName);
        },
        // onToolEnd
        (_toolName: string) => {
          setCurrentTool(null);
        },
      );

      setConversationId(result.conversationId);
      if (result.traceId) {
        setTraceId(result.traceId);
      }
    } catch (err) {
      // Mark the assistant message with an error
      setMessages((prev) => {
        const updated = [...prev];
        const lastIdx = updated.length - 1;
        if (lastIdx >= 0 && updated[lastIdx].role === 'assistant') {
          updated[lastIdx] = {
            ...updated[lastIdx],
            content: 'Sorry, something went wrong. Please try again.',
          };
        }
        return updated;
      });
    } finally {
      setIsLoading(false);
      setCurrentTool(null);
    }
  }, [input, isLoading, conversationId]);

  const handleFeedback = useCallback(
    async (rating: 'positive' | 'negative') => {
      if (!traceId || submittingFeedback || feedbackSubmitted) return;
      setSubmittingFeedback(true);
      try {
        await agentService.submitFeedback(rating, traceId);
        setFeedbackSubmitted(true);
      } catch {
        // Silently fail — feedback is non-critical
      } finally {
        setSubmittingFeedback(false);
      }
    },
    [traceId, submittingFeedback, feedbackSubmitted],
  );

  const renderMessage = useCallback(
    ({ item }: { item: AgentMessage }) => <MessageBubble message={item} />,
    [],
  );

  const keyExtractor = useCallback((_item: AgentMessage, index: number) => String(index), []);

  const renderEmptyState = () => (
    <View style={styles.emptyState}>
      <Ionicons name="warning" size={64} color={brandColors.red} />
      <Text style={[styles.disclaimerTitle, { color: theme.text }]}>AI Assistant Disclaimer</Text>
      <Text style={[styles.disclaimerBody, { color: theme.textSecondary }]}>
        This is not financial advice. AI can hallucinate and make mistakes.
        {'\n'}Always do your own research before making investment decisions.
      </Text>
      <View style={styles.disclaimerDivider} />
      <Ionicons name="chatbubbles-outline" size={28} color={theme.textSecondary} />
      <Text style={[styles.emptyTitle, { color: theme.textSecondary }]}>
        Ask me anything about your portfolio...
      </Text>
    </View>
  );

  return (
    <Modal visible={visible} transparent animationType="fade" onRequestClose={onClose}>
      <View style={[styles.overlay, { backgroundColor: theme.background + 'CC' }]}>
        <KeyboardAvoidingView
          behavior={Platform.OS === 'ios' ? 'padding' : undefined}
          style={styles.keyboardView}
        >
          <View
            style={[
              styles.card,
              {
                backgroundColor: theme.background,
                marginTop: insets.top,
                marginBottom: insets.bottom,
              },
            ]}
          >
            {/* Header */}
            <View style={[styles.header, { borderBottomColor: theme.border }]}>
              <Text style={[styles.title, { color: theme.text }]}>AI Assistant</Text>
              <TouchableOpacity
                onPress={onClose}
                hitSlop={{ top: 8, bottom: 8, left: 8, right: 8 }}
              >
                <Ionicons name="close" size={24} color={theme.text} />
              </TouchableOpacity>
            </View>

            {/* Messages */}
            <FlatList
              ref={flatListRef}
              data={messages}
              keyExtractor={keyExtractor}
              renderItem={renderMessage}
              contentContainerStyle={[
                styles.messageList,
                messages.length === 0 && styles.messageListEmpty,
              ]}
              ListEmptyComponent={renderEmptyState}
              onContentSizeChange={() => flatListRef.current?.scrollToEnd({ animated: true })}
            />

            {/* Feedback row — shown after streaming completes, before next message */}
            {traceId && !isLoading && !feedbackSubmitted && messages.length > 0 && (
              <View style={styles.feedbackRow}>
                <Text style={[styles.feedbackLabel, { color: theme.textSecondary }]}>
                  Was this helpful?
                </Text>
                <View style={styles.feedbackBtns}>
                  <TouchableOpacity
                    style={[styles.feedbackBtn, { borderColor: theme.border }]}
                    onPress={() => handleFeedback('positive')}
                    disabled={submittingFeedback}
                    hitSlop={{ top: 8, bottom: 8, left: 8, right: 8 }}
                  >
                    <Ionicons name="thumbs-up-outline" size={18} color={theme.text} />
                  </TouchableOpacity>
                  <TouchableOpacity
                    style={[styles.feedbackBtn, { borderColor: theme.border }]}
                    onPress={() => handleFeedback('negative')}
                    disabled={submittingFeedback}
                    hitSlop={{ top: 8, bottom: 8, left: 8, right: 8 }}
                  >
                    <Ionicons name="thumbs-down-outline" size={18} color={theme.text} />
                  </TouchableOpacity>
                </View>
              </View>
            )}
            {feedbackSubmitted && (
              <Text style={[styles.feedbackThanks, { color: theme.textSecondary }]}>
                Thanks for your feedback!
              </Text>
            )}

            {/* Tool indicator */}
            <ToolIndicator toolName={currentTool} />

            {/* Input bar */}
            <View style={[styles.inputBar, { borderTopColor: theme.border }]}>
              <TextInput
                style={[
                  styles.input,
                  {
                    backgroundColor: theme.surface,
                    color: theme.text,
                    borderColor: theme.border,
                  },
                ]}
                placeholder="Ask about your portfolio..."
                placeholderTextColor={theme.textSecondary}
                value={input}
                onChangeText={setInput}
                multiline
                maxLength={2000}
                editable={!isLoading}
                returnKeyType="send"
                onSubmitEditing={handleSend}
              />
              <TouchableOpacity
                style={[
                  styles.sendBtn,
                  {
                    backgroundColor: isLoading ? theme.textSecondary : theme.primary,
                  },
                ]}
                onPress={handleSend}
                disabled={isLoading || !input.trim()}
                hitSlop={{ top: 4, bottom: 4, left: 4, right: 4 }}
              >
                {isLoading ? (
                  <ActivityIndicator size="small" color={brandColors.white} />
                ) : (
                  <Ionicons name="send" size={18} color={brandColors.white} />
                )}
              </TouchableOpacity>
            </View>
          </View>
        </KeyboardAvoidingView>
      </View>
    </Modal>
  );
}

const styles = StyleSheet.create({
  overlay: {
    flex: 1,
    justifyContent: 'flex-end',
  },
  keyboardView: {
    flex: 1,
    justifyContent: 'flex-end',
  },
  card: {
    flex: 1,
    borderTopLeftRadius: radii.xl,
    borderTopRightRadius: radii.xl,
  },
  header: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    paddingHorizontal: spacing.lg,
    paddingVertical: spacing.md,
    borderBottomWidth: StyleSheet.hairlineWidth,
  },
  title: {
    ...typography.sectionTitle,
  },
  messageList: {
    flexGrow: 1,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
  },
  messageListEmpty: {
    flex: 1,
    justifyContent: 'center',
  },
  emptyState: {
    alignItems: 'center',
    gap: spacing.md,
    paddingHorizontal: spacing.xl,
  },
  disclaimerTitle: {
    ...typography.sectionTitle,
    textAlign: 'center',
  },
  disclaimerBody: {
    ...typography.caption,
    textAlign: 'center',
    lineHeight: 20,
  },
  disclaimerDivider: {
    width: 40,
    height: StyleSheet.hairlineWidth,
    backgroundColor: '#888',
    opacity: 0.3,
    marginVertical: spacing.sm,
  },
  emptyTitle: {
    ...typography.body,
    textAlign: 'center',
  },
  inputBar: {
    flexDirection: 'row',
    alignItems: 'flex-end',
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
    borderTopWidth: StyleSheet.hairlineWidth,
    gap: spacing.sm,
  },
  feedbackRow: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: spacing.md,
    paddingVertical: spacing.sm,
    paddingHorizontal: spacing.md,
  },
  feedbackLabel: {
    fontSize: 13,
  },
  feedbackBtns: {
    flexDirection: 'row',
    gap: spacing.sm,
  },
  feedbackBtn: {
    width: 32,
    height: 32,
    borderRadius: 16,
    borderWidth: 1,
    justifyContent: 'center',
    alignItems: 'center',
  },
  feedbackThanks: {
    fontSize: 13,
    textAlign: 'center',
    paddingVertical: spacing.sm,
  },
  input: {
    flex: 1,
    ...typography.body,
    borderRadius: radii.lg,
    borderWidth: 1,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
    maxHeight: 120,
  },
  sendBtn: {
    width: 40,
    height: 40,
    borderRadius: 20,
    justifyContent: 'center',
    alignItems: 'center',
  },
});
