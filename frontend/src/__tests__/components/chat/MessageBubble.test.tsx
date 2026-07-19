import React from 'react';
import MessageBubble from '@/components/chat/MessageBubble';
import { renderWithProviders } from '@/__tests__/utils/renderWithProviders';
import type { AgentMessage } from '@/services/agent';

describe('MessageBubble', () => {
  const userMessage: AgentMessage = {
    role: 'user',
    content: 'How is my portfolio performing?',
    createdAt: '2026-07-19T00:00:00Z',
  };

  const assistantMessage: AgentMessage = {
    role: 'assistant',
    content: 'Your portfolio is up 5.2% this quarter.',
    createdAt: '2026-07-19T00:00:00Z',
  };

  const messageWithTools: AgentMessage = {
    role: 'assistant',
    content: 'I found the data.',
    toolCalls: ['get_portfolio_summary', 'get_portfolio_performance'],
    createdAt: '2026-07-19T00:00:00Z',
  };

  it('renders user message text', () => {
    const { getByText } = renderWithProviders(<MessageBubble message={userMessage} />);
    expect(getByText('How is my portfolio performing?')).toBeTruthy();
  });

  it('renders assistant message text', () => {
    const { getByText } = renderWithProviders(<MessageBubble message={assistantMessage} />);
    expect(getByText('Your portfolio is up 5.2% this quarter.')).toBeTruthy();
  });

  it('displays tool call indicators below assistant messages', () => {
    const { getByText } = renderWithProviders(<MessageBubble message={messageWithTools} />);
    expect(getByText(/get_portfolio_summary/)).toBeTruthy();
    expect(getByText(/get_portfolio_performance/)).toBeTruthy();
  });

  it('does not render tool indicators for user messages', () => {
    const { queryByText } = renderWithProviders(<MessageBubble message={userMessage} />);
    expect(queryByText(/🔧/)).toBeNull();
  });

  it('handles empty content gracefully', () => {
    const empty: AgentMessage = {
      role: 'assistant',
      content: '',
      createdAt: '',
    };
    const { getByText } = renderWithProviders(<MessageBubble message={empty} />);
    expect(getByText('')).toBeTruthy();
  });

  it('does not render tool row when toolCalls is empty array', () => {
    const msg: AgentMessage = {
      role: 'assistant',
      content: 'Hello',
      toolCalls: [],
      createdAt: '',
    };
    expect(() => renderWithProviders(<MessageBubble message={msg} />)).not.toThrow();
  });

  it('does not render tool row when toolCalls is undefined', () => {
    const msg: AgentMessage = {
      role: 'assistant',
      content: 'No tools used',
      createdAt: '',
    };
    expect(() => renderWithProviders(<MessageBubble message={msg} />)).not.toThrow();
  });
});
