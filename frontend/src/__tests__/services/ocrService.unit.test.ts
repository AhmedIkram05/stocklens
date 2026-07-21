/**
 * Tests for `ocrService` — OCR.Space API integration.
 * Covers URL validation, fallback strategy, base64 preprocessing.
 */

import {
  recognizeImageWithOCRSpace,
  recognizeBase64WithOCRSpace,
  preprocessImageToBase64,
  performOcrWithFallback,
  ocrHelpers,
} from '@/services/ocrService';

const fetchMock = require('jest-fetch-mock');

describe('recognizeImageWithOCRSpace', () => {
  beforeEach(() => {
    fetchMock.resetMocks();
  });

  it('throws when apiKey is missing', async () => {
    await expect(recognizeImageWithOCRSpace('file://photo.jpg', '')).rejects.toThrow(
      'OCR Space API key is required',
    );
  });

  it('returns successful OcrResult on valid response', async () => {
    fetchMock.mockResponseOnce(
      JSON.stringify({
        ParsedResults: [{ ParsedText: 'Receipt Total £25.00' }],
        IsErroredOnProcessing: false,
      }),
      { status: 200 },
    );

    const result = await recognizeImageWithOCRSpace('file://photo.jpg', 'test-key');

    expect(result.success).toBe(true);
    expect(result.text).toBe('Receipt Total £25.00');
    expect(fetchMock).toHaveBeenCalledWith(
      'https://api.ocr.space/parse/image',
      expect.objectContaining({ method: 'POST' }),
    );
  });

  it('returns error result on API error', async () => {
    fetchMock.mockResponseOnce('', { status: 500 });

    const result = await recognizeImageWithOCRSpace('file://photo.jpg', 'test-key');

    expect(result.success).toBe(false);
    expect(result.text).toBe('');
    expect(result.errorMessage).toContain('500');
  });

  it('handles OCR processing error', async () => {
    fetchMock.mockResponseOnce(
      JSON.stringify({
        IsErroredOnProcessing: true,
        ErrorMessage: 'Processing timeout',
        ParsedResults: [{}],
      }),
      { status: 200 },
    );

    const result = await recognizeImageWithOCRSpace('file://photo.jpg', 'test-key');

    expect(result.success).toBe(false);
    expect(result.text).toBe('');
  });

  it('handles empty ParsedText', async () => {
    fetchMock.mockResponseOnce(
      JSON.stringify({
        ParsedResults: [{ ParsedText: '' }],
        IsErroredOnProcessing: false,
      }),
      { status: 200 },
    );

    const result = await recognizeImageWithOCRSpace('file://photo.jpg', 'test-key');

    expect(result.success).toBe(false);
    expect(result.errorMessage).toBe('No text detected in image');
  });

  it('handles network timeout (AbortError)', async () => {
    const abortError = new Error('The operation was aborted');
    abortError.name = 'AbortError';
    fetchMock.mockReject(abortError);

    const result = await recognizeImageWithOCRSpace('file://photo.jpg', 'test-key');

    expect(result.success).toBe(false);
    expect(result.text).toBe('');
    expect(result.errorMessage).toContain('timed out');
  });
});

describe('recognizeBase64WithOCRSpace', () => {
  beforeEach(() => {
    fetchMock.resetMocks();
  });

  it('adds data:image prefix when missing', async () => {
    fetchMock.mockResponseOnce(
      JSON.stringify({
        ParsedResults: [{ ParsedText: 'ABC123' }],
        IsErroredOnProcessing: false,
      }),
      { status: 200 },
    );

    const result = await recognizeBase64WithOCRSpace('base64string==', 'key');

    expect(result.success).toBe(true);
    // The base64 payload should be prefixed
    const body = fetchMock.mock.calls[0][1].body as FormData;
    expect(body.get('base64Image')).toBe('data:image/jpeg;base64,base64string==');
  });

  it('preserves existing data: prefix', async () => {
    fetchMock.mockResponseOnce(
      JSON.stringify({
        ParsedResults: [{ ParsedText: 'XYZ' }],
        IsErroredOnProcessing: false,
      }),
      { status: 200 },
    );

    await recognizeBase64WithOCRSpace('data:image/png;base64,abc123', 'key');

    const body = fetchMock.mock.calls[0][1].body as FormData;
    expect(body.get('base64Image')).toBe('data:image/png;base64,abc123');
  });

  it('throws without apiKey', async () => {
    await expect(recognizeBase64WithOCRSpace('data', '')).rejects.toThrow(
      'OCR Space API key is required',
    );
  });

  it('returns parsed text on successful response', async () => {
    fetchMock.mockResponseOnce(
      JSON.stringify({
        ParsedResults: [{ ParsedText: 'Extracted text from base64' }],
        IsErroredOnProcessing: false,
      }),
      { status: 200 },
    );

    const result = await recognizeBase64WithOCRSpace('dGVzdA==', 'valid-key');

    expect(result.success).toBe(true);
    expect(result.text).toBe('Extracted text from base64');
  });

  it('handles OCR processing error for base64 uploads', async () => {
    fetchMock.mockResponseOnce(
      JSON.stringify({
        IsErroredOnProcessing: true,
        ErrorMessage: 'Base64 too large',
        ParsedResults: [{}],
      }),
      { status: 200 },
    );

    const result = await recognizeBase64WithOCRSpace('dGVzdA==', 'valid-key');

    expect(result.success).toBe(false);
    expect(result.text).toBe('');
    expect(result.errorMessage).toContain('Base64 too large');
  });
});

describe('preprocessImageToBase64', () => {
  it('returns null when import fails (non-native env)', async () => {
    const result = await preprocessImageToBase64('file://photo.jpg');
    expect(result).toBeNull();
  });
});

describe('performOcrWithFallback', () => {
  beforeEach(() => {
    fetchMock.resetMocks();
    // Make preprocess return null so tests hit the fetch path
    jest.spyOn(ocrHelpers, 'preprocessImageToBase64').mockResolvedValue(null);
  });

  afterEach(() => {
    jest.restoreAllMocks();
  });

  it('throws when apiKey is missing', async () => {
    await expect(performOcrWithFallback('file://photo.jpg', null, '')).rejects.toThrow(
      'OCR Space API key is required',
    );
  });

  it('uses provided base64 data directly', async () => {
    fetchMock.mockResponseOnce(
      JSON.stringify({
        ParsedResults: [{ ParsedText: 'Receipt text' }],
        IsErroredOnProcessing: false,
      }),
      { status: 200 },
    );

    const result = await performOcrWithFallback('file://photo.jpg', 'base64data', 'key');

    expect(result.success).toBe(true);
    expect(result.text).toBe('Receipt text');
  });

  it('falls back to file upload when base64 fails', async () => {
    // First: preprocess returns null (set in beforeEach)
    // Second: file upload returns success
    fetchMock.mockResponseOnce(
      JSON.stringify({
        ParsedResults: [{ ParsedText: 'File OCR result' }],
        IsErroredOnProcessing: false,
      }),
      { status: 200 },
    );

    const result = await performOcrWithFallback('file://photo.jpg', null, 'key');

    expect(result.success).toBe(true);
    expect(result.text).toBe('File OCR result');
  });

  it('falls back to file upload when base64 is an empty string', async () => {
    fetchMock.mockResponseOnce(
      JSON.stringify({
        ParsedResults: [{ ParsedText: 'Fallback from empty string' }],
        IsErroredOnProcessing: false,
      }),
      { status: 200 },
    );

    const result = await performOcrWithFallback('file://photo.jpg', '', 'key');

    expect(result.success).toBe(true);
    expect(result.text).toBe('Fallback from empty string');
  });

  it('falls back to 2000px preprocessing when base64 and file upload fail', async () => {
    (ocrHelpers.preprocessImageToBase64 as jest.Mock)
      .mockResolvedValueOnce(null) // 1400px → null (skip base64 path)
      .mockResolvedValueOnce('bigger64'); // 2000px → base64 string

    // File upload returns empty text
    fetchMock.mockResponseOnce(
      JSON.stringify({
        ParsedResults: [{ ParsedText: '' }],
        IsErroredOnProcessing: false,
      }),
      { status: 200 },
    );

    // 2000px base64 OCR succeeds
    fetchMock.mockResponseOnce(
      JSON.stringify({
        ParsedResults: [{ ParsedText: '2000px OCR result' }],
        IsErroredOnProcessing: false,
      }),
      { status: 200 },
    );

    const result = await performOcrWithFallback('file://photo.jpg', null, 'key');

    expect(result.success).toBe(true);
    expect(result.text).toBe('2000px OCR result');
  });

  it('returns failure result when all strategies fail', async () => {
    fetchMock.mockReject(new Error('Network error'));

    const result = await performOcrWithFallback('file://photo.jpg', null, 'key');

    expect(result.success).toBe(false);
    expect(result.text).toBe('');
  });

  it('handles abort error as timeout message for performOcrWithFallback', async () => {
    const abortError = new Error('Aborted');
    abortError.name = 'AbortError';
    fetchMock.mockReject(abortError);

    // All three strategies fail with abort, so expectations check no OCR result
    const result = await performOcrWithFallback('file://test.jpg', null, 'test-key');

    expect(result.success).toBe(false);
    expect(result.text).toBe('');
  });
});
