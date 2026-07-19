import React from 'react';
import ToolIndicator from '@/components/chat/ToolIndicator';
import { renderWithProviders } from '@/__tests__/utils/renderWithProviders';

describe('ToolIndicator', () => {
  it('renders tool name when tool is active', () => {
    const { getByText } = renderWithProviders(<ToolIndicator toolName="get_portfolio_summary" />);
    expect(getByText(/get_portfolio_summary/)).toBeTruthy();
  });

  it('displays "Using" prefix in the label', () => {
    const { getByText } = renderWithProviders(<ToolIndicator toolName="get_market_quote" />);
    expect(getByText(/Using get_market_quote/)).toBeTruthy();
  });

  it('renders nothing when toolName is null', () => {
    const { queryByText } = renderWithProviders(<ToolIndicator toolName={null} />);
    // Should render nothing — no text should be visible
    expect(queryByText(/Using/)).toBeNull();
  });

  it('renders nothing when toolName is undefined', () => {
    const { queryByText } = renderWithProviders(
      <ToolIndicator toolName={undefined as unknown as null} />,
    );
    expect(queryByText(/Using/)).toBeNull();
  });

  it('renders without crashing', () => {
    expect(() => renderWithProviders(<ToolIndicator toolName="test_tool" />)).not.toThrow();
  });
});
