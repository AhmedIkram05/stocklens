import React from 'react';
import { fireEvent } from '@testing-library/react-native';
import { renderWithProviders } from '@/__tests__/utils';
import EmptyState from '@/components/EmptyState';

describe('EmptyState', () => {
  it('renders title', async () => {
    const { getByText } = await renderWithProviders(<EmptyState title="No receipts found" />);
    expect(getByText('No receipts found')).toBeTruthy();
  });

  it('renders subtitle when provided', async () => {
    const { getByText } = await renderWithProviders(
      <EmptyState title="Empty" subtitle="Start by scanning a receipt" />,
    );
    expect(getByText('Start by scanning a receipt')).toBeTruthy();
  });

  it('does not render subtitle when not provided', async () => {
    const { queryByText } = await renderWithProviders(<EmptyState title="Empty" />);
    expect(queryByText('Start by scanning a receipt')).toBeNull();
  });

  it('renders primary button when primaryText is provided', async () => {
    const { getByText } = await renderWithProviders(
      <EmptyState title="Empty" primaryText="Scan Receipt" />,
    );
    expect(getByText('Scan Receipt')).toBeTruthy();
  });

  it('does not render button when primaryText is not provided', async () => {
    const { queryByText } = await renderWithProviders(<EmptyState title="Empty" />);
    expect(queryByText('Scan Receipt')).toBeNull();
  });

  it('calls onPrimaryPress when button is pressed', async () => {
    const onPress = jest.fn();
    const { getByText } = await renderWithProviders(
      <EmptyState title="Empty" primaryText="Scan" onPrimaryPress={onPress} />,
    );
    await fireEvent.press(getByText('Scan'));
    expect(onPress).toHaveBeenCalledTimes(1);
  });

  it('uses default iconName when not provided', async () => {
    const { getByText } = await renderWithProviders(<EmptyState title="Empty" />);
    expect(getByText('Empty')).toBeTruthy();
  });

  it('uses custom iconName when provided', async () => {
    const { getByText } = await renderWithProviders(<EmptyState title="Empty" iconName="camera" />);
    expect(getByText('Empty')).toBeTruthy();
  });
});
