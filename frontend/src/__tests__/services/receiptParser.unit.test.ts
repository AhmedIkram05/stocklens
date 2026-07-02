/**
 * Tests for `receiptParser`.
 * Verifies extraction and inference logic for totals from noisy OCR text,
 * decimal inference, and fallback heuristics.
 */
import { parseAmountFromOcrText } from '@/services/receiptParser';

describe('parseAmountFromOcrText', () => {
  it('extracts amount from total keyword lines', () => {
    const text = `ITEMS 40.00\nTOTAL £45.67`;
    expect(parseAmountFromOcrText(text)).toBe(45.67);
  });

  it('infers decimal positions for large integers', () => {
    const text = `TOTAL 1250`;
    expect(parseAmountFromOcrText(text)).toBe(12.5);
  });

  it('falls back to bottom scan when no keyword is present', () => {
    const text = `Veggies 10.00\nBread 2.50\n\n 12.50`;
    expect(parseAmountFromOcrText(text)).toBe(12.5);
  });
});
