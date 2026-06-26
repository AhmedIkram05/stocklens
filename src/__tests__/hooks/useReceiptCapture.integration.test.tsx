/**
 * Tests for `useReceiptCapture` hook (integration).
 * Covers the capture → OCR → confirm → save flow, manual-entry fallback,
 * and error handling when OCR configuration is missing.
 */

import { act, renderHook } from '@testing-library/react-native';
import { Alert, Platform } from 'react-native';
import { useReceiptCapture } from '@/hooks/useReceiptCapture';
import { receiptService } from '@/services/dataService';
import { performOcrWithFallback } from '@/services/ocrService';
import { parseAmountFromOcrText, validateAmount } from '@/services/receiptParser';
import showConfirmationPrompt from '@/components/ConfirmationPrompt';

jest.mock('@/services/dataService', () => ({
  receiptService: {
    create: jest.fn(),
    update: jest.fn(),
    delete: jest.fn(),
  },
}));

jest.mock('@/services/ocrService', () => ({
  performOcrWithFallback: jest.fn(),
}));

jest.mock('@/services/receiptParser', () => ({
  parseAmountFromOcrText: jest.fn(),
  validateAmount: jest.fn(),
}));

jest.mock('@/components/ConfirmationPrompt', () => jest.fn());

const mockedReceiptService = receiptService as jest.Mocked<typeof receiptService>;
const mockedPerformOcr = performOcrWithFallback as jest.MockedFunction<
  typeof performOcrWithFallback
>;
const mockedParseAmount = parseAmountFromOcrText as jest.MockedFunction<
  typeof parseAmountFromOcrText
>;
const mockedValidateAmount = validateAmount as jest.MockedFunction<typeof validateAmount>;
const mockedPrompt = showConfirmationPrompt as jest.MockedFunction<typeof showConfirmationPrompt>;
const alertSpy = jest.spyOn(Alert, 'alert');
const Constants = require('expo-constants');

// Helper: create a hook instance with basic mocks for navigation and callbacks
const createHook = () =>
  renderHook(() =>
    useReceiptCapture({
      navigation: { navigate: jest.fn() },
      userUid: 'user-1',
      onResetCamera: jest.fn(),
    }),
  );

describe('useReceiptCapture', () => {
  beforeEach(() => {
    // Reset mocks and set up sensible defaults for OCR and parsing
    jest.clearAllMocks();
    alertSpy.mockClear();
    // Ensure tests behave as if OCR API key exists
    Constants.manifest.extra = { OCR_SPACE_API_KEY: 'test-key' };
    // Mock OCR returning a simple total
    mockedPerformOcr.mockResolvedValue({ text: 'Total 12.34' } as any);
    // Mock the parser to return a numeric amount
    mockedParseAmount.mockReturnValue(12.34);
    // By default consider parsed amounts valid
    mockedValidateAmount.mockReturnValue(true);
    // Confirmation prompt is replaced with a jest fn to capture options
    mockedPrompt.mockImplementation(() => {});
  });

  /**
   * Test: OCR success path
   * - Simulates capturing a photo, OCR returning a valid amount,
   *   showing a confirmation prompt, and saving the receipt on confirm.
   */
  it('shows confirmation prompt and saves when OCR succeeds', async () => {
    const navigation = { navigate: jest.fn() };
    const onResetCamera = jest.fn();
    const { result } = renderHook(() =>
      useReceiptCapture({ navigation, userUid: 'user-1', onResetCamera }),
    );

    await act(async () => {
      await result.current.actions.processReceipt({
        photoUri: 'file://receipt.jpg',
        photoBase64: 'abc',
        draftIdArg: 42,
      });
    });

    // Verify confirmation prompt was displayed with formatted amount
    expect(mockedPrompt).toHaveBeenCalledWith('£12.34', expect.any(Object));
    const options = mockedPrompt.mock.calls[0][1];

    // Simulate user confirming the prompt which should save the receipt
    await act(async () => {
      await options.onConfirm?.();
    });

    expect(mockedReceiptService.update).toHaveBeenCalledWith(
      42,
      expect.objectContaining({ total_amount: 12.34 }),
    );
    expect(navigation.navigate).toHaveBeenCalledWith('ReceiptDetails', expect.any(Object));
    expect(onResetCamera).toHaveBeenCalled();
  });

  it('opens manual entry flow when OCR returns empty text', async () => {
    mockedPerformOcr.mockResolvedValue({ text: '' } as any);
    const { result } = createHook();
    const platform = Platform as any;
    const originalOS = platform.OS;

    await act(async () => {
      await result.current.actions.processReceipt({
        photoUri: 'file://receipt.jpg',
        photoBase64: 'abc',
      });
    });

    const options = mockedPrompt.mock.calls[0][1];
    await act(async () => {
      platform.OS = 'android';
      options.onEnterManually?.();
    });
    platform.OS = originalOS;

    expect(result.current.state.manualModalVisible).toBe(true);
  });

  it('alerts when OCR API key is missing', async () => {
    Constants.manifest.extra = {};
    const { result } = createHook();

    await act(async () => {
      await result.current.actions.processReceipt({
        photoUri: 'file://receipt.jpg',
        photoBase64: 'abc',
      });
    });

    expect(alertSpy).toHaveBeenCalledWith('Missing API Key', expect.any(String));
  });
});
