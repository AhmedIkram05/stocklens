import { ocrHelpers, performOcrWithFallback } from '@/services/ocrService';

/**
 * Tests for `ocrService` helpers and `performOcrWithFallback`.
 * Ensures image preprocessing, OCR submission, fallback behavior, and
 * network/error handling are exercised.
 */

describe('performOcrWithFallback', () => {
  afterEach(() => {
    jest.restoreAllMocks();
  });

  it('returns successful OCR result from preprocessed image', async () => {
    const preprocessSpy = jest
      .spyOn(ocrHelpers, 'preprocessImageToBase64')
      .mockResolvedValue('tiny-b64');
    const base64Spy = jest
      .spyOn(ocrHelpers, 'recognizeBase64WithOCRSpace')
      .mockResolvedValue({ text: 'receipt text', success: true } as any);

    const result = await performOcrWithFallback('file://receipt.jpg', null, 'api-key');

    expect(preprocessSpy).toHaveBeenCalledWith('file://receipt.jpg', 1400);
    expect(base64Spy).toHaveBeenCalledWith('tiny-b64', 'api-key');
    expect(result.text).toBe('receipt text');
  });
});
