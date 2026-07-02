/**
 * Test fixtures for receipts.
 * Exposes `createReceipt`, `createApiReceipt`, `buildReceiptList`, and `sampleReceipts` for tests.
 *
 * Two shapes are supported:
 *   - `Receipt` (SQLite shape from old dataService) — used only by screen tests that
 *     haven't migrated yet.
 *   - `Receipt` (API shape from @/services/receipts) — for all new hook/service tests.
 */

import type { Receipt as ApiReceipt, ReceiptCreate } from '@/services/receipts';

let receiptCounter = 1;

/** Create an API-shape receipt fixture (matches @/services/receipts Receipt). */
export const createApiReceipt = (overrides: Partial<ApiReceipt> = {}): ApiReceipt => {
  const id = String(receiptCounter++);
  return {
    id: overrides.id ?? id,
    user_id: overrides.user_id ?? 'test-user-uid',
    total_amount: overrides.total_amount ?? 42.5,
    merchant_name: overrides.merchant_name ?? null,
    category_id: overrides.category_id ?? null,
    ocr_raw_text: overrides.ocr_raw_text ?? 'Total: $42.50',
    ocr_confidence: overrides.ocr_confidence ?? null,
    line_items: overrides.line_items ?? null,
    receipt_image_s3_key: overrides.receipt_image_s3_key ?? 's3://receipts/test.jpg',
    scanned_at: overrides.scanned_at ?? new Date().toISOString(),
    created_at: overrides.created_at ?? new Date().toISOString(),
    ...overrides,
  };
};

/** Create an API-shape create payload fixture. */
export const createApiReceiptPayload = (overrides: Partial<ReceiptCreate> = {}): ReceiptCreate => ({
  total_amount: overrides.total_amount ?? 42.5,
  merchant_name: overrides.merchant_name ?? undefined,
  ocr_raw_text: overrides.ocr_raw_text ?? 'Total: $42.50',
  receipt_image_s3_key: overrides.receipt_image_s3_key ?? undefined,
  ...overrides,
});

export const buildApiReceiptList = (
  count = 3,
  overrides?: (index: number) => Partial<ApiReceipt>,
): ApiReceipt[] =>
  Array.from({ length: count }, (_unused, index) => createApiReceipt(overrides?.(index)));

export const sampleApiReceipts: ApiReceipt[] = buildApiReceiptList(5, (index) => ({
  total_amount: 25 + index * 7,
  scanned_at: new Date(Date.now() - index * 86400000).toISOString(),
}));

// ── Old-shape receipt (for backward compat in screen tests) ──

export interface OldReceiptShape {
  id: number;
  user_id: string;
  image_uri: string;
  total_amount: number;
  date_scanned: string;
  ocr_data: string;
  synced: number;
}

export const createReceipt = (overrides: Partial<OldReceiptShape> = {}): OldReceiptShape => {
  const base: OldReceiptShape = {
    id: overrides.id ?? receiptCounter++,
    user_id: overrides.user_id ?? 'test-user-uid',
    image_uri: overrides.image_uri ?? 'file:///receipt.jpg',
    total_amount: overrides.total_amount ?? 42.5,
    date_scanned: overrides.date_scanned ?? new Date().toISOString(),
    ocr_data: overrides.ocr_data ?? 'Total: $42.50',
    synced: overrides.synced ?? 1,
  };
  return { ...base, ...overrides };
};

export const buildReceiptList = (
  count = 3,
  overrides?: (index: number) => Partial<OldReceiptShape>,
): OldReceiptShape[] =>
  Array.from({ length: count }, (_unused, index) => createReceipt(overrides?.(index)));

export const sampleReceipts: OldReceiptShape[] = buildReceiptList(5, (index) => ({
  total_amount: 25 + index * 7,
  date_scanned: new Date(Date.now() - index * 86400000).toISOString(),
}));
