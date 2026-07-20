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

  it('returns failure result when all strategies fail', async () => {
    fetchMock.mockReject(new Error('Network error'));

    const result = await performOcrWithFallback('file://photo.jpg', null, 'key');

    expect(result.success).toBe(false);
    expect(result.text).toBe('');
  });
});
