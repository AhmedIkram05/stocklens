/**
 * Tests for `ReceiptExtractionDetails` — source badge, confidence bar and
 * processing-time formatting.
 */

import React from 'react';
import { renderWithProviders } from '../utils/renderWithProviders';
import ReceiptExtractionDetails from '@/components/ReceiptExtractionDetails';

describe('ReceiptExtractionDetails', () => {
  const render = (props: React.ComponentProps<typeof ReceiptExtractionDetails>) =>
    renderWithProviders(<ReceiptExtractionDetails {...props} />, {
      providerOverrides: { withNavigation: false },
    });

  it('renders nothing without a source', async () => {
    const { queryByText } = await render({ source: undefined, confidencePct: 90 });
    expect(queryByText('Extraction Details')).toBeNull();
  });

  it('renders the source badge, confidence and processing time', async () => {
    const { getByText } = await render({
      source: 'cascade',
      confidencePct: 92,
      processingTimeMs: 1500,
    });
    expect(getByText('Extraction Details')).toBeTruthy();
    expect(getByText('AI Enhanced')).toBeTruthy();
    expect(getByText('92%')).toBeTruthy();
    expect(getByText('1.5s')).toBeTruthy();
  });

  it('formats sub-second processing time in ms and hides zero confidence', async () => {
    const { getByText, queryByText } = await render({
      source: 'regex',
      confidencePct: 0,
      processingTimeMs: 350,
    });
    expect(getByText('Regex')).toBeTruthy();
    expect(getByText('350ms')).toBeTruthy();
    expect(queryByText('0%')).toBeNull();
  });
});
