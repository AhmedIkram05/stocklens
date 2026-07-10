/**
 * Shared time-period options for YearSelector and date-range calculations.
 */

export const PERIOD_OPTIONS = ['1M', '3M', '6M', '1Y', '3Y', '5Y', '10Y', '20Y', 'YTD'] as const;

export type PeriodLabel = (typeof PERIOD_OPTIONS)[number];

/** Convert a period label to a year fraction for projection math. */
export function periodToYears(label: string): number {
  switch (label) {
    case '1M':
      return 1 / 12;
    case '3M':
      return 3 / 12;
    case '6M':
      return 6 / 12;
    case '1Y':
      return 1;
    case '3Y':
      return 3;
    case '5Y':
      return 5;
    case '10Y':
      return 10;
    case '20Y':
      return 20;
    case 'YTD': {
      const now = new Date();
      const startOfYear = new Date(now.getFullYear(), 0, 1);
      const msPerYear = 365.25 * 24 * 60 * 60 * 1000;
      return (now.getTime() - startOfYear.getTime()) / msPerYear;
    }
    default:
      return 1;
  }
}

/** Convert a period label to a start date for API date-range queries. */
export function periodToStartDate(label: string, endDate: Date = new Date()): string {
  const d = new Date(endDate);
  switch (label) {
    case '1M':
      d.setMonth(d.getMonth() - 1);
      break;
    case '3M':
      d.setMonth(d.getMonth() - 3);
      break;
    case '6M':
      d.setMonth(d.getMonth() - 6);
      break;
    case '1Y':
      d.setFullYear(d.getFullYear() - 1);
      break;
    case '3Y':
      d.setFullYear(d.getFullYear() - 3);
      break;
    case '5Y':
      d.setFullYear(d.getFullYear() - 5);
      break;
    case '10Y':
      d.setFullYear(d.getFullYear() - 10);
      break;
    case '20Y':
      d.setFullYear(d.getFullYear() - 20);
      break;
    case 'YTD':
      d.setMonth(0, 1);
      d.setHours(0, 0, 0, 0);
      break;
    default:
      d.setFullYear(d.getFullYear() - 1);
  }
  return d.toISOString().split('T')[0];
}

/** Human-readable label for a period (used in subtitles). */
export function periodLabel(label: string): string {
  switch (label) {
    case 'YTD':
      return 'year to date';
    case '1M':
      return '1 month';
    case '3M':
      return '3 months';
    case '6M':
      return '6 months';
    case '1Y':
      return '1 year';
    default: {
      const n = parseInt(label, 10);
      const unit = label.endsWith('Y') ? 'year' : 'month';
      return `${n} ${unit}${n === 1 ? '' : 's'}`;
    }
  }
}
