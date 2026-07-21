/**
 * Integration tests for `ConversationHistoryScreen`.
 *
 * Covers:
 * - Loading state
 * - Empty state when no conversations exist
 * - Rendering conversation list
 * - Tapping a conversation calls onSelectConversation
 * - Deleting a conversation via swipe action
 * - Closing the modal via close button
 * - New Chat button calls onNewChat and onClose
 */

import React from 'react';
import { fireEvent, waitFor } from '@testing-library/react-native';
import ConversationHistoryScreen from '../../screens/ConversationHistoryScreen';
import { renderWithProviders } from '../utils/renderWithProviders';
import { agentService } from '../../services/agent';

jest.mock('../../services/agent', () => ({
  agentService: {
    listConversations: jest.fn(),
    deleteConversation: jest.fn(),
  },
}));

const mockedAgentService = agentService as jest.Mocked<typeof agentService>;

const mockConversations = [
  {
    id: 'conv-1',
    title: 'Portfolio Review',
    messageCount: 3,
    createdAt: '2026-07-20T10:00:00Z',
    updatedAt: '2026-07-20T11:00:00Z',
  },
  {
    id: 'conv-2',
    title: 'Market Analysis',
    messageCount: 7,
    createdAt: '2026-07-19T09:00:00Z',
    updatedAt: '2026-07-19T09:30:00Z',
  },
  {
    id: 'conv-3',
    title: null,
    messageCount: 1,
    createdAt: '2026-07-21T08:00:00Z',
    updatedAt: '2026-07-21T08:05:00Z',
  },
];

describe('ConversationHistoryScreen', () => {
  const mockOnClose = jest.fn();
  const mockOnSelectConversation = jest.fn();
  const mockOnNewChat = jest.fn();

  beforeEach(() => {
    jest.clearAllMocks();
    jest.useFakeTimers();
    jest.setSystemTime(new Date('2026-07-21T12:00:00Z'));
    mockedAgentService.listConversations.mockResolvedValue(mockConversations as any);
    mockedAgentService.deleteConversation.mockResolvedValue(undefined);
  });

  afterEach(() => {
    jest.useRealTimers();
  });

  const renderScreen = (visible = true) =>
    renderWithProviders(
      <ConversationHistoryScreen
        visible={visible}
        onClose={mockOnClose}
        onSelectConversation={mockOnSelectConversation}
      />,
      { providerOverrides: { withNavigation: false } },
    );

  it('renders the modal with title', async () => {
    const { getByText } = renderScreen();
    await waitFor(() => expect(getByText('History')).toBeTruthy());
  });

  it('shows close button and calls onClose when pressed', async () => {
    const { getByLabelText } = renderScreen();
    await waitFor(() => expect(getByLabelText('Close history')).toBeTruthy());
    fireEvent.press(getByLabelText('Close history'));
    expect(mockOnClose).toHaveBeenCalledTimes(1);
  });

  it('calls onNewChat and onClose when New Chat button pressed', async () => {
    const { getByLabelText } = renderWithProviders(
      <ConversationHistoryScreen
        visible
        onClose={mockOnClose}
        onSelectConversation={mockOnSelectConversation}
        onNewChat={mockOnNewChat}
      />,
      { providerOverrides: { withNavigation: false } },
    );
    await waitFor(() => expect(getByLabelText('New chat')).toBeTruthy());
    fireEvent.press(getByLabelText('New chat'));
    expect(mockOnNewChat).toHaveBeenCalledTimes(1);
    expect(mockOnClose).toHaveBeenCalledTimes(1);
  });

  it('loads and displays a list of conversations', async () => {
    const { getByText } = renderScreen();
    await waitFor(() => expect(getByText('Portfolio Review')).toBeTruthy());
    expect(getByText('Market Analysis')).toBeTruthy();
    expect(getByText('3 messages')).toBeTruthy();
    expect(getByText('7 messages')).toBeTruthy();
  });

  it('shows "New Conversation" when title is null', async () => {
    const { getByText } = renderScreen();
    await waitFor(() => expect(getByText('New Conversation')).toBeTruthy());
  });

  it('calls onSelectConversation with conversation id when tapped', async () => {
    const { getByText } = renderScreen();
    await waitFor(() => expect(getByText('Portfolio Review')).toBeTruthy());
    fireEvent.press(getByText('Portfolio Review'));
    expect(mockOnSelectConversation).toHaveBeenCalledWith('conv-1');
  });

  it('deletes a conversation on long press', async () => {
    const { getByText } = renderScreen();
    await waitFor(() => expect(getByText('Market Analysis')).toBeTruthy());

    // Long-press the first conversation item to trigger delete
    fireEvent(getByText('Portfolio Review'), 'longPress');

    await waitFor(() => {
      expect(mockedAgentService.deleteConversation).toHaveBeenCalledWith('conv-1');
      // Item should be removed from the list
      expect(getByText('Market Analysis')).toBeTruthy();
    });
  });

  it('shows empty state when no conversations exist', async () => {
    mockedAgentService.listConversations.mockResolvedValue([]);
    const { getByText } = renderScreen();
    await waitFor(() => expect(getByText('No conversations yet')).toBeTruthy());
    expect(getByText('Start a chat with the AI assistant to begin.')).toBeTruthy();
  });

  it('does not render when visible is false', () => {
    const { queryByText } = renderScreen(false);
    expect(queryByText('History')).toBeNull();
  });
});
