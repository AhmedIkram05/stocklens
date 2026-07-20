/**
 * Tests for `periods` constants and helpers.
 * Covers periodToYears, periodToStartDate, periodLabel conversions.
 */

import { periodToYears, periodToStartDate, periodLabel, PERIOD_OPTIONS } from '@/constants/periods';

describe('PERIOD_OPTIONS', () => {
  it('exports expected period labels', () => {
    expect(PERIOD_OPTIONS).toEqual(['1M', '3M', '6M', '1Y', '3Y', '5Y', '10Y', '20Y', 'YTD']);
  });
});

describe('periodToYears', () => {
  it('converts month labels to year fractions', () => {
    expect(periodToYears('1M')).toBeCloseTo(1 / 12);
    expect(periodToYears('3M')).toBeCloseTo(3 / 12);
    expect(periodToYears('6M')).toBeCloseTo(6 / 12);
  });

  it('converts year labels to whole numbers', () => {
    expect(periodToYears('1Y')).toBe(1);
    expect(periodToYears('3Y')).toBe(3);
    expect(periodToYears('5Y')).toBe(5);
    expect(periodToYears('10Y')).toBe(10);
    expect(periodToYears('20Y')).toBe(20);
  });

  it('computes YTD as elapsed fraction of current year', () => {
    jest.useFakeTimers();
    jest.setSystemTime(new Date('2025-07-01T00:00:00Z'));

    const ytd = periodToYears('YTD');
    expect(ytd).toBeGreaterThan(0.49);
    expect(ytd).toBeLessThan(0.5);

    jest.useRealTimers();
  });

  it('defaults to 1 year for unknown labels', () => {
    expect(periodToYears('unknown')).toBe(1);
    expect(periodToYears('')).toBe(1);
  });
});

describe('periodToStartDate', () => {
  const base = new Date('2025-07-15T12:00:00Z');

  it('returns YYYY-MM-DD for month periods', () => {
    expect(periodToStartDate('1M', base)).toBe('2025-06-15');
    expect(periodToStartDate('3M', base)).toBe('2025-04-15');
    expect(periodToStartDate('6M', base)).toBe('2025-01-15');
  });

  it('returns YYYY-MM-DD for year periods', () => {
    expect(periodToStartDate('1Y', base)).toBe('2024-07-15');
    expect(periodToStartDate('3Y', base)).toBe('2022-07-15');
    expect(periodToStartDate('5Y', base)).toBe('2020-07-15');
    expect(periodToStartDate('10Y', base)).toBe('2015-07-15');
    expect(periodToStartDate('20Y', base)).toBe('2005-07-15');
  });

  it('returns YTD as Jan 1 of the same year', () => {
    expect(periodToStartDate('YTD', base)).toBe('2025-01-01');
  });

  it('defaults to 1 year ago for unknown labels', () => {
    expect(periodToStartDate('foobar', base)).toBe('2024-07-15');
  });

  it('uses current date when endDate is not provided', () => {
    jest.useFakeTimers();
    jest.setSystemTime(new Date('2025-06-01T00:00:00Z'));
    expect(periodToStartDate('1M')).toBe('2025-05-01');
    jest.useRealTimers();
  });
});

describe('periodLabel', () => {
  it('returns short descriptions for common labels', () => {
    expect(periodLabel('YTD')).toBe('year to date');
    expect(periodLabel('1M')).toBe('1 month');
    expect(periodLabel('3M')).toBe('3 months');
    expect(periodLabel('6M')).toBe('6 months');
    expect(periodLabel('1Y')).toBe('1 year');
  });

  it('parses number-based labels into natural language', () => {
    expect(periodLabel('3Y')).toBe('3 years');
    expect(periodLabel('5Y')).toBe('5 years');
    expect(periodLabel('10Y')).toBe('10 years');
    expect(periodLabel('20Y')).toBe('20 years');
  });

  it('handles singular and plural correctly', () => {
    expect(periodLabel('2M')).toBe('2 months');
    expect(periodLabel('2Y')).toBe('2 years');
  });
});
