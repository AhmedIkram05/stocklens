import { act, renderHook } from '@testing-library/react-native';
import { Alert } from 'react-native';
import { useReceiptCapture } from '@/hooks/useReceiptCapture';
import { receiptService } from '@/services/receipts';

jest.mock('@/services/receipts', () => ({
  receiptService: {
    create: jest.fn(),
    update: jest.fn(),
    delete: jest.fn(),
    scan: jest.fn(),
  },
}));

jest.mock('@/components/ConfirmationPrompt', () => jest.fn());

const mockedPrompt = require('@/components/ConfirmationPrompt') as jest.Mock;
const alertSpy = jest.spyOn(Alert, 'alert');

const mockScanResponse = {
  id: 'scan-42',
  extraction: {
    merchant_name: 'Tesco',
    total: 12.34,
    date: '2025-06-15',
    currency: 'GBP',
    items: [{ name: 'Item', quantity: 1, price: 12.34 }],
  },
  raw_text: 'TOTAL: £12.34',
  source: 'regex',
  confidence: 95,
  processing_time_ms: 350,
};

const createHook = () =>
  renderHook(() =>
    useReceiptCapture({
      navigation: { navigate: jest.fn() },
      onResetCamera: jest.fn(),
    }),
  );

describe('useReceiptCapture', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    alertSpy.mockClear();
  });

  it('shows confirmation prompt and navigates when scan succeeds', async () => {
    const navigation = { navigate: jest.fn() };
    const onResetCamera = jest.fn();
    const { result } = renderHook(() => useReceiptCapture({ navigation, onResetCamera }));

    (receiptService.scan as jest.Mock).mockResolvedValue(mockScanResponse);

    await act(async () => {
      await result.current.actions.processReceipt({
        photoUri: 'file://receipt.jpg',
      });
    });

    expect(receiptService.scan).toHaveBeenCalledWith('file://receipt.jpg');
    expect(mockedPrompt).toHaveBeenCalledWith('£12.34', expect.any(Object));

    const options = mockedPrompt.mock.calls[0][1];
    await act(async () => {
      await options.onConfirm?.();
    });

    expect(navigation.navigate).toHaveBeenCalledWith('ReceiptDetails', {
      receiptId: 'scan-42',
      totalAmount: 12.34,
      merchantName: 'Tesco',
      date: '2025-06-15',
      lineItems: [{ name: 'Item', quantity: 1, price: 12.34 }],
      image: 'file://receipt.jpg',
      source: 'regex',
      confidence: 95,
      processingTimeMs: 350,
    });
    expect(onResetCamera).toHaveBeenCalled();
  });

  it('opens manual entry flow when scan fails with no amount', async () => {
    (receiptService.scan as jest.Mock).mockRejectedValue(
      new Error('No total amount found in receipt'),
    );
    const { result } = createHook();

    await act(async () => {
      await result.current.actions.processReceipt({
        photoUri: 'file://receipt.jpg',
      });
    });

    expect(alertSpy).toHaveBeenCalledWith('Could not read receipt', expect.any(String));
    expect(result.current.state.manualModalVisible).toBe(true);
  });

  it('alerts on unexpected scan errors', async () => {
    (receiptService.scan as jest.Mock).mockRejectedValue(new Error('Network error'));
    const { result } = createHook();

    await act(async () => {
      await result.current.actions.processReceipt({
        photoUri: 'file://receipt.jpg',
      });
    });

    expect(alertSpy).toHaveBeenCalledWith('Scan Error', expect.any(String));
  });

  it('manual entry via saveAndNavigate creates receipt and navigates', async () => {
    const navigation = { navigate: jest.fn() };
    const onResetCamera = jest.fn();
    const { result } = renderHook(() => useReceiptCapture({ navigation, onResetCamera }));

    (receiptService.create as jest.Mock).mockResolvedValue({ id: 'manual-1' });

    await act(async () => {
      await result.current.actions.saveAndNavigate(99.99, 'Total £99.99', 'file://manual.jpg');
    });

    expect(receiptService.create).toHaveBeenCalledWith({
      receipt_image_s3_key: 'file://manual.jpg',
      total_amount: 99.99,
      ocr_raw_text: 'Total £99.99',
    });
    expect(navigation.navigate).toHaveBeenCalledWith(
      'ReceiptDetails',
      expect.objectContaining({
        receiptId: 'manual-1',
        totalAmount: 99.99,
      }),
    );
  });
});
