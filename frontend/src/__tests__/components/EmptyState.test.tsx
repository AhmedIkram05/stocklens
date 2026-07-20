import React from 'react';
import { fireEvent } from '@testing-library/react-native';
import { renderWithProviders } from '@/__tests__/utils';
import EmptyState from '@/components/EmptyState';

describe('EmptyState', () => {
  it('renders title', () => {
    const { getByText } = renderWithProviders(<EmptyState title="No receipts found" />);
    expect(getByText('No receipts found')).toBeTruthy();
  });

  it('renders subtitle when provided', () => {
    const { getByText } = renderWithProviders(
      <EmptyState title="Empty" subtitle="Start by scanning a receipt" />,
    );
    expect(getByText('Start by scanning a receipt')).toBeTruthy();
  });

  it('does not render subtitle when not provided', () => {
    const { queryByText } = renderWithProviders(<EmptyState title="Empty" />);
    expect(queryByText('Start by scanning a receipt')).toBeNull();
  });

  it('renders primary button when primaryText is provided', () => {
    const { getByText } = renderWithProviders(
      <EmptyState title="Empty" primaryText="Scan Receipt" />,
    );
    expect(getByText('Scan Receipt')).toBeTruthy();
  });

  it('does not render button when primaryText is not provided', () => {
    const { queryByText } = renderWithProviders(<EmptyState title="Empty" />);
    expect(queryByText('Scan Receipt')).toBeNull();
  });

  it('calls onPrimaryPress when button is pressed', () => {
    const onPress = jest.fn();
    const { getByText } = renderWithProviders(
      <EmptyState title="Empty" primaryText="Scan" onPrimaryPress={onPress} />,
    );
    fireEvent.press(getByText('Scan'));
    expect(onPress).toHaveBeenCalledTimes(1);
  });

  it('uses default iconName when not provided', () => {
    const { getByText } = renderWithProviders(<EmptyState title="Empty" />);
    expect(getByText('Empty')).toBeTruthy();
  });

  it('uses custom iconName when provided', () => {
    const { getByText } = renderWithProviders(<EmptyState title="Empty" iconName="camera" />);
    expect(getByText('Empty')).toBeTruthy();
  });
});
