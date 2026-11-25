/** Receipt parsing helpers for extracting monetary amounts from OCR text. */

/**
 * Return true if the receipt's amounts are denominated in a non-GBP currency
 * ($ or €). Receipts are GBP-only; foreign-currency receipts should be
 * rejected and re-entered in £.
 *
 * Only currency symbols attached to an amount token count (`$9.99`, `€3,50`,
 * `12$`) — a bare `$` in prose, brand names, or OCR noise must not reject the
 * receipt. A £ amount token anywhere wins: fine print like "RRP $9.99" on an
 * otherwise-GBP receipt is not the receipt's denomination.
 */
export function hasForeignCurrency(text: string): boolean {
  if (!text) return false;
  const hasGbpAmount = /(?:£\s*\d)|(?:\d\s*£)/.test(text);
  if (hasGbpAmount) return false;
  return /(?:[$€]\s*\d)|(?:\d\s*[$€])/.test(text);
}
