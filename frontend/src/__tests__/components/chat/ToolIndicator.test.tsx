import React from 'react';
import ToolIndicator from '@/components/chat/ToolIndicator';
import { renderWithProviders } from '@/__tests__/utils/renderWithProviders';

describe('ToolIndicator', () => {
  it('renders tool name when tool is active', async () => {
    const { getByText } = await renderWithProviders(
      <ToolIndicator toolName="get_portfolio_summary" />,
    );
    expect(getByText(/get_portfolio_summary/)).toBeTruthy();
  });

  it('displays "Using" prefix in the label', async () => {
    const { getByText } = await renderWithProviders(<ToolIndicator toolName="get_market_quote" />);
    expect(getByText(/Using get_market_quote/)).toBeTruthy();
  });

  it('renders nothing when toolName is null', async () => {
    const { queryByText } = await renderWithProviders(<ToolIndicator toolName={null} />);
    // Should render nothing — no text should be visible
    expect(queryByText(/Using/)).toBeNull();
  });

  it('renders nothing when toolName is undefined', async () => {
    const { queryByText } = await renderWithProviders(
      <ToolIndicator toolName={undefined as unknown as null} />,
    );
    expect(queryByText(/Using/)).toBeNull();
  });

  it('renders without crashing', async () => {
    await renderWithProviders(<ToolIndicator toolName="test_tool" />);
  });
});
