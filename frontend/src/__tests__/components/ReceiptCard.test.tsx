import React from 'react';
import { fireEvent } from '@testing-library/react-native';
import { renderWithProviders } from '@/__tests__/utils';
import ReceiptCard from '@/components/ReceiptCard';

const mockUseDecryptedImage = jest.fn();
jest.mock('@/hooks/useDecryptedImage', () => ({
  __esModule: true,
  default: (...args: any[]) => mockUseDecryptedImage(...args),
}));

describe('ReceiptCard', () => {
  beforeEach(() => {
    mockUseDecryptedImage.mockReset();
  });

  it('renders amount and label', () => {
    mockUseDecryptedImage.mockReturnValue(undefined);
    const { getByText } = renderWithProviders(<ReceiptCard amount="$25.00" label="Coffee" />);
    expect(getByText('$25.00')).toBeTruthy();
    expect(getByText('Coffee')).toBeTruthy();
  });

  it('shows image when resolvedImage is available', () => {
    mockUseDecryptedImage.mockReturnValue('https://example.com/receipt.jpg');
    const { queryByTestId } = renderWithProviders(
      <ReceiptCard amount="$25.00" label="Coffee" image="encrypted-uri" />,
    );
    expect(queryByTestId('receipt-card-image')).toBeTruthy();
    expect(queryByTestId('receipt-card-placeholder')).toBeNull();
  });

  it('shows placeholder when no image', () => {
    mockUseDecryptedImage.mockReturnValue(undefined);
    const { queryByTestId } = renderWithProviders(<ReceiptCard amount="$25.00" label="Coffee" />);
    expect(queryByTestId('receipt-card-placeholder')).toBeTruthy();
    expect(queryByTestId('receipt-card-image')).toBeNull();
  });

  it('shows placeholder when image uri is undefined but resolvedImage is falsy', () => {
    mockUseDecryptedImage.mockReturnValue(undefined);
    const { getByTestId } = renderWithProviders(
      <ReceiptCard amount="$25.00" label="Coffee" image={undefined} />,
    );
    expect(getByTestId('receipt-card-placeholder')).toBeTruthy();
  });

  it('shows time when provided', () => {
    mockUseDecryptedImage.mockReturnValue(undefined);
    const { getByText } = renderWithProviders(
      <ReceiptCard amount="$25.00" label="Coffee" time="2 hours ago" />,
    );
    expect(getByText('2 hours ago')).toBeTruthy();
  });

  it('does not show time when not provided', () => {
    mockUseDecryptedImage.mockReturnValue(undefined);
    const { queryByText } = renderWithProviders(<ReceiptCard amount="$25.00" label="Coffee" />);
    expect(queryByText('2 hours ago')).toBeNull();
  });

  it('shows category chip when category is provided', () => {
    mockUseDecryptedImage.mockReturnValue(undefined);
    const { getByText } = renderWithProviders(
      <ReceiptCard amount="$25.00" label="Coffee" category="Food & Drink" />,
    );
    expect(getByText('Food & Drink')).toBeTruthy();
  });

  it('does not show category chip when category is null', () => {
    mockUseDecryptedImage.mockReturnValue(undefined);
    const { queryByText } = renderWithProviders(
      <ReceiptCard amount="$25.00" label="Coffee" category={null} />,
    );
    expect(queryByText('FOOD & DRINK')).toBeNull();
  });

  it('shows source badge when source is provided', () => {
    mockUseDecryptedImage.mockReturnValue(undefined);
    const { getByText } = renderWithProviders(
      <ReceiptCard amount="$25.00" label="Coffee" source="regex" />,
    );
    expect(getByText('Regex')).toBeTruthy();
  });

  it('shows AI Enhanced badge for cascade source', () => {
    mockUseDecryptedImage.mockReturnValue(undefined);
    const { getByText } = renderWithProviders(
      <ReceiptCard amount="$25.00" label="Coffee" source="cascade" />,
    );
    expect(getByText('AI Enhanced')).toBeTruthy();
  });

  it('does not show source badge when source is not provided', () => {
    mockUseDecryptedImage.mockReturnValue(undefined);
    const { queryByText } = renderWithProviders(<ReceiptCard amount="$25.00" label="Coffee" />);
    expect(queryByText('REGEX')).toBeNull();
  });

  it('calls onPress when pressed', () => {
    mockUseDecryptedImage.mockReturnValue(undefined);
    const onPress = jest.fn();
    const { getByTestId } = renderWithProviders(
      <ReceiptCard amount="$25.00" label="Coffee" onPress={onPress} />,
    );
    fireEvent.press(getByTestId('receipt-card'));
    expect(onPress).toHaveBeenCalledTimes(1);
  });

  it('accepts custom style', () => {
    mockUseDecryptedImage.mockReturnValue(undefined);
    const { getByTestId } = renderWithProviders(
      <ReceiptCard amount="$25.00" label="Coffee" style={{ marginTop: 10 }} />,
    );
    expect(getByTestId('receipt-card')).toBeTruthy();
  });
});
