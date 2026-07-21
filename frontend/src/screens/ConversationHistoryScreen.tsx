/**
 * ConversationHistoryScreen
 *
 * Overlay that shows the user's past conversations.
 * Renders inside the chat Modal (no nested RN Modal — RN can't stack them).
 * Loads from agentService.listConversations().
 * Tap a row → onSelectConversation(id).
 * Long-press on a row → deleteConversation(id).
 */

import React, { useState, useEffect, useCallback } from 'react';
import {
  View,
  Text,
  FlatList,
  StyleSheet,
  TouchableOpacity,
  ActivityIndicator,
  Alert,
} from 'react-native';
import { Ionicons } from '@expo/vector-icons';

import { useTheme } from '../contexts/ThemeContext';
import { spacing, radii, typography } from '../styles/theme';
import { agentService, type ConversationSummary } from '../services/agent';
import ConversationListItem from '../components/chat/ConversationListItem';

interface ConversationHistoryScreenProps {
  visible: boolean;
  onClose: () => void;
  onSelectConversation: (conversationId: string) => void;
  onNewChat?: () => void;
}

export default function ConversationHistoryScreen({
  visible,
  onClose,
  onSelectConversation,
  onNewChat,
}: ConversationHistoryScreenProps) {
  const { theme } = useTheme();

  const [conversations, setConversations] = useState<ConversationSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [deletingId, setDeletingId] = useState<string | null>(null);

  const fetchConversations = useCallback(async () => {
    setLoading(true);
    try {
      const res = await agentService.listConversations();
      // The API returns { conversations, total }
      const list = Array.isArray(res)
        ? (res as unknown as ConversationSummary[])
        : (res as any).conversations;
      setConversations(list ?? []);
    } catch {
      setConversations([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (visible) {
      fetchConversations();
    }
  }, [visible, fetchConversations]);

  const handleDelete = useCallback(
    async (conv: ConversationSummary) => {
      if (deletingId) return;
      setDeletingId(conv.id);
      try {
        await agentService.deleteConversation(conv.id);
        setConversations((prev) => prev.filter((c) => c.id !== conv.id));
      } catch {
        Alert.alert('Error', 'Failed to delete conversation.');
      } finally {
        setDeletingId(null);
      }
    },
    [deletingId],
  );

  const handleSelect = useCallback(
    (conv: ConversationSummary) => {
      onSelectConversation(conv.id);
    },
    [onSelectConversation],
  );

  const renderItem = useCallback(
    ({ item }: { item: ConversationSummary }) => (
      <ConversationListItem
        conversation={item}
        onPress={() => handleSelect(item)}
        onDelete={() => handleDelete(item)}
      />
    ),
    [handleSelect, handleDelete],
  );

  const keyExtractor = useCallback((item: ConversationSummary) => item.id, []);

  const renderEmptyState = () => (
    <View style={styles.emptyState}>
      <Ionicons name="chatbubbles-outline" size={48} color={theme.textSecondary} />
      <Text style={[styles.emptyTitle, { color: theme.text }]}>No conversations yet</Text>
      <Text style={[styles.emptyBody, { color: theme.textSecondary }]}>
        Start a chat with the AI assistant to begin.
      </Text>
    </View>
  );

  if (!visible) return null;

  return (
    <View style={StyleSheet.absoluteFill}>
      <View style={[styles.overlay, { backgroundColor: theme.background + 'CC' }]}>
        <View style={[styles.card, { backgroundColor: theme.background }]}>
          {/* Header */}
          <View style={[styles.header, { borderBottomColor: theme.border }]}>
            <Text style={[styles.title, { color: theme.text }]}>History</Text>
            <View style={styles.headerActions}>
              {onNewChat && (
                <TouchableOpacity
                  onPress={() => {
                    onClose();
                    onNewChat();
                  }}
                  hitSlop={{ top: 8, bottom: 8, left: 8, right: 8 }}
                  accessibilityLabel="New chat"
                  accessibilityRole="button"
                  style={styles.newChatBtn}
                >
                  <Ionicons name="add-circle-outline" size={24} color={theme.primary} />
                </TouchableOpacity>
              )}
              <TouchableOpacity
                onPress={onClose}
                hitSlop={{ top: 8, bottom: 8, left: 8, right: 8 }}
                accessibilityLabel="Close history"
                accessibilityRole="button"
              >
                <Ionicons name="close" size={24} color={theme.text} />
              </TouchableOpacity>
            </View>
          </View>

          {/* Content */}
          {loading ? (
            <View style={styles.loadingWrap}>
              <ActivityIndicator size="large" color={theme.primary} />
              <Text style={[styles.loadingText, { color: theme.textSecondary }]}>
                Loading conversations...
              </Text>
            </View>
          ) : (
            <FlatList
              data={conversations}
              keyExtractor={keyExtractor}
              renderItem={renderItem}
              contentContainerStyle={conversations.length === 0 ? styles.listEmpty : undefined}
              ListEmptyComponent={renderEmptyState}
            />
          )}
        </View>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  overlay: {
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
  headerActions: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
  },
  newChatBtn: {
    padding: 2,
  },
  title: {
    ...typography.sectionTitle,
  },
  loadingWrap: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
    gap: spacing.md,
  },
  loadingText: {
    ...typography.caption,
  },
  listEmpty: {
    flex: 1,
    justifyContent: 'center',
  },
  emptyState: {
    alignItems: 'center',
    gap: spacing.sm,
    paddingHorizontal: spacing.xl,
  },
  emptyTitle: {
    ...typography.subtitle,
    textAlign: 'center',
  },
  emptyBody: {
    ...typography.caption,
    textAlign: 'center',
    lineHeight: 20,
  },
});
