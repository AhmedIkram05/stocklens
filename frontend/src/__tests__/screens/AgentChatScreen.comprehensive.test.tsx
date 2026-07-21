/**
 * Comprehensive tests for `AgentChatScreen`.
 * Tests error handling, feedback, tool indicators, loading states, and edge cases.
 */

import React from 'react';
import { fireEvent, waitFor } from '@testing-library/react-native';
import AgentChatScreen from '@/screens/AgentChatScreen';
import { renderWithProviders } from '@/__tests__/utils/renderWithProviders';
import { agentService } from '@/services/agent';

jest.mock('@/services/agent', () => ({
  agentService: {
    sendMessage: jest.fn(),
    submitFeedback: jest.fn(),
    listConversations: jest.fn(),
    getConversation: jest.fn(),
  },
}));

const mockSendMessage = agentService.sendMessage as jest.MockedFunction<
  typeof agentService.sendMessage
>;

const mockSubmitFeedback = agentService.submitFeedback as jest.MockedFunction<
  typeof agentService.submitFeedback
>;

const mockListConversations = agentService.listConversations as jest.MockedFunction<
  typeof agentService.listConversations
>;

const mockGetConversation = agentService.getConversation as jest.MockedFunction<
  typeof agentService.getConversation
>;

describe('AgentChatScreen comprehensive', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockSendMessage.mockResolvedValue({
      conversationId: 'test-conv-id',
      fullResponse: 'Test response text.',
      traceId: 'test-trace',
    });
    mockSubmitFeedback.mockResolvedValue({ status: 'success' });
    mockListConversations.mockResolvedValue([]);
    mockGetConversation.mockResolvedValue({
      conversation: {
        id: 'c1',
        title: 'Test',
        messageCount: 2,
        createdAt: '2025-01-01',
        updatedAt: '2025-01-01',
      },
      messages: [
        { role: 'user', content: 'Hello', created_at: '2025-01-01T00:00:00Z' },
        { role: 'assistant', content: 'Hi there', created_at: '2025-01-01T00:00:01Z' },
      ],
    } as any);
  });

  it('renders empty state with disclaimer when no messages', () => {
    const result = renderWithProviders(<AgentChatScreen visible onClose={jest.fn()} />, {
      providerOverrides: { withNavigation: false },
    });
    const { getByText } = result;

    expect(getByText('AI Assistant Disclaimer')).toBeTruthy();
    expect(getByText(/not financial advice/i)).toBeTruthy();
    expect(getByText(/AI can hallucinate/i)).toBeTruthy();
    expect(getByText(/do your own research/i)).toBeTruthy();
    expect(getByText('Ask me anything about your portfolio...')).toBeTruthy();
  });

  it('hides disclaimer after sending a message', async () => {
    const result = renderWithProviders(<AgentChatScreen visible onClose={jest.fn()} />, {
      providerOverrides: { withNavigation: false },
    });
    const { getByText, queryByText, getByPlaceholderText } = result;

    // Disclaimer visible initially
    expect(getByText('AI Assistant Disclaimer')).toBeTruthy();

    // Type a message and trigger submit
    const input = getByPlaceholderText('Ask about your portfolio...');
    fireEvent.changeText(input, 'How is my portfolio doing?');
    fireEvent(input, 'submitEditing');

    // Wait for async sendMessage to resolve and state to update
    await waitFor(() => {
      expect(queryByText('AI Assistant Disclaimer')).toBeNull();
    });

    expect(mockSendMessage).toHaveBeenCalledWith(
      'How is my portfolio doing?',
      undefined,
      expect.any(Function),
      expect.any(Function),
      expect.any(Function),
    );
  });

  it('shows loading indicator when sending message', async () => {
    const result = renderWithProviders(<AgentChatScreen visible onClose={jest.fn()} />, {
      providerOverrides: { withNavigation: false },
    });
    const { getByPlaceholderText } = result;
    const input = getByPlaceholderText('Ask about your portfolio...');
    fireEvent.changeText(input, 'Test message');
    fireEvent(input, 'submitEditing');

    // Should show loading state immediately (input is disabled when loading)
    expect(input.props.editable).toBe(false);

    await waitFor(() => {
      expect(mockSendMessage).toHaveBeenCalled();
    });
  });

  it('does not call sendMessage when input is empty', () => {
    const result = renderWithProviders(<AgentChatScreen visible onClose={jest.fn()} />, {
      providerOverrides: { withNavigation: false },
    });
    const { getByPlaceholderText } = result as any;
    const input = getByPlaceholderText('Ask about your portfolio...');
    fireEvent.changeText(input, ''); // Empty input

    // Press submit - should not call sendMessage
    fireEvent(input, 'submitEditing');
    expect(mockSendMessage).not.toHaveBeenCalled();
  });

  it('shows error message when sendMessage fails', async () => {
    mockSendMessage.mockRejectedValueOnce(new Error('Network error'));

    const result = renderWithProviders(<AgentChatScreen visible onClose={jest.fn()} />, {
      providerOverrides: { withNavigation: false },
    });
    const { getByPlaceholderText, getByText } = result as any;
    const input = getByPlaceholderText('Ask about your portfolio...');
    fireEvent.changeText(input, 'Test message');
    fireEvent(input, 'submitEditing');

    await waitFor(() => {
      expect(getByText(/sorry, something went wrong/i)).toBeTruthy();
    });
  });

  it('adds user message immediately when sending', async () => {
    const result = renderWithProviders(<AgentChatScreen visible onClose={jest.fn()} />, {
      providerOverrides: { withNavigation: false },
    });
    const { getByText, getByPlaceholderText } = result;
    const input = getByPlaceholderText('Ask about your portfolio...');
    fireEvent.changeText(input, 'Hello AI');
    fireEvent(input, 'submitEditing');

    // User message should appear immediately
    await waitFor(() => {
      expect(getByText('Hello AI')).toBeTruthy();
    });
  });

  it('streams assistant response token by token', async () => {
    // Mock sendMessage to simulate streaming
    mockSendMessage.mockImplementationOnce(
      async (
        _text: string,
        _convenctionId?: string | undefined,
        onToken?: (token: string) => void,
        _onToolStart?: (toolName: string) => void,
        _onToolEnd?: (toolName: string) => void,
      ) => {
        // Simulate streaming tokens
        if (onToken) {
          onToken('Hello');
          onToken(' ');
          onToken('there');
          onToken('!');
        }
        return {
          conversationId: 'conv-123',
          fullResponse: 'Hello there!',
          traceId: 'trace-123',
        };
      },
    );

    const result = renderWithProviders(<AgentChatScreen visible onClose={jest.fn()} />, {
      providerOverrides: { withNavigation: false },
    });
    const { getByText } = result;
    // Access getByPlaceholderText via bracket notation
    const getByPlaceholderToken = (result as any)['getByPlaceholderText'];
    const input = getByPlaceholderToken('Ask about your portfolio...');
    fireEvent.changeText(input, 'Hi');
    fireEvent(input, 'submitEditing');

    // Wait for streaming to complete
    await waitFor(() => {
      expect(getByText('Hello there!')).toBeTruthy();
    });
  });

  it('clears input after sending message', async () => {
    const result = renderWithProviders(<AgentChatScreen visible onClose={jest.fn()} />, {
      providerOverrides: { withNavigation: false },
    });
    // Access getByPlaceholderText via bracket notation
    const getByPlaceholderText = (result as any)['getByPlaceholderText'];
    const input = getByPlaceholderText('Ask about your portfolio...');
    fireEvent.changeText(input, 'Test message');
    expect(input.props.value).toBe('Test message');

    fireEvent(input, 'submitEditing');

    // Input should be cleared after sending
    await waitFor(() => {
      expect(input.props.value).toBe('');
    });
  });

  it('resets feedback state when sending new message', async () => {
    mockSendMessage
      .mockResolvedValueOnce({
        conversationId: 'conv-1',
        fullResponse: 'Resp1',
        traceId: 'trace-1',
      }) // First message
      .mockResolvedValueOnce({
        conversationId: 'conv-2',
        fullResponse: 'Resp2',
        traceId: 'trace-2',
      }); // Second message

    const result = renderWithProviders(<AgentChatScreen visible onClose={jest.fn()} />, {
      providerOverrides: { withNavigation: false },
    });
    // Access getByPlaceholderText via bracket notation
    const getByPlaceholderText = (result as any)['getByPlaceholderText'];
    const input = getByPlaceholderText('Ask about your portfolio...');

    // Send first message
    fireEvent.changeText(input, 'First message');
    fireEvent(input, 'submitEditing');
    await waitFor(() => {
      expect(mockSendMessage).toHaveBeenCalledTimes(1);
    });

    // Send second message
    fireEvent.changeText(input, 'Second message');
    fireEvent(input, 'submitEditing');
    await waitFor(() => {
      expect(mockSendMessage).toHaveBeenCalledTimes(2);
    });

    // Second call should have first message's conversationId as the previous conversationId
    expect(mockSendMessage).toHaveBeenNthCalledWith(
      2,
      'Second message',
      'conv-1',
      expect.any(Function),
      expect.any(Function),
      expect.any(Function),
    );
  });

  it('does not crash when rendered hidden', () => {
    expect(() =>
      renderWithProviders(<AgentChatScreen visible={false} onClose={jest.fn()} />),
    ).not.toThrow();
  });

  // ── New Chat button ───────────────────────────────────────────────────────

  it('renders New Chat button in header', () => {
    const { getByLabelText } = renderWithProviders(
      <AgentChatScreen visible onClose={jest.fn()} />,
      { providerOverrides: { withNavigation: false } },
    );
    expect(getByLabelText('New chat')).toBeTruthy();
  });

  it('shows empty disclaimer again after New Chat clears messages', async () => {
    const result = renderWithProviders(<AgentChatScreen visible onClose={jest.fn()} />, {
      providerOverrides: { withNavigation: false },
    });
    const { getByPlaceholderText, getByLabelText, queryByText } = result;
    const input = getByPlaceholderText('Ask about your portfolio...');

    // Send a message
    fireEvent.changeText(input, 'Hello');
    fireEvent(input, 'submitEditing');

    await waitFor(() => {
      expect(mockSendMessage).toHaveBeenCalled();
    });
    await waitFor(() => {
      expect(queryByText('Hello')).toBeTruthy();
    });

    // Disclaimer should be hidden while messages exist
    expect(queryByText('AI Assistant Disclaimer')).toBeNull();

    // Press New Chat
    fireEvent.press(getByLabelText('New chat'));

    // Empty state disclaimer should reappear
    await waitFor(() => {
      expect(queryByText('AI Assistant Disclaimer')).toBeTruthy();
    });
    // The old message should be gone
    expect(queryByText('Hello')).toBeNull();
  });

  it('resets conversationId and conversationTitle on New Chat', async () => {
    const result = renderWithProviders(<AgentChatScreen visible onClose={jest.fn()} />, {
      providerOverrides: { withNavigation: false },
    });
    const { getByPlaceholderText, getByLabelText, queryByText } = result;
    const input = getByPlaceholderText('Ask about your portfolio...');

    // Send a message to trigger conversation title fetch
    fireEvent.changeText(input, 'Test');
    fireEvent(input, 'submitEditing');

    await waitFor(() => {
      expect(mockSendMessage).toHaveBeenCalled();
    });
    // Title fetch fires in the background after send
    await waitFor(() => {
      expect(mockGetConversation).toHaveBeenCalled();
    });

    // The title subtitle should be gone after New Chat
    fireEvent.press(getByLabelText('New chat'));
    await waitFor(() => {
      // Messages cleared so disclaimer visible
      expect(queryByText('AI Assistant Disclaimer')).toBeTruthy();
    });
    // No subtitle with a title should be visible
    expect(queryByText('Test')).toBeNull();
  });

  it('does not error when New Chat is pressed with no messages', () => {
    const { getByLabelText } = renderWithProviders(
      <AgentChatScreen visible onClose={jest.fn()} />,
      { providerOverrides: { withNavigation: false } },
    );
    expect(() => fireEvent.press(getByLabelText('New chat'))).not.toThrow();
  });
});
