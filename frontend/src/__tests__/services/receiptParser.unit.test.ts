/**
 * Tests for `receiptParser` — OCR text parsing and amount extraction.
 * Covers hasForeignCurrency.
 */

import { hasForeignCurrency } from '@/services/receiptParser';

describe('hasForeignCurrency', () => {
  it('detects dollar sign', () => {
    expect(hasForeignCurrency('Total: $25.00')).toBe(true);
  });

  it('detects euro sign', () => {
    expect(hasForeignCurrency('Total: €30.00')).toBe(true);
  });

  it('returns false for GBP receipts', () => {
    expect(hasForeignCurrency('Total: £25.00')).toBe(false);
  });

  it('returns false for empty or null text', () => {
    expect(hasForeignCurrency('')).toBe(false);
    expect(hasForeignCurrency(null as unknown as string)).toBe(false);
  });

  it('returns false for GBP-denominated text without symbols', () => {
    expect(hasForeignCurrency('Total 25.00')).toBe(false);
  });

  it('treats GBP amounts as authoritative over fine-print foreign symbols', () => {
    // M8 regression: the old bare-[$€] test nuked UK receipts whose fine
    // print mentioned a foreign price. The £ amount token wins.
    expect(hasForeignCurrency('Total: £25.00 ($32.00)')).toBe(false);
    expect(hasForeignCurrency('RRP $9.99\nTOTAL £12.50')).toBe(false);
    expect(hasForeignCurrency('save €2 with clubcard\nTOTAL £7.40')).toBe(false);
  });

  it('ignores currency symbols not attached to an amount token', () => {
    // OCR noise / prose / brand glyphs must not reject the receipt.
    expect(hasForeignCurrency('S&P 500 index fund')).toBe(false);
    expect(hasForeignCurrency('Prices in $$$')).toBe(false);
  });

  it('detects foreign symbols only when attached to amounts', () => {
    expect(hasForeignCurrency('TOTAL $9.99')).toBe(true);
    expect(hasForeignCurrency('TOTAL €30')).toBe(true);
    expect(hasForeignCurrency('TOTAL 15$')).toBe(true);
  });

  it('returns false for text with only numbers and no currency symbols', () => {
    expect(hasForeignCurrency('Total 25.00')).toBe(false);
  });
});
