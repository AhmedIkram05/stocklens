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

  it('renders amount and label', async () => {
    mockUseDecryptedImage.mockReturnValue(undefined);
    const { getByText } = await renderWithProviders(<ReceiptCard amount="$25.00" label="Coffee" />);
    expect(getByText('$25.00')).toBeTruthy();
    expect(getByText('Coffee')).toBeTruthy();
  });

  it('shows image when resolvedImage is available', async () => {
    mockUseDecryptedImage.mockReturnValue('https://example.com/receipt.jpg');
    const { queryByTestId } = await renderWithProviders(
      <ReceiptCard amount="$25.00" label="Coffee" image="encrypted-uri" />,
    );
    expect(queryByTestId('receipt-card-image')).toBeTruthy();
    expect(queryByTestId('receipt-card-placeholder')).toBeNull();
  });

  it('shows placeholder when no image', async () => {
    mockUseDecryptedImage.mockReturnValue(undefined);
    const { queryByTestId } = await renderWithProviders(<ReceiptCard amount="$25.00" label="Coffee" />);
    expect(queryByTestId('receipt-card-placeholder')).toBeTruthy();
    expect(queryByTestId('receipt-card-image')).toBeNull();
  });

  it('shows placeholder when image uri is undefined but resolvedImage is falsy', async () => {
    mockUseDecryptedImage.mockReturnValue(undefined);
    const { getByTestId } = await renderWithProviders(
      <ReceiptCard amount="$25.00" label="Coffee" image={undefined} />,
    );
    expect(getByTestId('receipt-card-placeholder')).toBeTruthy();
  });

  it('shows time when provided', async () => {
    mockUseDecryptedImage.mockReturnValue(undefined);
    const { getByText } = await renderWithProviders(
      <ReceiptCard amount="$25.00" label="Coffee" time="2 hours ago" />,
    );
    expect(getByText('2 hours ago')).toBeTruthy();
  });

  it('does not show time when not provided', async () => {
    mockUseDecryptedImage.mockReturnValue(undefined);
    const { queryByText } = await renderWithProviders(<ReceiptCard amount="$25.00" label="Coffee" />);
    expect(queryByText('2 hours ago')).toBeNull();
  });

  it('shows category chip when category is provided', async () => {
    mockUseDecryptedImage.mockReturnValue(undefined);
    const { getByText } = await renderWithProviders(
      <ReceiptCard amount="$25.00" label="Coffee" category="Food & Drink" />,
    );
    expect(getByText('Food & Drink')).toBeTruthy();
  });

  it('does not show category chip when category is null', async () => {
    mockUseDecryptedImage.mockReturnValue(undefined);
    const { queryByText } = await renderWithProviders(
      <ReceiptCard amount="$25.00" label="Coffee" category={null} />,
    );
    expect(queryByText('FOOD & DRINK')).toBeNull();
  });

  it('shows source badge when source is provided', async () => {
    mockUseDecryptedImage.mockReturnValue(undefined);
    const { getByText } = await renderWithProviders(
      <ReceiptCard amount="$25.00" label="Coffee" source="regex" />,
    );
    expect(getByText('Regex')).toBeTruthy();
  });

  it('shows AI Enhanced badge for cascade source', async () => {
    mockUseDecryptedImage.mockReturnValue(undefined);
    const { getByText } = await renderWithProviders(
      <ReceiptCard amount="$25.00" label="Coffee" source="cascade" />,
    );
    expect(getByText('AI Enhanced')).toBeTruthy();
  });

  it('does not show source badge when source is not provided', async () => {
    mockUseDecryptedImage.mockReturnValue(undefined);
    const { queryByText } = await renderWithProviders(<ReceiptCard amount="$25.00" label="Coffee" />);
    expect(queryByText('REGEX')).toBeNull();
  });

  it('calls onPress when pressed', async () => {
    mockUseDecryptedImage.mockReturnValue(undefined);
    const onPress = jest.fn();
    const { getByTestId } = await renderWithProviders(
      <ReceiptCard amount="$25.00" label="Coffee" onPress={onPress} />,
    );
    await fireEvent.press(getByTestId('receipt-card'));
    expect(onPress).toHaveBeenCalledTimes(1);
  });

  it('accepts custom style', async () => {
    mockUseDecryptedImage.mockReturnValue(undefined);
    const { getByTestId } = await renderWithProviders(
      <ReceiptCard amount="$25.00" label="Coffee" style={{ marginTop: 10 }} />,
    );
    expect(getByTestId('receipt-card')).toBeTruthy();
  });
});
