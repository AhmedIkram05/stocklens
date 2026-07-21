/**
 * Unit tests for `useReceiptCapture` hook.
 * Tests the photo → scan → confirm → navigate workflow.
 */

import { act, renderHook, waitFor } from '@testing-library/react-native';
import { useReceiptCapture } from '@/hooks/useReceiptCapture';
import { receiptService } from '@/services/receipts';
import { emit } from '@/services/eventBus';
import showConfirmationPrompt from '@/components/ConfirmationPrompt';
import { Alert } from 'react-native';

// Mock dependencies
jest.mock('@/services/receipts');
jest.mock('@/services/eventBus');
jest.mock('@/components/ConfirmationPrompt');

const mockedReceiptService = jest.mocked(receiptService);
const mockedEmit = jest.mocked(emit);
const mockedShowConfirmationPrompt = jest.mocked(showConfirmationPrompt);

describe('useReceiptCapture', () => {
  const navigationMock = { navigate: jest.fn() };
  const onResetCameraMock = jest.fn();

  beforeEach(() => {
    jest.clearAllMocks();
    // Mock Alert.alert
    jest.spyOn(Alert, 'alert').mockImplementation(() => {});
  });

  afterEach(() => {
    jest.restoreAllMocks();
  });

  const createHookResult = (overrides = {}) => {
    return renderHook(() =>
      useReceiptCapture({
        navigation: navigationMock,
        onResetCamera: onResetCameraMock,
        ...overrides,
      }),
    );
  };

  it('initializes with correct default state', () => {
    const { result } = createHookResult();
    expect(result.current.state.processing).toBe(false);
    expect(result.current.state.ocrRaw).toBeNull();
    expect(result.current.state.manualModalVisible).toBe(false);
    expect(result.current.state.manualEntryText).toBe('');
    expect(result.current.pendingRef.current).toEqual({
      scanResponse: null,
      photoUri: null,
    });
  });

  it('resets workflow state correctly', () => {
    const { result } = createHookResult();

    // Set some state
    result.current.actions.setProcessing(true);
    result.current.actions.setOcrRaw('test text');
    result.current.actions.setManualModalVisible(true);
    result.current.actions.setManualEntryText('12.34');
    result.current.pendingRef.current = {
      scanResponse: {
        id: 'test-123',
        extraction: { merchant_name: null, total: null, date: null, currency: 'GBP', items: [] },
        raw_text: '',
        source: 'regex',
        confidence: 0,
        processing_time_ms: 0,
      },
      photoUri: 'test-uri.jpg',
    };

    // Reset
    result.current.actions.resetWorkflowState();

    // Verify reset
    expect(result.current.state.processing).toBe(false);
    expect(result.current.state.ocrRaw).toBeNull();
    expect(result.current.state.manualModalVisible).toBe(false);
    expect(result.current.state.manualEntryText).toBe('');
    expect(result.current.pendingRef.current).toEqual({
      scanResponse: null,
      photoUri: null,
    });
  });

  it('processes receipt successfully', async () => {
    const { result } = createHookResult();
    const photoUri = 'test-photo.jpg';

    // Mock service response
    const mockScanResponse = {
      id: 'scan-789',
      extraction: {
        total: 45.67,
        currency: 'GBP',
        merchant_name: 'Test Store',
        date: '2025-01-15',
        items: [],
      },
      raw_text: 'TOTAL £45.67',
      source: 'regex',
      confidence: 95,
      processing_time_ms: 350,
    };
    mockedReceiptService.scan.mockResolvedValue(mockScanResponse);

    // Mock confirmation prompt
    mockedShowConfirmationPrompt.mockImplementation((amount, callbacks) => {
      callbacks.onConfirm();
    });

    // Process receipt
    await act(async () => {
      result.current.actions.processReceipt({ photoUri });
    });

    // Wait for processing to finish
    await waitFor(() => {
      return result.current.state.processing === false;
    });

    // Verify calls
    expect(mockedReceiptService.scan).toHaveBeenCalledWith(photoUri);
    expect(mockedEmit).toHaveBeenCalledWith('receipts-changed', { id: 'scan-789' });

    // Verify navigation was called
    expect(navigationMock.navigate).toHaveBeenCalled();

    // Verify onResetCamera was called via the mock
    expect(onResetCameraMock).toHaveBeenCalled();
  });

  it('handles foreign currency rejection', async () => {
    const { result } = createHookResult();
    const photoUri = 'foreign-photo.jpg';

    // Mock service response with foreign currency
    const mockScanResponse = {
      id: 'scan-foreign',
      extraction: {
        total: 50.0,
        currency: 'EUR',
        merchant_name: 'Foreign Store',
        date: '2025-01-15',
        items: [],
      },
      raw_text: 'TOTAL €50.00',
      source: 'regex',
      confidence: 90,
      processing_time_ms: 0,
    };
    mockedReceiptService.scan.mockResolvedValue(mockScanResponse);

    // Mock hasForeignCurrency to return true
    const hasForeignCurrencyMock = jest
      .spyOn(require('@/services/receiptParser'), 'hasForeignCurrency')
      .mockImplementation(() => true);

    // Process receipt
    await act(async () => {
      result.current.actions.processReceipt({ photoUri });
    });

    // Wait for processing to finish
    await waitFor(() => {
      return result.current.state.processing === false;
    });

    // Verify draft was discarded
    expect(mockedReceiptService.delete).toHaveBeenCalledWith('scan-foreign');
    hasForeignCurrencyMock.mockRestore();

    // Verify alert was shown
    expect(Alert.alert).toHaveBeenCalledWith(
      'Receipt not in £',
      'Receipts must be entered in GBP (£). Please re-enter the amount in pounds.',
    );
  });

  it('handles scan error gracefully', async () => {
    const { result } = createHookResult();
    const photoUri = 'bad-photo.jpg';

    // Mock service error
    mockedReceiptService.scan.mockRejectedValue(new Error('Scan failed'));

    // Process receipt
    await act(async () => {
      result.current.actions.processReceipt({ photoUri });
    });

    // Wait for processing to finish
    await waitFor(() => {
      return result.current.state.processing === false;
    });

    // Verify error handling
    expect(Alert.alert).toHaveBeenCalledWith('Scan Error', 'Scan failed');
  });

  it('handles manual entry submission', async () => {
    const { result } = createHookResult();
    const amount = 22.5;
    const ocrText = 'MANUAL ENTRY TEST';
    const photoUri = 'manual-photo.jpg';

    // Set up pending state
    act(() => {
      result.current.pendingRef.current = {
        scanResponse: {
          id: 'scan-mock-123',
          extraction: { total: 0, currency: 'GBP', merchant_name: '', date: '', items: [] },
          raw_text: '',
          source: 'regex',
          confidence: 0,
          processing_time_ms: 0,
        },
        photoUri,
      };
    });

    // Mock receipt creation
    const mockCreatedReceipt = {
      id: 'created-456',
      user_id: 'user-123',
      total_amount: 22.5,
      receipt_image_s3_key: photoUri,
      merchant_name: null,
      transaction_date: '2025-01-15',
      category_id: null,
      created_at: '2025-01-15T10:30:00Z',
      updated_at: '2025-01-15T10:30:00Z',
      is_expired: false,
      ocr_raw_text: null,
      ocr_confidence: null,
      line_items: {},
      scanned_at: '2025-01-15T10:30:00Z',
    };
    mockedReceiptService.create.mockResolvedValue(mockCreatedReceipt);

    // Execute action
    await act(async () => {
      result.current.actions.saveAndNavigate(amount, ocrText, photoUri);
    });

    // Wait for processing to finish (wait for navigation or emit)
    await waitFor(() => {
      return navigationMock.navigate.mock.calls.length > 0;
    });

    // Verify calls
    expect(mockedReceiptService.create).toHaveBeenCalledWith({
      receipt_image_s3_key: photoUri,
      total_amount: amount,
      ocr_raw_text: ocrText,
    });

    expect(mockedEmit).toHaveBeenCalledWith('receipts-changed', { id: 'created-456' });
    expect(navigationMock.navigate).toHaveBeenCalled();
    // resetWorkflowState is called internally (verified by state being reset)
    // onResetCamera is called via the mock
    expect(onResetCameraMock).toHaveBeenCalled();
    expect(result.current.state.manualModalVisible).toBe(false);
  });

  it('handles draft discard', async () => {
    const { result } = createHookResult();
    const draftId = 'draft-789';

    // Execute action
    await act(async () => {
      result.current.actions.discardDraft(draftId);
    });

    // Verify calls
    expect(mockedReceiptService.delete).toHaveBeenCalledWith(draftId);
    expect(mockedEmit).toHaveBeenCalledWith('receipts-changed', { id: draftId });
  });
});
