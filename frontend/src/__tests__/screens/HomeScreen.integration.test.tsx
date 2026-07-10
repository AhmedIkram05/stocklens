/**
 * Integration tests for `HomeScreen` UI.
 * Exercises empty state behavior, stats display, history expansion,
 * and navigation to Scan and ReceiptDetails screens.
 */

import React from 'react';
import { fireEvent, waitFor } from '@testing-library/react-native';
import HomeScreen from '@/screens/HomeScreen';
import { renderWithProviders } from '../utils';
import useReceipts from '@/hooks/useReceipts';
import { useNavigation } from '@react-navigation/native';
import { createUserProfile } from '../fixtures';

jest.mock('@/hooks/useReceipts', () => jest.fn());

// Mock useDecryptedImage to return synchronously (avoids act() warning from async decryption)
jest.mock('@/hooks/useDecryptedImage', () => ({
  __esModule: true,
  default: (src: string | null | undefined) => src ?? undefined,
}));

jest.mock('@react-navigation/native', () => {
  const actual = jest.requireActual('@react-navigation/native');
  return {
    ...actual,
    useNavigation: jest.fn(),
  };
});

const mockedUseReceipts = useReceipts as jest.MockedFunction<typeof useReceipts>;
const mockedUseNavigation = useNavigation as jest.MockedFunction<typeof useNavigation>;

describe('HomeScreen', () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  const renderScreen = () => {
    const testUser = createUserProfile({ first_name: 'Alex', uid: 'user-1' });
    return renderWithProviders(<HomeScreen />, {
      providerOverrides: {
        withNavigation: false,
        authValue: {
          userProfile: testUser as any,
          user: { uid: testUser.uid } as any,
        },
      },
    });
  };

  it('shows onboarding empty state and navigates to Scan when CTA pressed', () => {
    const navigateSpy = jest.fn();
    mockedUseNavigation.mockReturnValue({ navigate: navigateSpy } as any);
    mockedUseReceipts.mockReturnValue({
      receipts: [],
      loading: false,
      error: null,
      refetch: jest.fn(),
    });

    const { getByText } = renderScreen();

    expect(getByText('No Receipts Yet')).toBeTruthy();
    fireEvent.press(getByText('Scan Your First Receipt'));

    expect(navigateSpy).toHaveBeenCalledWith('MainTabs', { screen: 'Scan' });
  });

  it('renders stats, toggles history, and opens receipt details', async () => {
    const navigateSpy = jest.fn();
    mockedUseNavigation.mockReturnValue({ navigate: navigateSpy } as any);
    mockedUseReceipts.mockReturnValue({
      receipts: [
        {
          id: '1',
          label: '2 hours ago',
          amount: 80,
          date: '2025-02-01T10:00:00Z',
          time: '9:00',
          image: 'uri://receipt-1',
          source: 'regex',
          confidence: 95,
        },
        {
          id: '2',
          label: 'Yesterday',
          amount: 40,
          date: '2025-01-05T10:00:00Z',
          time: '12:00',
          image: 'uri://receipt-2',
          source: 'cascade',
          confidence: 78,
        },
        {
          id: '3',
          label: 'Last week',
          amount: 20,
          date: '2024-12-15T10:00:00Z',
          time: '15:00',
          image: 'uri://receipt-3',
          source: 'degraded',
          confidence: 45,
        },
        {
          id: '4',
          label: '2 weeks ago',
          amount: 10,
          date: '2024-12-01T10:00:00Z',
          time: '11:00',
          image: 'uri://receipt-4',
          source: 'failed',
          confidence: 0,
        },
      ],
      loading: false,
      error: null,
      refetch: jest.fn(),
    });

    const { getByText, getAllByTestId } = renderScreen();

    await waitFor(() => expect(getByText('Total Money Spent')).toBeTruthy());
    expect(getByText('£150.00')).toBeTruthy();
    expect(getByText('Receipts Scanned')).toBeTruthy();
    expect(getByText('£80.00')).toBeTruthy();

    fireEvent.press(getByText('View all receipts'));
    expect(getByText('Show Less')).toBeTruthy();

    fireEvent.press(getAllByTestId('receipt-card')[0]);
    expect(navigateSpy).toHaveBeenCalledWith(
      'ReceiptDetails',
      expect.objectContaining({ receiptId: '1', totalAmount: 80, source: 'regex', confidence: 95 }),
    );
  });
});
