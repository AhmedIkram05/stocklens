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
  it('returns null for empty results', async () => {
    const { queryByText } = await renderWithProviders(<ToolResultsAccordion results={[]} />);
    // Component returns null but providers render; verify no accordion content
    expect(queryByText(/./)).toBeNull();
  });

  it('returns null for undefined results', async () => {
    const { queryByText } = await renderWithProviders(
      <ToolResultsAccordion results={undefined as any} />,
    );
    expect(queryByText(/./)).toBeNull();
  });

  it('renders accordion header for a single result', async () => {
    const { getByText } = await renderWithProviders(
      <ToolResultsAccordion
        results={[{ toolName: 'get_portfolio_summary', result: { name: 'Test' } }]}
      />,
    );
    expect(getByText('get_portfolio_summary')).toBeTruthy();
  });

  it('collapses by default — content is not visible', async () => {
    const { queryByText } = await renderWithProviders(
      <ToolResultsAccordion
        results={[{ toolName: 'get_portfolio_summary', result: { name: 'Test' } }]}
      />,
    );
    expect(queryByText('Test')).toBeNull();
  });

  it('expands content on header press', async () => {
    const { getByText } = await renderWithProviders(
      <ToolResultsAccordion
        results={[{ toolName: 'get_portfolio_summary', result: { name: 'Test' } }]}
      />,
    );

    await fireEvent.press(getByText('get_portfolio_summary'));
    expect(getByText('Test')).toBeTruthy();
  });

  it('collapses content on second header press', async () => {
    const { getByText, queryByText } = await renderWithProviders(
      <ToolResultsAccordion
        results={[{ toolName: 'get_portfolio_summary', result: { name: 'Test' } }]}
      />,
    );

    await fireEvent.press(getByText('get_portfolio_summary'));
    expect(getByText('Test')).toBeTruthy();

    await fireEvent.press(getByText('get_portfolio_summary'));
    expect(queryByText('Test')).toBeNull();
  });

  it('supports single-expand model — expansion collapses previous', async () => {
    const results = [
      { toolName: 'tool_a', result: { name: 'Alpha' } },
      { toolName: 'tool_b', result: { name: 'Beta' } },
    ];
    const { getByText, queryByText } = await renderWithProviders(
      <ToolResultsAccordion results={results} />,
    );

    // Expand first
    await fireEvent.press(getByText('tool_a'));
    expect(getByText(/Alpha/)).toBeTruthy();
    expect(queryByText(/Beta/)).toBeNull();

    // Expand second — first should collapse
    await fireEvent.press(getByText('tool_b'));
    expect(queryByText(/Alpha/)).toBeNull();
    expect(getByText(/Beta/)).toBeTruthy();
  });

  it('renders all result headers', async () => {
    const results = [
      { toolName: 'tool_a', result: { value: 1 } },
      { toolName: 'tool_b', result: { value: 2 } },
      { toolName: 'tool_c', result: { value: 3 } },
    ];
    const { getByText } = await renderWithProviders(<ToolResultsAccordion results={results} />);

    expect(getByText('tool_a')).toBeTruthy();
    expect(getByText('tool_b')).toBeTruthy();
    expect(getByText('tool_c')).toBeTruthy();
  });
});
