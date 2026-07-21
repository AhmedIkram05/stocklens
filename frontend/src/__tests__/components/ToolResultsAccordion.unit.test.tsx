/**
 * Unit tests for ToolResultsAccordion.
 *
 * Verifies: empty/undefined results return null, single item expand/collapse,
 * multiple items toggle, single-expand model, toggle callback behavior.
 */

import React from 'react';
import { fireEvent } from '@testing-library/react-native';
import { renderWithProviders } from '@/__tests__/utils/renderWithProviders';
import ToolResultsAccordion from '@/components/chat/ToolResultsAccordion';

describe('ToolResultsAccordion', () => {
  it('returns null for empty results', () => {
    const { queryByText } = renderWithProviders(<ToolResultsAccordion results={[]} />);
    // Component returns null but providers render; verify no accordion content
    expect(queryByText(/./)).toBeNull();
  });

  it('returns null for undefined results', () => {
    const { queryByText } = renderWithProviders(
      <ToolResultsAccordion results={undefined as any} />,
    );
    expect(queryByText(/./)).toBeNull();
  });

  it('renders accordion header for a single result', () => {
    const { getByText } = renderWithProviders(
      <ToolResultsAccordion
        results={[{ toolName: 'get_portfolio_summary', result: { name: 'Test' } }]}
      />,
    );
    expect(getByText('get_portfolio_summary')).toBeTruthy();
  });

  it('collapses by default — content is not visible', () => {
    const { queryByText } = renderWithProviders(
      <ToolResultsAccordion
        results={[{ toolName: 'get_portfolio_summary', result: { name: 'Test' } }]}
      />,
    );
    expect(queryByText('Test')).toBeNull();
  });

  it('expands content on header press', () => {
    const { getByText } = renderWithProviders(
      <ToolResultsAccordion
        results={[{ toolName: 'get_portfolio_summary', result: { name: 'Test' } }]}
      />,
    );

    fireEvent.press(getByText('get_portfolio_summary'));
    expect(getByText('Test')).toBeTruthy();
  });

  it('collapses content on second header press', () => {
    const { getByText, queryByText } = renderWithProviders(
      <ToolResultsAccordion
        results={[{ toolName: 'get_portfolio_summary', result: { name: 'Test' } }]}
      />,
    );

    fireEvent.press(getByText('get_portfolio_summary'));
    expect(getByText('Test')).toBeTruthy();

    fireEvent.press(getByText('get_portfolio_summary'));
    expect(queryByText('Test')).toBeNull();
  });

  it('supports single-expand model — expansion collapses previous', () => {
    const results = [
      { toolName: 'tool_a', result: { name: 'Alpha' } },
      { toolName: 'tool_b', result: { name: 'Beta' } },
    ];
    const { getByText, queryByText } = renderWithProviders(
      <ToolResultsAccordion results={results} />,
    );

    // Expand first
    fireEvent.press(getByText('tool_a'));
    expect(getByText(/Alpha/)).toBeTruthy();
    expect(queryByText(/Beta/)).toBeNull();

    // Expand second — first should collapse
    fireEvent.press(getByText('tool_b'));
    expect(queryByText(/Alpha/)).toBeNull();
    expect(getByText(/Beta/)).toBeTruthy();
  });

  it('renders all result headers', () => {
    const results = [
      { toolName: 'tool_a', result: { value: 1 } },
      { toolName: 'tool_b', result: { value: 2 } },
      { toolName: 'tool_c', result: { value: 3 } },
    ];
    const { getByText } = renderWithProviders(<ToolResultsAccordion results={results} />);

    expect(getByText('tool_a')).toBeTruthy();
    expect(getByText('tool_b')).toBeTruthy();
    expect(getByText('tool_c')).toBeTruthy();
  });
});
