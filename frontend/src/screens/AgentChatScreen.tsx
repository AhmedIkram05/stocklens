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
 * - History icon opens ConversationHistoryScreen
 * - Auto-title display in header
 * - Feedback comment modal with optional textarea
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
  Alert,
} from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { useTheme, brandColors } from '../contexts/ThemeContext';
import { spacing, radii, typography } from '../styles/theme';
import { agentService, type AgentMessage } from '../services/agent';
import MessageBubble from '../components/chat/MessageBubble';
import ToolIndicator from '../components/chat/ToolIndicator';
import ConversationHistoryScreen from './ConversationHistoryScreen';

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
  const [conversationTitle, setConversationTitle] = useState<string | null>(null);
  const [traceId, setTraceId] = useState<string>('');
  const [feedbackSubmitted, setFeedbackSubmitted] = useState(false);
  const [submittingFeedback, setSubmittingFeedback] = useState(false);
  const [showHistory, setShowHistory] = useState(false);
  const [showFeedbackModal, setShowFeedbackModal] = useState(false);
  const [feedbackRating, setFeedbackRating] = useState<'positive' | 'negative' | null>(null);
  const [feedbackComment, setFeedbackComment] = useState('');
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
        (_toolName: string, result?: any) => {
          setCurrentTool(null);
          if (result !== undefined) {
            setMessages((prev) => {
              const updated = [...prev];
              const lastIdx = updated.length - 1;
              if (lastIdx >= 0 && updated[lastIdx].role === 'assistant') {
                const msg = updated[lastIdx];
                updated[lastIdx] = {
                  ...msg,
                  toolResults: [...(msg.toolResults ?? []), { toolName: _toolName, result }],
                };
              }
              return updated;
            });
          }
        },
      );

      setConversationId(result.conversationId);
      if (result.traceId) {
        setTraceId(result.traceId);
      }
      // Fetch the auto-generated title for the conversation
      if (result.conversationId && !conversationTitle) {
        try {
          const convData = await agentService.getConversation(result.conversationId);
          if (convData.conversation?.title) {
            setConversationTitle(convData.conversation.title);
          }
        } catch {
          // Title fetch is non-critical
        }
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
  }, [input, isLoading, conversationId, conversationTitle]);

  const handleFeedbackTap = useCallback(
    (rating: 'positive' | 'negative') => {
      if (!traceId || submittingFeedback || feedbackSubmitted) return;
      setFeedbackRating(rating);
      setFeedbackComment('');
      setShowFeedbackModal(true);
    },
    [traceId, submittingFeedback, feedbackSubmitted],
  );

  const handleFeedbackSubmit = useCallback(async () => {
    if (!traceId || !feedbackRating) return;
    setSubmittingFeedback(true);
    setShowFeedbackModal(false);
    try {
      await agentService.submitFeedback(
        feedbackRating,
        traceId,
        feedbackComment.trim() || undefined,
      );
      setFeedbackSubmitted(true);
    } catch {
      // Silently fail — feedback is non-critical
    } finally {
      setSubmittingFeedback(false);
      setFeedbackRating(null);
      setFeedbackComment('');
    }
  }, [traceId, feedbackRating, feedbackComment]);

  const handleFeedbackSkip = useCallback(() => {
    setShowFeedbackModal(false);
    setFeedbackRating(null);
    setFeedbackComment('');
  }, []);

  const handleLoadConversation = useCallback(async (convId: string) => {
    setShowHistory(false);
    try {
      const data = await agentService.getConversation(convId);
      setMessages(
        (data.messages ?? []).map((m: any) => ({
          role: m.role as 'user' | 'assistant',
          content: m.content,
          createdAt: m.created_at ?? m.createdAt,
        })),
      );
      setConversationId(convId);
      setConversationTitle(data.conversation?.title ?? null);
      setTraceId('');
      setFeedbackSubmitted(false);
    } catch {
      Alert.alert('Error', 'Failed to load conversation.');
    }
  }, []);

  const handleNewChat = useCallback(() => {
    setMessages([]);
    setConversationId(undefined);
    setConversationTitle(null);
    setTraceId('');
    setFeedbackSubmitted(false);
  }, []);

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
    <>
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
              <View>
                <View style={[styles.header, { borderBottomColor: theme.border }]}>
                  <View style={styles.headerLeft}>
                    <TouchableOpacity
                      onPress={() => setShowHistory(true)}
                      hitSlop={{ top: 8, bottom: 8, left: 8, right: 8 }}
                      accessibilityLabel="Conversation history"
                      accessibilityRole="button"
                    >
                      <Ionicons name="time-outline" size={24} color={theme.text} />
                    </TouchableOpacity>
                    <Text style={[styles.title, { color: theme.text }]}>AI Assistant</Text>
                  </View>
                  <View style={styles.headerRight}>
                    <TouchableOpacity
                      onPress={handleNewChat}
                      hitSlop={{ top: 8, bottom: 8, left: 8, right: 8 }}
                      accessibilityLabel="New chat"
                      accessibilityRole="button"
                    >
                      <Ionicons name="add-circle-outline" size={24} color={theme.primary} />
                    </TouchableOpacity>
                    <TouchableOpacity
                      onPress={onClose}
                      hitSlop={{ top: 8, bottom: 8, left: 8, right: 8 }}
                    >
                      <Ionicons name="close" size={24} color={theme.text} />
                    </TouchableOpacity>
                  </View>
                </View>
                {conversationTitle ? (
                  <View style={[styles.subtitleRow, { borderBottomColor: theme.border }]}>
                    <Text
                      style={[styles.headerSubtitle, { color: theme.textSecondary }]}
                      numberOfLines={1}
                    >
                      {conversationTitle}
                    </Text>
                  </View>
                ) : null}
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
                      onPress={() => handleFeedbackTap('positive')}
                      disabled={submittingFeedback}
                      hitSlop={{ top: 8, bottom: 8, left: 8, right: 8 }}
                    >
                      <Ionicons name="thumbs-up-outline" size={18} color={theme.text} />
                    </TouchableOpacity>
                    <TouchableOpacity
                      style={[styles.feedbackBtn, { borderColor: theme.border }]}
                      onPress={() => handleFeedbackTap('negative')}
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

              {/* Conversation History overlay — inside Modal View, not nested RN Modal */}
              <ConversationHistoryScreen
                visible={showHistory}
                onClose={() => setShowHistory(false)}
                onSelectConversation={handleLoadConversation}
                onNewChat={handleNewChat}
              />
            </View>
          </KeyboardAvoidingView>
        </View>
      </Modal>

      {/* Feedback Comment Modal */}
      <Modal
        visible={showFeedbackModal}
        transparent
        animationType="fade"
        onRequestClose={handleFeedbackSkip}
      >
        <View style={styles.feedbackModalOverlay}>
          <View style={[styles.feedbackModalCard, { backgroundColor: theme.surface }]}>
            <Text style={[styles.feedbackModalTitle, { color: theme.text }]}>
              {feedbackRating === 'positive' ? 'Glad we could help!' : 'Sorry about that'}
            </Text>
            <TextInput
              style={[
                styles.feedbackTextarea,
                {
                  backgroundColor: theme.background,
                  color: theme.text,
                  borderColor: theme.border,
                },
              ]}
              placeholder="Tell us more (optional)"
              placeholderTextColor={theme.textSecondary}
              value={feedbackComment}
              onChangeText={setFeedbackComment}
              multiline
              maxLength={500}
              textAlignVertical="top"
            />
            <View style={styles.feedbackModalActions}>
              <TouchableOpacity
                style={[styles.feedbackModalBtn, { borderColor: theme.border }]}
                onPress={handleFeedbackSkip}
              >
                <Text style={[styles.feedbackModalBtnText, { color: theme.textSecondary }]}>
                  Skip
                </Text>
              </TouchableOpacity>
              <TouchableOpacity
                style={[
                  styles.feedbackModalBtn,
                  styles.feedbackModalBtnPrimary,
                  { backgroundColor: theme.primary },
                ]}
                onPress={handleFeedbackSubmit}
              >
                <Text style={[styles.feedbackModalBtnText, { color: brandColors.white }]}>
                  Submit
                </Text>
              </TouchableOpacity>
            </View>
          </View>
        </View>
      </Modal>
    </>
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
  headerLeft: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
    flex: 1,
  },
  headerTitleGroup: {
    flex: 1,
  },
  subtitleRow: {
    paddingHorizontal: spacing.lg,
    paddingTop: spacing.sm,
    paddingBottom: spacing.sm,
    borderBottomWidth: StyleSheet.hairlineWidth,
  },
  headerRight: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
  },
  title: {
    ...typography.sectionTitle,
  },
  headerSubtitle: {
    ...typography.caption,
    marginTop: -2,
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
  feedbackModalOverlay: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
    backgroundColor: 'rgba(0,0,0,0.5)',
    paddingHorizontal: spacing.xl,
  },
  feedbackModalCard: {
    width: '100%',
    borderRadius: radii.lg,
    padding: spacing.lg,
    gap: spacing.md,
  },
  feedbackModalTitle: {
    ...typography.subtitle,
    textAlign: 'center',
  },
  feedbackTextarea: {
    ...typography.body,
    borderRadius: radii.md,
    borderWidth: 1,
    padding: spacing.md,
    minHeight: 80,
    maxHeight: 120,
  },
  feedbackModalActions: {
    flexDirection: 'row',
    justifyContent: 'flex-end',
    gap: spacing.sm,
  },
  feedbackModalBtn: {
    paddingHorizontal: spacing.lg,
    paddingVertical: spacing.sm,
    borderRadius: radii.md,
    borderWidth: 1,
    borderColor: 'transparent',
  },
  feedbackModalBtnPrimary: {
    borderWidth: 0,
  },
  feedbackModalBtnText: {
    ...typography.button,
  },
});
