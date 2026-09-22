import React from 'react';
import { fireEvent } from '@testing-library/react-native';
import { renderWithProviders } from '@/__tests__/utils';
import StockCard from '@/components/StockCard';

describe('StockCard', () => {
  const defaultProps = {
    name: 'Apple Inc.',
    futureDisplay: '$1,234.56',
    formattedAmount: '$1,000.00',
    percentDisplay: '+23.5%',
    gainDisplay: '+$234.56',
  };

  it('renders name and financial values', async () => {
    const { getByText } = await renderWithProviders(<StockCard {...defaultProps} />);
    expect(getByText('Apple Inc.')).toBeTruthy();
    expect(getByText('$1,234.56')).toBeTruthy();
    expect(getByText('+23.5%')).toBeTruthy();
    expect(getByText('+$234.56')).toBeTruthy();
    expect(getByText('Return')).toBeTruthy();
    expect(getByText('Gained')).toBeTruthy();
  });

  it('renders ticker when provided', async () => {
    const { getByText } = await renderWithProviders(<StockCard {...defaultProps} ticker="AAPL" />);
    expect(getByText('AAPL')).toBeTruthy();
  });

  it('does not render ticker when not provided', async () => {
    const { queryByText } = await renderWithProviders(<StockCard {...defaultProps} />);
    expect(queryByText('AAPL')).toBeNull();
  });

  it('renders badge when badgeText is provided', async () => {
    const { getByText } = await renderWithProviders(<StockCard {...defaultProps} badgeText="Popular" />);
    expect(getByText('Popular')).toBeTruthy();
  });

  it('calls onPress when pressed', async () => {
    const onPress = jest.fn();
    const { getByText } = await renderWithProviders(<StockCard {...defaultProps} onPress={onPress} />);
    await fireEvent.press(getByText('Apple Inc.'));
    expect(onPress).toHaveBeenCalledTimes(1);
  });

  it('applies isLast style (no right margin)', async () => {
    const { getByText } = await renderWithProviders(<StockCard {...defaultProps} isLast />);
    expect(getByText('Apple Inc.')).toBeTruthy();
  });

  it('uses custom valueColor', async () => {
    const { getByText } = await renderWithProviders(<StockCard {...defaultProps} valueColor="#ff0000" />);
    expect(getByText('+23.5%')).toBeTruthy();
    expect(getByText('+$234.56')).toBeTruthy();
  });

  it('uses default valueColor when not provided', async () => {
    const { getByText } = await renderWithProviders(<StockCard {...defaultProps} />);
    expect(getByText('+23.5%')).toBeTruthy();
    expect(getByText('+$234.56')).toBeTruthy();
  });

  it('uses custom cardWidth', async () => {
    const { getByText } = await renderWithProviders(<StockCard {...defaultProps} cardWidth={300} />);
    expect(getByText('Apple Inc.')).toBeTruthy();
  });
});
