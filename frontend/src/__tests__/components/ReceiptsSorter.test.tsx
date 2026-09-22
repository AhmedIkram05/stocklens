/**
 * Tests for `ReceiptsSorter` component.
 * Covers sorting toggles, active state, and direction indicators.
 */

import React from 'react';
import { fireEvent } from '@testing-library/react-native';
import ReceiptsSorter from '@/components/ReceiptsSorter';
import { renderWithProviders } from '@/__tests__/utils/renderWithProviders';

type SortBy = 'date' | 'amount';
type SortDirection = 'asc' | 'desc';
type OnSortChange = (sortBy: SortBy, sortDirection: SortDirection) => void;

const defaultProps: {
  sortBy: SortBy;
  sortDirection: SortDirection;
  onSortChange: jest.Mock<OnSortChange>;
} = {
  sortBy: 'date',
  sortDirection: 'desc',
  onSortChange: jest.fn(),
};

describe('ReceiptsSorter', () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  const renderSorter = (overrides?: Partial<typeof defaultProps>) =>
    renderWithProviders(<ReceiptsSorter {...defaultProps} {...overrides} />, {
      providerOverrides: { withNavigation: false },
    });

  it('renders sort options (Date, Amount)', async () => {
    const { getByText } = await renderSorter();
    expect(getByText('Date')).toBeTruthy();
    expect(getByText('Amount')).toBeTruthy();
  });

  it('shows active state for the currently selected sort field', async () => {
    const { getByText } = await renderSorter();
    expect(getByText('↓')).toBeTruthy();
  });

  it('toggles direction when same sort field is pressed', async () => {
    const onSortChange = jest.fn();
    const { getByText } = await renderSorter({ onSortChange });

    await fireEvent.press(getByText('Date'));

    expect(onSortChange).toHaveBeenCalledWith('date', 'asc');
  });

  it('resets direction when switching sort fields', async () => {
    const onSortChange = jest.fn();
    const { getByText } = await renderSorter({ onSortChange });

    await fireEvent.press(getByText('Amount'));

    expect(onSortChange).toHaveBeenCalledWith('amount', 'asc');
  });

  it('switches to desc default for date sort', async () => {
    const onSortChange = jest.fn();
    const { getByText } = await renderSorter({
      sortBy: 'amount',
      sortDirection: 'asc',
      onSortChange,
    });

    await fireEvent.press(getByText('Date'));

    expect(onSortChange).toHaveBeenCalledWith('date', 'desc');
  });

  it('shows the correct arrow for asc direction', async () => {
    const { getByText } = await renderSorter({
      sortBy: 'amount',
      sortDirection: 'asc',
    });
    expect(getByText('↑')).toBeTruthy();
  });

  it('shows the correct arrow for desc direction', async () => {
    const { getByText } = await renderSorter({
      sortBy: 'amount',
      sortDirection: 'desc',
    });
    expect(getByText('↓')).toBeTruthy();
  });
});
