/**
 * Integration tests for `AgentChatScreen`.
 *
 * Verifies the disclaimer warning shows in empty state and disappears
 * after sending a message. The AI disclaimer is shown as a placeholder
 * in the FlatList's ListEmptyComponent, so it is automatically hidden
 * once messages are added to the list.
 */

import React from 'react';
import { fireEvent, waitFor } from '@testing-library/react-native';
import AgentChatScreen from '@/screens/AgentChatScreen';
import { renderWithProviders } from '@/__tests__/utils/renderWithProviders';
import { agentService } from '@/services/agent';

jest.mock('@/services/agent', () => ({
  agentService: {
    sendMessage: jest.fn(),
  },
}));

const mockSendMessage = agentService.sendMessage as jest.MockedFunction<
  typeof agentService.sendMessage
>;

describe('AgentChatScreen disclaimer', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockSendMessage.mockResolvedValue({
      conversationId: 'test-conv-id',
      fullResponse: 'Test response text.',
      traceId: 'test-trace',
    });
  });

  it('shows the AI disclaimer heading in empty state', () => {
    const { getByText } = renderWithProviders(<AgentChatScreen visible onClose={jest.fn()} />);

    expect(getByText('AI Assistant Disclaimer')).toBeTruthy();
  });

  it('shows the full warning message about AI limitations', () => {
    const { getByText } = renderWithProviders(<AgentChatScreen visible onClose={jest.fn()} />);

    expect(getByText(/not financial advice/i)).toBeTruthy();
    expect(getByText(/AI can hallucinate/i)).toBeTruthy();
    expect(getByText(/do your own research/i)).toBeTruthy();
  });

  it('shows the prompt to ask about portfolio in empty state', () => {
    const { getByText } = renderWithProviders(<AgentChatScreen visible onClose={jest.fn()} />);

    expect(getByText('Ask me anything about your portfolio...')).toBeTruthy();
  });

  it('hides the disclaimer after sending a message', async () => {
    const { getByText, queryByText, getByPlaceholderText } = renderWithProviders(
      <AgentChatScreen visible onClose={jest.fn()} />,
    );

    // Disclaimer visible initially
    expect(getByText('AI Assistant Disclaimer')).toBeTruthy();

    // Type a message and trigger submit (send action)
    const input = getByPlaceholderText('Ask about your portfolio...');
    fireEvent.changeText(input, 'How is my portfolio doing?');
    fireEvent(input, 'submitEditing');

    // Wait for async sendMessage to resolve and state to update
    await waitFor(() => {
      expect(queryByText('AI Assistant Disclaimer')).toBeNull();
    });
  });

  it('does not crash when rendered hidden', () => {
    expect(() =>
      renderWithProviders(<AgentChatScreen visible={false} onClose={jest.fn()} />),
    ).not.toThrow();
  });
});
