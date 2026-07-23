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
  // Stateful thinking-tag stripper for streaming tokens.
  // Holds back text that could be the start of a <thinking> tag
  // so we never emit partial tags during streaming.
  const thinkingStripperRef = useRef<{
    buffer: string;
    inTag: boolean;
  }>({ buffer: '', inTag: false });

  const handleSend = useCallback(async () => {
    const text = input.trim();
    if (!text || isLoading) return;

    // Reset feedback state and thinking tag stripper for the new response
    setTraceId('');
    setFeedbackSubmitted(false);
    setInput('');
    setIsLoading(true);
    thinkingStripperRef.current = { buffer: '', inTag: false };

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
        // onToken — stateful thinking-tag stripper
        (token: string) => {
          const s = thinkingStripperRef.current;
          s.buffer += token;

          if (s.inTag) {
            // Inside a <thinking> tag — look for closing </thinking>
            const closeIdx = s.buffer.indexOf('</thinking>');
            if (closeIdx === -1) return; // Still inside — discard
            // Tag closed — emit text after </thinking>
            const after = s.buffer.slice(closeIdx + '</thinking>'.length);
            s.buffer = '';
            s.inTag = false;
            if (after) {
              setMessages((prev) => {
                const updated = [...prev];
                const lastIdx = updated.length - 1;
                if (lastIdx >= 0 && updated[lastIdx].role === 'assistant') {
                  updated[lastIdx] = {
                    ...updated[lastIdx],
                    content: updated[lastIdx].content + after,
                  };
                }
                return updated;
              });
            }
            return;
          }

          // Not in tag — look for <thinking anywhere in the buffer
          const openIdx = s.buffer.indexOf('<thinking');
          if (openIdx !== -1) {
            const before = s.buffer.slice(0, openIdx);
            s.buffer = s.buffer.slice(openIdx);
            s.inTag = true;
            if (before) {
              setMessages((prev) => {
                const updated = [...prev];
                const lastIdx = updated.length - 1;
                if (lastIdx >= 0 && updated[lastIdx].role === 'assistant') {
                  updated[lastIdx] = {
                    ...updated[lastIdx],
                    content: updated[lastIdx].content + before,
                  };
                }
                return updated;
              });
            }
            // After entering tag, check if the same buffer also closes it
            const closeIdx = s.buffer.indexOf('</thinking>');
            if (closeIdx !== -1) {
              const after = s.buffer.slice(closeIdx + '</thinking>'.length);
              s.buffer = '';
              s.inTag = false;
              if (after) {
                setMessages((prev) => {
                  const updated = [...prev];
                  const lastIdx = updated.length - 1;
                  if (lastIdx >= 0 && updated[lastIdx].role === 'assistant') {
                    updated[lastIdx] = {
                      ...updated[lastIdx],
                      content: updated[lastIdx].content + after,
                    };
                  }
                  return updated;
                });
              }
            }
            return;
          }

          // Buffer doesn't contain <thinking — but if it ends with <
          // it could be the start of one in the next token. Hold back.
          if (s.buffer.endsWith('<')) return;

          // Safe to emit
          const safe = s.buffer;
          s.buffer = '';
          if (safe) {
            setMessages((prev) => {
              const updated = [...prev];
              const lastIdx = updated.length - 1;
              if (lastIdx >= 0 && updated[lastIdx].role === 'assistant') {
                updated[lastIdx] = {
                  ...updated[lastIdx],
                  content: updated[lastIdx].content + safe,
                };
              }
              return updated;
            });
          }
        },
        // onToolStart
        (toolName: string) => {
          setCurrentTool(toolName);
        },
        // onToolEnd
        (_toolName: string, result?: any) => {
          setCurrentTool(null);
          setMessages((prev) => {
            const updated = [...prev];
            const lastIdx = updated.length - 1;
            if (lastIdx >= 0 && updated[lastIdx].role === 'assistant') {
              const msg = updated[lastIdx];
              updated[lastIdx] = {
                ...msg,
                toolResults: [
                  ...(msg.toolResults ?? []),
                  { toolName: _toolName, result: result ?? { _raw: String(result) } },
                ],
              };
            }
            return updated;
          });
        },
        // onReasoning — model-provided reasoning is displayed separately in a
        // subdued style above the final answer.
        (reasoning: string) => {
          setMessages((prev) => {
            const updated = [...prev];
            const lastIdx = updated.length - 1;
            if (lastIdx >= 0 && updated[lastIdx].role === 'assistant') {
              updated[lastIdx] = {
                ...updated[lastIdx],
                reasoning: (updated[lastIdx].reasoning ?? '') + reasoning,
              };
            }
            return updated;
          });
        },
      );

      setConversationId(result.conversationId);
      if (result.traceId) {
        setTraceId(result.traceId);
      }
      // Strip any <thinking> tags that may have leaked through streaming
      if (result.fullResponse && /<thinking/i.test(result.fullResponse)) {
        const clean = result.fullResponse
          .replace(/<thinking>[\s\S]*?<\/thinking>\s*/g, '')
          .replace(/<thinking\b[\s\S]*/g, '')
          .replace(/\s*<\/thinking>/g, '')
          .trim();
        if (clean !== result.fullResponse) {
          setMessages((prev) => {
            const updated = [...prev];
            const lastIdx = updated.length - 1;
            if (lastIdx >= 0 && updated[lastIdx].role === 'assistant') {
              updated[lastIdx] = { ...updated[lastIdx], content: clean };
            }
            return updated;
          });
        }
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
      console.error('Agent stream error:', err instanceof Error ? err.message : String(err));
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
      if ((!traceId && !conversationId) || submittingFeedback || feedbackSubmitted) return;
      setFeedbackRating(rating);
      setFeedbackComment('');
      setShowFeedbackModal(true);
    },
    [traceId, conversationId, submittingFeedback, feedbackSubmitted],
  );

  const handleFeedbackSubmit = useCallback(async () => {
    if (!feedbackRating) return;
    if (!traceId && !conversationId) return;
    setSubmittingFeedback(true);
    setShowFeedbackModal(false);
    try {
      await agentService.submitFeedback(
        feedbackRating,
        traceId,
        feedbackComment.trim() || undefined,
        conversationId,
      );
      setFeedbackSubmitted(true);
    } catch {
      // Silently fail — feedback is non-critical
    } finally {
      setSubmittingFeedback(false);
      setFeedbackRating(null);
      setFeedbackComment('');
    }
  }, [traceId, conversationId, feedbackRating, feedbackComment]);

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
          reasoning: m.reasoning_steps?.thinking,
          toolResults: (m.tools_used ?? [])
            .filter((t: any) => t.status === 'completed' && t.result != null)
            .map((t: any) => ({
              toolName: t.name,
              result: typeof t.result === 'string' ? { _raw: t.result } : t.result,
            })),
          createdAt: m.created_at ?? m.createdAt,
        })),
      );
      setConversationId(convId);
      setConversationTitle(data.conversation?.title ?? null);
      // Restore feedback state from stored rating if available
      const convData = data.conversation as any;
      if (convData?.user_rating) {
        setFeedbackSubmitted(true);
      }
      setTraceId('');
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
                      accessibilityLabel="Close"
                      accessibilityRole="button"
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
              {(traceId || conversationId) &&
                !isLoading &&
                !feedbackSubmitted &&
                messages.length > 0 && (
                  <View style={styles.feedbackRow}>
                    <Text style={[styles.feedbackLabel, { color: theme.textSecondary }]}>
                      Was this helpful?
                    </Text>
                    <View style={styles.feedbackBtns}>
                      <TouchableOpacity
                        style={[
                          styles.feedbackBtn,
                          {
                            borderColor:
                              feedbackRating === 'positive' ? theme.primary : theme.border,
                          },
                        ]}
                        onPress={() => handleFeedbackTap('positive')}
                        disabled={submittingFeedback}
                        hitSlop={{ top: 8, bottom: 8, left: 8, right: 8 }}
                        accessibilityLabel="Thumbs up"
                        accessibilityRole="button"
                      >
                        <Ionicons
                          name={feedbackRating === 'positive' ? 'thumbs-up' : 'thumbs-up-outline'}
                          size={18}
                          color={feedbackRating === 'positive' ? theme.primary : theme.text}
                        />
                      </TouchableOpacity>
                      <TouchableOpacity
                        style={[
                          styles.feedbackBtn,
                          {
                            borderColor:
                              feedbackRating === 'negative' ? brandColors.red : theme.border,
                          },
                        ]}
                        onPress={() => handleFeedbackTap('negative')}
                        disabled={submittingFeedback}
                        hitSlop={{ top: 8, bottom: 8, left: 8, right: 8 }}
                        accessibilityLabel="Thumbs down"
                        accessibilityRole="button"
                      >
                        <Ionicons
                          name={
                            feedbackRating === 'negative' ? 'thumbs-down' : 'thumbs-down-outline'
                          }
                          size={18}
                          color={feedbackRating === 'negative' ? brandColors.red : theme.text}
                        />
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
