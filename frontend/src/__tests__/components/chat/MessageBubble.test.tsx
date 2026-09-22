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

  it('renders user message text', async () => {
    const { getByText } = await renderWithProviders(<MessageBubble message={userMessage} />);
    expect(getByText('How is my portfolio performing?')).toBeTruthy();
  });

  it('renders assistant message text', async () => {
    const { getByText } = await renderWithProviders(<MessageBubble message={assistantMessage} />);
    expect(getByText('Your portfolio is up 5.2% this quarter.')).toBeTruthy();
  });

  it('renders Markdown bold markers as bold text rather than literal asterisks', async () => {
    const { getByText, queryByText } = await renderWithProviders(
      <MessageBubble message={{ ...assistantMessage, content: 'Your **portfolio** is up.' }} />,
    );
    expect(getByText('portfolio')).toBeTruthy();
    expect(queryByText('**portfolio**')).toBeNull();
  });

  it('shows model reasoning above the final answer', async () => {
    const { getByText } = await renderWithProviders(
      <MessageBubble
        message={{ ...assistantMessage, reasoning: 'I checked the latest holdings.' }}
      />,
    );
    expect(getByText('Thinking')).toBeTruthy();
    expect(getByText('I checked the latest holdings.')).toBeTruthy();
  });

  it('displays tool call indicators below assistant messages', async () => {
    const { getByText } = await renderWithProviders(<MessageBubble message={messageWithTools} />);
    expect(getByText(/get_portfolio_summary/)).toBeTruthy();
    expect(getByText(/get_portfolio_performance/)).toBeTruthy();
  });

  it('does not render tool indicators for user messages', async () => {
    const { queryByText } = await renderWithProviders(<MessageBubble message={userMessage} />);
    expect(queryByText(/🔧/)).toBeNull();
  });

  it('handles empty content gracefully', async () => {
    const empty: AgentMessage = {
      role: 'assistant',
      content: '',
      createdAt: '',
    };
    const { getByText } = await renderWithProviders(<MessageBubble message={empty} />);
    expect(getByText('')).toBeTruthy();
  });

  it('does not render tool row when toolCalls is empty array', async () => {
    const msg: AgentMessage = {
      role: 'assistant',
      content: 'Hello',
      toolCalls: [],
      createdAt: '',
    };
    await renderWithProviders(<MessageBubble message={msg} />);
  });

  it('does not render tool row when toolCalls is undefined', async () => {
    const msg: AgentMessage = {
      role: 'assistant',
      content: 'No tools used',
      createdAt: '',
    };
    await renderWithProviders(<MessageBubble message={msg} />);
  });

  // ── Phase 1: Tool Results Accordion ─────────────────────────────────

  it('renders tool results accordion for assistant messages with toolResults', async () => {
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
    const { getByText } = await renderWithProviders(<MessageBubble message={msgWithResults} />);
    // Accordion shows tool names in header
    expect(getByText(/get_portfolio_summary/)).toBeTruthy();
    expect(getByText(/get_sector_exposure/)).toBeTruthy();
  });

  it('does not render tool results accordion for user messages', async () => {
    const msg: AgentMessage = {
      role: 'user',
      content: 'How is my portfolio?',
      toolResults: [{ toolName: 'get_portfolio_summary', result: { value: 100 } }],
      createdAt: '',
    };
    const { queryByText } = await renderWithProviders(<MessageBubble message={msg} />);
    // Tool results accordion should not render for user messages
    expect(queryByText(/get_portfolio_summary/)).toBeNull();
  });

  it('does not render tool results accordion when toolResults is empty', async () => {
    const msg: AgentMessage = {
      role: 'assistant',
      content: 'No tools used',
      toolResults: [],
      createdAt: '',
    };
    const { queryByText } = await renderWithProviders(<MessageBubble message={msg} />);
    // Accordion renders tool names like get_portfolio_summary, never generic "tool" text
    expect(queryByText(/get_portfolio/)).toBeNull();
    expect(queryByText(/^TWR$/)).toBeNull();
  });

  it('does not render tool results accordion when toolResults is undefined', async () => {
    const msg: AgentMessage = {
      role: 'assistant',
      content: 'Simple response',
      createdAt: '',
    };
    await renderWithProviders(<MessageBubble message={msg} />);
  });
});
