/**
 * Tests for `receiptParser` — OCR text parsing and amount extraction.
 * Covers hasForeignCurrency, validateAmount, parseAmountFromOcrText.
 */

import {
  hasForeignCurrency,
  validateAmount,
  parseAmountFromOcrText,
} from '@/services/receiptParser';

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
});

describe('validateAmount', () => {
  it('accepts valid positive amounts', () => {
    expect(validateAmount(25.0)).toBe(true);
    expect(validateAmount(0.01)).toBe(true);
    expect(validateAmount(999999.99)).toBe(true);
  });

  it('rejects null/undefined/NaN', () => {
    expect(validateAmount(null)).toBe(false);
    expect(validateAmount(undefined)).toBe(false);
    expect(validateAmount(NaN)).toBe(false);
  });

  it('rejects zero or negative amounts', () => {
    expect(validateAmount(0)).toBe(false);
    expect(validateAmount(-10)).toBe(false);
  });

  it('rejects extremely large amounts', () => {
    expect(validateAmount(1_000_000)).toBe(false);
    expect(validateAmount(1_000_001)).toBe(false);
  });

  it('rejects Infinity', () => {
    expect(validateAmount(Infinity)).toBe(false);
  });
});

describe('parseAmountFromOcrText', () => {
  it('extracts amount from a line with TOTAL keyword', () => {
    const text = 'SOME ITEMS\nTOTAL £25.50\nVISA ****1234';
    expect(parseAmountFromOcrText(text)).toBe(25.5);
  });

  it('extracts amount from a line with GRAND TOTAL keyword', () => {
    const text = 'Item 1    £10.00\nItem 2    £15.50\nGRAND TOTAL    £25.50';
    expect(parseAmountFromOcrText(text)).toBe(25.5);
  });

  it('extracts amount from a line with AMOUNT DUE keyword', () => {
    const text = 'AMOUNT DUE    £42.00';
    expect(parseAmountFromOcrText(text)).toBe(42);
  });

  it('extracts amount from a line with SUBTOTAL keyword', () => {
    const text = 'Item A    £8.00\nItem B    £12.00\nSUBTOTAL    £20.00';
    expect(parseAmountFromOcrText(text)).toBe(20);
  });

  it('handles total with comma as decimal separator (EU style)', () => {
    // In normalized form, commas before digits become dots
    const text = 'TOTAL    £25,50';
    expect(parseAmountFromOcrText(text)).toBe(25.5);
  });

  it('handles total with comma as thousands separator', () => {
    const text = 'TOTAL    £1,234.56';
    expect(parseAmountFromOcrText(text)).toBe(1234.56);
  });

  it('extracts amount from bottom-scan when no keyword present', () => {
    const text =
      'Item 1    £10.00\nItem 2    £15.00\nItem 3    £20.00\nThank you\nTotal including VAT    £45.00';
    const result = parseAmountFromOcrText(text);
    expect(result).not.toBeNull();
  });

  it('skips footer lines (cash, change, barcode) in bottom scan', () => {
    const text =
      'Item    £10.00\nItem    £15.00\nCASH    £30.00\nCHANGE    £5.00\nThank you\nVISA    £25.00';
    // The actual total line would be the one that's not footer
    const result = parseAmountFromOcrText(text);
    expect(result).not.toBeNull();
    expect(typeof result).toBe('number');
  });

  it('handles amount with letter-number confusion (O→0, l→1)', () => {
    // O replaced with 0, l replaced with 1
    const text = 'Total    £1O.50';
    expect(parseAmountFromOcrText(text)).toBe(10.5);
  });

  it('extracts amount from neighbor line of keyword', () => {
    const text = 'TOTAL\n£99.99\nCash tendered';
    expect(parseAmountFromOcrText(text)).toBe(99.99);
  });

  it('returns null for entirely empty text', () => {
    expect(parseAmountFromOcrText('')).toBeNull();
  });

  it('returns null for text with no numeric values', () => {
    expect(parseAmountFromOcrText('Just some text without numbers')).toBeNull();
  });

  it('prefers right-most numeric token on total line', () => {
    const text = 'TOTAL    10 items    £35.00';
    expect(parseAmountFromOcrText(text)).toBe(35);
  });

  it('handles integer-style amounts as pounds when large enough', () => {
    // "2500" without decimal should be treated as £25.00 when it's 100-50000
    const text = 'TOTAL    2500';
    expect(parseAmountFromOcrText(text)).toBe(25);
  });

  it('handles amount with currency symbol on keyword line', () => {
    const text = 'Total    $25.00';
    // It should still parse the number even if it's not GBP
    const result = parseAmountFromOcrText(text);
    expect(result).not.toBeNull();
    expect(typeof result).toBe('number');
  });
});
