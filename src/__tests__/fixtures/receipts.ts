/**
 * Test fixtures for receipts.
 * Exposes `createReceipt`, `buildReceiptList`, and `sampleReceipts` for tests.
 */

import { Receipt } from '@/services/dataService';

let receiptCounter = 1;

export const createReceipt = (overrides: Partial<Receipt> = {}): Receipt => {
  const base: Receipt = {
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
  overrides?: (index: number) => Partial<Receipt>,
): Receipt[] =>
  Array.from({ length: count }, (_unused, index) => createReceipt(overrides?.(index)));

export const sampleReceipts: Receipt[] = buildReceiptList(5, (index) => ({
  total_amount: 25 + index * 7,
  date_scanned: new Date(Date.now() - index * 86400000).toISOString(),
}));
