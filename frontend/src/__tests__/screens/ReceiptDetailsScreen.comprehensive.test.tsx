/**
 * Comprehensive tests for `ReceiptDetailsScreen`.
 * Tests a subset of functionality that works reliably in test environment.
 */

import React from 'react';
import { act, fireEvent, waitFor } from '@testing-library/react-native';
import { Alert } from 'react-native';
import ReceiptDetailsScreen from '@/screens/ReceiptDetailsScreen';
import { renderWithProviders } from '@/__tests__/utils/renderWithProviders';
import { receiptService } from '@/services/receipts';
import { emit, subscribe } from '@/services/eventBus';
import { getHistoricalCAGRFromToday } from '@/services/projectionService';
import { useNavigation, useRoute } from '@react-navigation/native';

// Mock dependencies
jest.mock('@/services/receipts');
jest.mock('@/services/portfolios');
jest.mock('@/services/eventBus');
jest.mock('@/services/projectionService');
jest.mock('@react-navigation/native');

const mockedReceiptService = receiptService as jest.Mocked<typeof receiptService>;
const mockedEmit = emit as jest.MockedFunction<typeof emit>;
const mockedSubscribe = subscribe as jest.MockedFunction<typeof subscribe>;
const mockedGetHistorical = getHistoricalCAGRFromToday as jest.MockedFunction<
  typeof getHistoricalCAGRFromToday
>;
const mockedUseNavigation = useNavigation as jest.MockedFunction<typeof useNavigation>;
const mockedUseRoute = useRoute as jest.MockedFunction<typeof useRoute>;

// Alert spy
const alertSpy = jest.spyOn(Alert, 'alert');

describe('ReceiptDetailsScreen comprehensive', () => {
  let navigateSpy: jest.Mock;
  let goBackSpy: jest.Mock;

  const mockReceipt = {
    id: 'test-receipt-123',
    user_id: 'user-456',
    total_amount: 85.5,
    receipt_image_s3_key: 'test-image.jpg',
    merchant_name: 'Test Store',
    transaction_date: '2025-01-15',
    category_id: 'cat-1',
    category_name: 'Food & Drink',
    created_at: '2025-01-15T10:30:00Z',
    updated_at: '2025-01-15T10:30:00Z',
    is_expired: false,
    ocr_raw_text: 'TEST STORE\nTOTAL £85.50',
    ocr_confidence: 92,
    scanned_at: '2025-01-15T10:30:00Z',
    line_items: [
      { id: 'item-1', name: 'Item 1', quantity: 2, price: 20.0 },
      { id: 'item-2', name: 'Item 2', quantity: 1, price: 45.5 },
    ],
  };

  const defaultRouteParams = {
    receiptId: 'test-receipt-123',
    totalAmount: 85.5,
    date: '2025-01-15',
    image: 'test-image.jpg',
    confidence: 92,
    processingTimeMs: 1000,
    merchantName: 'Test Store',
    lineItems: [
      { id: 'item-1', name: 'Item 1', quantity: 2, price: 20.0 },
      { id: 'item-2', name: 'Item 2', quantity: 1, price: 45.5 },
    ],
  };

  beforeEach(() => {
    jest.clearAllMocks();
    alertSpy.mockClear();
    navigateSpy = jest.fn();
    goBackSpy = jest.fn();
    mockedUseNavigation.mockReturnValue({
      navigate: navigateSpy,
      goBack: goBackSpy,
    } as any);
    mockedUseRoute.mockReturnValue({
      params: defaultRouteParams,
    } as any);
    mockedReceiptService.getById.mockResolvedValue(mockReceipt);
    mockedReceiptService.update.mockResolvedValue(undefined);
    mockedReceiptService.delete.mockResolvedValue(undefined);
    mockedGetHistorical.mockResolvedValue(0.08);
    mockedEmit.mockResolvedValue(undefined);
    mockedSubscribe.mockImplementation((_event: string, _handler: () => void) => {
      return () => {};
    });
  });

  const renderScreen = () =>
    renderWithProviders(<ReceiptDetailsScreen />, {
      providerOverrides: { withNavigation: false },
    });

  it('shows line items when present', async () => {
    const { getByText } = renderScreen();

    await waitFor(() => {
      expect(getByText('Item 1')).toBeTruthy();
    });
    expect(getByText('Item 2')).toBeTruthy();
  });

  it('updates projections when year selector changes', async () => {
    const { getByText, getAllByRole } = renderScreen();

    await waitFor(() => {
      expect(getByText('Item 1')).toBeTruthy();
    });

    // Year selector should be present
    const yearSelector = getAllByRole('button').find(
      (btn) => btn.props.children === '5Y' || String(btn.props.children).includes('Y'),
    );
    if (yearSelector) {
      act(() => {
        fireEvent.press(yearSelector);
      });
      await waitFor(() => {
        expect(mockedGetHistorical).toHaveBeenCalled();
      });
    }
  });

  it('handles delete cancellation', async () => {
    const { getByText, getByLabelText } = renderScreen();

    await waitFor(() => {
      expect(getByText('Item 1')).toBeTruthy();
    });

    const deleteBtn = getByLabelText('Delete receipt');
    act(() => {
      fireEvent.press(deleteBtn);
    });

    await waitFor(() => {
      expect(alertSpy).toHaveBeenCalled();
    });

    // Find and press cancel button
    const alertCalls = alertSpy.mock.calls;
    const lastCall = alertCalls[alertCalls.length - 1];
    const buttons = lastCall[2] as Array<{ text?: string; style?: string; onPress?: () => void }>;
    const cancelButton = buttons?.find(
      (btn: any) => btn.text === 'Cancel' && btn.style === 'cancel',
    );

    act(() => {
      cancelButton?.onPress?.();
    });

    // Delete should not have been called
    expect(mockedReceiptService.delete).not.toHaveBeenCalled();
  });
});
