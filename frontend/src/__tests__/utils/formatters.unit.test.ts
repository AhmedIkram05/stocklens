/**
 * Tests for `formatters` utilities.
 * Covers GBP currency formatting, rounding, relative date formatting,
 * and the multi-currency formatCurrency function.
 */

import {
  formatCurrency,
  formatCurrencyGBP,
  formatCurrencyRounded,
  formatRelativeDate,
} from '@/utils/formatters';

describe('formatCurrency', () => {
  it('formats GBP amounts by default', () => {
    expect(formatCurrency(1234.56)).toBe('£1,234.56');
  });

  it('formats USD amounts', () => {
    expect(formatCurrency(99.99, 'USD')).toBe('US$99.99');
  });

  it('formats EUR amounts', () => {
    expect(formatCurrency(50, 'EUR')).toBe('€50.00');
  });

  it('handles zero gracefully', () => {
    expect(formatCurrency(0)).toBe('£0.00');
  });

  it('falls back to symbol-based formatting when Intl fails', () => {
    const originalNumberFormat = Intl.NumberFormat;
    (Intl as any).NumberFormat = jest.fn(() => {
      throw new Error('Intl not available');
    });

    expect(formatCurrency(25, 'GBP')).toBe('£25.00');
    expect(formatCurrency(25, 'USD')).toBe('$25.00');
    expect(formatCurrency(25, 'EUR')).toBe('€25.00');
    expect(formatCurrency(25, 'JPY')).toBe('25.00');

    (Intl as any).NumberFormat = originalNumberFormat;
  });
});

describe('formatCurrencyGBP', () => {
  it('formats amounts in GBP with thousands separator', () => {
    expect(formatCurrencyGBP(1234.56)).toBe('£1,234.56');
  });

  it('handles zero', () => {
    expect(formatCurrencyGBP(0)).toBe('£0.00');
  });

  it('handles large amounts', () => {
    expect(formatCurrencyGBP(1000000)).toBe('£1,000,000.00');
  });
});

describe('formatCurrencyRounded', () => {
  it('rounds to exactly two decimals', () => {
    expect(formatCurrencyRounded(12)).toBe('£12.00');
    expect(formatCurrencyRounded(12.345)).toBe('£12.35');
  });

  it('handles zero', () => {
    expect(formatCurrencyRounded(0)).toBe('£0.00');
  });

  it('handles negative amounts', () => {
    expect(formatCurrencyRounded(-10.5)).toBe('-£10.50');
  });
});

describe('formatRelativeDate', () => {
  const fixedNow = new Date('2025-02-01T12:00:00Z');

  beforeAll(() => {
    jest.useFakeTimers();
    jest.setSystemTime(fixedNow);
  });

  afterAll(() => {
    jest.useRealTimers();
  });

  it('describes events from the last minute in seconds', () => {
    expect(formatRelativeDate('2025-02-01T11:59:30Z')).toBe('30s ago');
  });

  it('describes events within the last hour in minutes', () => {
    expect(formatRelativeDate('2025-02-01T11:30:00Z')).toBe('30m ago');
  });

  it('describes events within the last 24 hours in hours', () => {
    expect(formatRelativeDate('2025-02-01T10:00:00Z')).toBe('2h ago');
  });

  it('describes events from the previous day as "Yesterday"', () => {
    expect(formatRelativeDate('2025-01-31T12:00:00Z')).toBe('Yesterday');
  });

  it('describes events within the last week in days', () => {
    expect(formatRelativeDate('2025-01-28T12:00:00Z')).toBe('4 days ago');
  });

  it('falls back to locale date strings for older events', () => {
    const date = '2024-01-15T00:00:00Z';
    const expected = new Date(date).toLocaleDateString(undefined, {
      day: 'numeric',
      month: 'short',
      year: 'numeric',
    });

    expect(formatRelativeDate(date)).toBe(expected);
  });

  it('returns "Receipt" for undefined/null/empty date', () => {
    expect(formatRelativeDate(undefined)).toBe('Receipt');
    expect(formatRelativeDate('')).toBe('Receipt');
  });

  it('returns "Invalid Date" locale string for invalid date strings', () => {
    const result = formatRelativeDate('not-a-date');
    // Invalid Date -> toLocaleDateString returns "Invalid Date" in Node
    expect(result).toBe('Invalid Date');
  });
});
