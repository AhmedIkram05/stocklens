import { formatCurrencyGBP, formatCurrencyRounded, formatRelativeDate } from '@/utils/formatters';

/**
 * Tests for `formatters` utilities.
 * Covers GBP currency formatting, rounding, and relative date formatting.
 */

describe('formatCurrency helpers', () => {
  it('formats amounts in GBP with thousands separator', () => {
    expect(formatCurrencyGBP(1234.56)).toBe('£1,234.56');
  });

  it('rounds to exactly two decimals', () => {
    expect(formatCurrencyRounded(12)).toBe('£12.00');
    expect(formatCurrencyRounded(12.345)).toBe('£12.35');
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

  it('describes events from the previous day as "Yesterday"', () => {
    expect(formatRelativeDate('2025-01-31T12:00:00Z')).toBe('Yesterday');
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
});
