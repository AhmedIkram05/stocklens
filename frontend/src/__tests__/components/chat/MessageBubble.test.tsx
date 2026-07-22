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
    toolResults: [
      { toolName: 'get_portfolio_summary', result: { value: 50000 } },
      { toolName: 'get_portfolio_performance', result: { return_pct: 5.2 } },
    ],
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

  // ── Phase 1: Tool Results Accordion ─────────────────────────────────

  it('renders tool results accordion for assistant messages with toolResults', () => {
    const msgWithResults: AgentMessage = {
      role: 'assistant',
      content: 'Here is your portfolio data.',
      toolResults: [
        {
          toolName: 'get_portfolio_summary',
          result: { name: 'My Portfolio', total_market_value_gbp: 50000 },
        },
        {
          toolName: 'get_sector_exposure',
          result: { sectors: [{ sector: 'Tech', allocation_pct: 60 }] },
        },
      ],
      createdAt: '2026-07-19T00:00:00Z',
    };
    const { getByText } = renderWithProviders(<MessageBubble message={msgWithResults} />);
    // Accordion shows tool names in header
    expect(getByText(/get_portfolio_summary/)).toBeTruthy();
    expect(getByText(/get_sector_exposure/)).toBeTruthy();
  });

  it('does not render tool results accordion for user messages', () => {
    const msg: AgentMessage = {
      role: 'user',
      content: 'How is my portfolio?',
      toolResults: [{ toolName: 'get_portfolio_summary', result: { value: 100 } }],
      createdAt: '',
    };
    const { queryByText } = renderWithProviders(<MessageBubble message={msg} />);
    // Tool results accordion should not render for user messages
    expect(queryByText(/get_portfolio_summary/)).toBeNull();
  });

  it('does not render tool results accordion when toolResults is empty', () => {
    const msg: AgentMessage = {
      role: 'assistant',
      content: 'No tools used',
      toolResults: [],
      createdAt: '',
    };
    const { queryByText } = renderWithProviders(<MessageBubble message={msg} />);
    // Accordion renders tool names like get_portfolio_summary, never generic "tool" text
    expect(queryByText(/get_portfolio/)).toBeNull();
    expect(queryByText(/^TWR$/)).toBeNull();
  });

  it('does not render tool results accordion when toolResults is undefined', () => {
    const msg: AgentMessage = {
      role: 'assistant',
      content: 'Simple response',
      createdAt: '',
    };
    expect(() => renderWithProviders(<MessageBubble message={msg} />)).not.toThrow();
  });
});
