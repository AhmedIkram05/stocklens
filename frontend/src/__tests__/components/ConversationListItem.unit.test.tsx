/**
 * ConversationListItem — unit tests.
 *
 * Tests rendering of title, message count, relative timestamp,
 * onPress callback, and swipe-to-delete via onDelete callback.
 */

import React from 'react';
import { fireEvent } from '@testing-library/react-native';
import { render } from '@testing-library/react-native';
import { ThemeContext, lightTheme } from '../../contexts/ThemeContext';
import ConversationListItem from '../../components/chat/ConversationListItem';
import type { ConversationSummary } from '../../services/agent';

const mockOnPress = jest.fn();
const mockOnDelete = jest.fn();

const baseConversation: ConversationSummary = {
  id: 'conv-1',
  title: 'My Portfolio Analysis',
  messageCount: 5,
  createdAt: '2026-07-21T10:00:00Z',
  updatedAt: '2026-07-21T10:30:00Z',
};

function renderItem(conversation: ConversationSummary = baseConversation) {
  return render(
    <ThemeContext.Provider
      value={{ theme: lightTheme, mode: 'light', isDark: false, setMode: () => {} }}
    >
      <ConversationListItem
        conversation={conversation}
        onPress={mockOnPress}
        onDelete={mockOnDelete}
      />
    </ThemeContext.Provider>,
  );
}

describe('ConversationListItem', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    jest.useFakeTimers();
    jest.setSystemTime(new Date('2026-07-21T12:00:00Z'));
  });

  afterEach(() => {
    jest.useRealTimers();
  });

  it('renders the conversation title', async () => {
    const { getByText } = await renderItem();
    expect(getByText('My Portfolio Analysis')).toBeTruthy();
  });

  it('shows "New Conversation" when title is null', async () => {
    const conv: ConversationSummary = { ...baseConversation, title: null };
    const { getByText } = await renderItem(conv);
    expect(getByText('New Conversation')).toBeTruthy();
  });

  it('shows message count', async () => {
    const { getByText } = await renderItem();
    expect(getByText('5 messages')).toBeTruthy();
  });

  it('shows singular "1 message" for single message', async () => {
    const conv: ConversationSummary = { ...baseConversation, messageCount: 1 };
    const { getByText } = await renderItem(conv);
    expect(getByText('1 message')).toBeTruthy();
  });

  it('shows relative timestamp from formatRelativeDate', async () => {
    const { getByText } = await renderItem();
    // 2026-07-21T10:30:00Z is 1.5h before the system time of 12:00:00Z
    expect(getByText('1h ago')).toBeTruthy();
  });

  it('calls onPress when tapped', async () => {
    const { getByText } = await renderItem();
    await fireEvent.press(getByText('My Portfolio Analysis'));
    expect(mockOnPress).toHaveBeenCalledTimes(1);
  });

  it('calls onDelete on long press', async () => {
    const { getByText } = await renderItem();
    await fireEvent(getByText('My Portfolio Analysis'), 'longPress');
    expect(mockOnDelete).toHaveBeenCalledTimes(1);
  });
});
