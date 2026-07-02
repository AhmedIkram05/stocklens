/**
 * Formatters
 *
 * Currency and date formatting helpers (GBP, relative dates).
 */

/** Format number as GBP (e.g., "£12.50"). */
export function formatCurrencyGBP(amount: number) {
  try {
    return new Intl.NumberFormat('en-GB', {
      style: 'currency',
      currency: 'GBP',
      minimumFractionDigits: 2,
    }).format(amount || 0);
  } catch (e) {
    return `£${(amount || 0).toFixed(2)}`;
  }
}

/** Format ISO date as a short relative string (e.g., "3h ago", "Yesterday"). */
export function formatRelativeDate(isoDate?: string) {
  if (!isoDate) return 'Receipt';
  try {
    const d = new Date(isoDate);
    const now = new Date();
    const diffMs = now.getTime() - d.getTime();
    const diffSec = Math.floor(diffMs / 1000);
    const diffMin = Math.floor(diffSec / 60);
    const diffHours = Math.floor(diffMin / 60);
    const diffDays = Math.floor(diffHours / 24);

    if (diffSec < 60) return `${diffSec}s ago`;
    if (diffMin < 60) return `${diffMin}m ago`;
    if (diffHours < 24) return `${diffHours}h ago`;
    if (diffDays === 1) return 'Yesterday';
    if (diffDays <= 7) return `${diffDays} days ago`;

    return d.toLocaleDateString(undefined, { day: 'numeric', month: 'short', year: 'numeric' });
  } catch (e) {
    return 'Receipt';
  }
}

/** Format currency with exactly two decimal places (GBP). */
export function formatCurrencyRounded(amount: number) {
  try {
    return new Intl.NumberFormat('en-GB', {
      style: 'currency',
      currency: 'GBP',
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    }).format(amount || 0);
  } catch (e) {
    return `£${(amount || 0).toFixed(2)}`;
  }
}
