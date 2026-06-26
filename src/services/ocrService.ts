/**
 * OcrService
 *
 * Helpers for performing OCR on receipt images via OCR.Space (file/base64).
 */

/**
 * OcrResult type - Result structure from OCR operations
 *
 * @property text - Extracted text from image (empty string if failed)
 * @property raw - Raw API response or error object
 * @property success - Whether OCR succeeded
 * @property errorMessage - Human-readable error message if failed
 */
export type OcrResult = {
  text: string;
  raw?: any;
  success: boolean;
  errorMessage?: string;
};

/**
 * Internal helper to send FormData to OCR.Space API
 *
 * @param formData - FormData containing image file or base64 string
 * @param apiKey - OCR.Space API key
 * @returns OcrResult with extracted text or error
 *
 * Features:
 * - 10-second timeout protection (AbortController)
 * - Error handling for API responses and network failures
 * - Validates ParsedText is non-empty
 */
async function doOcrForm(formData: FormData, apiKey: string): Promise<OcrResult> {
  const TIMEOUT_MS = 10000;
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), TIMEOUT_MS);

  try {
    try {
      formData.append('apikey', apiKey as any);
    } catch (e) {}

    const resp = await fetch('https://api.ocr.space/parse/image', {
      method: 'POST',
      headers: { apikey: apiKey, Accept: 'application/json' } as any,
      body: formData as any,
      signal: (controller as any).signal,
    });
    clearTimeout(timeout);

    if (!resp.ok) {
      const txt = await resp.text();
      return {
        text: '',
        raw: txt,
        success: false,
        errorMessage: `OCR.Space request failed: ${resp.status}`,
      };
    }
    const json = await resp.json();
    const isErrored = json?.IsErroredOnProcessing;
    const parsed = json?.ParsedResults?.[0];
    const text = parsed?.ParsedText ?? '';
    if (isErrored) {
      const msg = json?.ErrorMessage || parsed?.ErrorMessage || 'OCR.Space reported an error';
      return { text: '', raw: json, success: false, errorMessage: String(msg) };
    }
    if (!text || text.trim().length === 0) {
      return { text: '', raw: json, success: false, errorMessage: 'No text detected in image' };
    }
    return { text, raw: json, success: true };
  } catch (e: any) {
    clearTimeout(timeout);
    const isAbort = e?.name === 'AbortError' || String(e).toLowerCase().includes('abort');
    const message = isAbort
      ? `OCR request timed out after ${TIMEOUT_MS / 1000}s`
      : e?.message || String(e);
    return { text: '', raw: e, success: false, errorMessage: message };
  }
}

/**
 * Recognize text from an image URI using OCR.Space (file upload method)
 *
 * @param imageUri - Local file URI (e.g., from expo-camera)
 * @param apiKey - OCR.Space API key
 * @returns OcrResult with extracted text or error
 *
 * Process:
 * 1. Extracts filename and MIME type from URI
 * 2. Creates FormData with image file
 * 3. Sets OCREngine=2 (best for receipts), language=eng
 * 4. Sends multipart request to OCR.Space
 */
export async function recognizeImageWithOCRSpace(
  imageUri: string,
  apiKey: string,
): Promise<OcrResult> {
  if (!apiKey) throw new Error('OCR Space API key is required');
  const uri = imageUri;
  const filename = uri.split('/').pop() || 'photo.jpg';
  const match = filename.match(/\.(\w+)$/);
  let ext = match ? match[1].toLowerCase() : 'jpg';
  if (ext === 'jpg') ext = 'jpeg';
  const type = `image/${ext}`;
  const formData = new FormData();
  // @ts-ignore
  formData.append('file', { uri, name: filename, type });
  formData.append('OCREngine', '2');
  formData.append('language', 'eng');
  formData.append('isOverlayRequired', 'false');
  try {
    formData.append('apikey', apiKey as any);
  } catch (e) {}
  return doOcrForm(formData, apiKey);
}

export const ocrHelpers = {
  preprocessImageToBase64,
  recognizeBase64WithOCRSpace,
  recognizeImageWithOCRSpace,
};

/**
 * Recognize text from a base64-encoded image string using OCR.Space
 *
 * @param base64Data - Base64 image string (with or without data: prefix)
 * @param apiKey - OCR.Space API key
 * @returns OcrResult with extracted text or error
 *
 * Process:
 * 1. Ensures base64 string has data:image/jpeg;base64, prefix
 * 2. Creates FormData with base64Image field
 * 3. Sets OCREngine=2, language=eng
 * 4. Sends request to OCR.Space
 *
 * Note: Base64 method often has better results than file upload due to
 * preprocessing control (see preprocessImageToBase64).
 */
export async function recognizeBase64WithOCRSpace(
  base64Data: string,
  apiKey: string,
): Promise<OcrResult> {
  if (!apiKey) throw new Error('OCR Space API key is required');
  let payload = base64Data;
  if (!payload.startsWith('data:')) payload = `data:image/jpeg;base64,${payload}`;
  const formData = new FormData();
  formData.append('base64Image', payload as any);
  try {
    formData.append('apikey', apiKey as any);
  } catch (e) {}
  formData.append('OCREngine', '2');
  formData.append('language', 'eng');
  formData.append('isOverlayRequired', 'false');
  return doOcrForm(formData, apiKey);
}

/**
 * Preprocess image to base64 for better OCR quality
 *
 * @param uri - Local image URI
 * @param targetWidth - Target width in pixels (default: 2200px)
 * @returns Base64 string (without data: prefix) or null if failed
 *
 * Process:
 * 1. Uses expo-image-manipulator to resize image to targetWidth
 * 2. Maintains aspect ratio, compresses as JPEG at 1.0 quality
 * 3. Returns base64 string for OCR submission
 *
 * Benefits:
 * - Reduces file size for faster uploads
 * - Normalizes image dimensions for consistent OCR quality
 * - Improves text recognition accuracy for receipts
 */
export async function preprocessImageToBase64(
  uri: string,
  targetWidth = 2200,
): Promise<string | null> {
  try {
    const ImageManipulator = await import('expo-image-manipulator');
    const manip = await ImageManipulator.manipulateAsync(
      uri,
      [{ resize: { width: targetWidth } }],
      { compress: 1.0, format: ImageManipulator.SaveFormat.JPEG, base64: true },
    );
    return manip?.base64 || null;
  } catch (e: any) {
    return null;
  }
}

/**
 * Perform OCR with automatic fallback strategies
 *
 * @param imageUri - Local image URI
 * @param base64Data - Optional pre-computed base64 string
 * @param apiKey - OCR.Space API key
 * @returns OcrResult with text or error
 *
 * Fallback Strategy (tries in order until success):
 * 1. Base64 upload with 1400px preprocessing (fastest, best quality)
 * 2. Direct file upload if base64 fails or returns empty text
 * 3. Base64 upload with 2000px preprocessing (last resort for poor images)
 *
 * Process:
 * - Each strategy is wrapped in try/catch
 * - Continues to next strategy if current returns empty text
 * - Returns first successful result with non-empty text
 * - Returns failure result if all strategies fail
 *
 * Usage:
 * This is the recommended entry point for OCR operations.
 */
export async function performOcrWithFallback(
  imageUri: string,
  base64Data: string | null,
  apiKey: string,
): Promise<OcrResult> {
  if (!apiKey) throw new Error('OCR Space API key is required');
  let b64 = base64Data || null;
  let ocrResult: OcrResult | undefined;

  try {
    if (!b64) {
      b64 = await ocrHelpers.preprocessImageToBase64(imageUri, 1400);
    }

    if (b64) {
      try {
        ocrResult = await ocrHelpers.recognizeBase64WithOCRSpace(b64, apiKey);
      } catch (e) {
        ocrResult = { text: '', raw: null, success: false, errorMessage: String(e) } as OcrResult;
      }
    }

    if ((!ocrResult || !ocrResult.text || !ocrResult.text.trim()) && imageUri) {
      try {
        const fileTry = await ocrHelpers.recognizeImageWithOCRSpace(imageUri, apiKey);
        if (fileTry && fileTry.text && fileTry.text.trim().length > 0) {
          ocrResult = fileTry;
        }
      } catch (e) {}
    }

    if ((!ocrResult || !ocrResult.text || !ocrResult.text.trim()) && imageUri) {
      try {
        const bigger = await ocrHelpers.preprocessImageToBase64(imageUri, 2000);
        if (bigger) {
          const tryB = await ocrHelpers.recognizeBase64WithOCRSpace(bigger, apiKey);
          if (tryB && tryB.text && tryB.text.trim().length > 0) {
            ocrResult = tryB;
          }
        }
      } catch (e) {}
    }

    return ocrResult || { text: '', raw: null, success: false, errorMessage: 'No OCR result' };
  } catch (e: any) {
    return { text: '', raw: null, success: false, errorMessage: String(e) };
  }
}
