/**
 * useReceipts
 *
 * Fetch and manage receipts for a user; subscribes to changes and polls periodically.
 */

import { useEffect, useRef, useState, useCallback } from 'react';
import { receiptService } from '../services/receipts';
import { subscribe } from '../services/eventBus';
import { formatRelativeDate } from '../utils/formatters';

export type ReceiptShape = {
  /** Unique receipt identifier (API document ID) */
  id: string;
  /** Formatted label for display (relative date like "2 days ago" or "Yesterday") */
  label: string;
  /** Total purchase amount in currency */
  amount: number;
  /** ISO date string of when receipt was scanned */
  date: string;
  /** Time string (e.g., "14:30") for display purposes */
  time: string;
  /** URI to receipt image (S3 key or local) */
  image: string;
  /** OCR extraction source: "regex" | "cascade" | "degraded" | "failed" */
  source?: string;
  /** OCR extraction confidence 0-100 */
  confidence?: number;
};

/**
 * Fetches receipts for the authenticated user and subscribes to changes.
 * Automatically refreshes when 'receipts-changed' event is emitted.
 * Polls every 30 seconds for freshness while mounted.
 */
export default function useReceipts() {
  const [receipts, setReceipts] = useState<ReceiptShape[]>([]);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);
  const mountedRef = useRef(true);

  const fetch = useCallback(async (opts: { silent?: boolean } = {}) => {
    if (!opts.silent) setLoading(true);
    setError(null);
    try {
      const data = await receiptService.list();
      if (!mountedRef.current) return;
      const mapped = data.map((r: any) => ({
        id: String(r.id),
        label: formatRelativeDate(r.scanned_at) || 'Receipt',
        amount: r.total_amount || 0,
        date: r.scanned_at || '',
        time: '',
        image: r.receipt_image_s3_key || undefined,
        source: r.source || undefined,
        confidence: r.ocr_confidence != null ? Number(r.ocr_confidence) : undefined,
      }));
      setReceipts(mapped);
    } catch (err: any) {
      if (mountedRef.current) setError(err?.message || String(err));
    } finally {
      if (mountedRef.current && !opts.silent) setLoading(false);
    }
  }, []);

  useEffect(() => {
    mountedRef.current = true;
    fetch().catch(() => {});

    const unsub = subscribe('receipts-changed', async () => {
      await fetch({ silent: true });
    });

    // Poll while mounted (keeps UI reasonably fresh); consumer can still control refresh
    const id = setInterval(() => fetch({ silent: true }).catch(() => {}), 30000);

    return () => {
      mountedRef.current = false;
      try {
        unsub();
      } catch (e) {}
      clearInterval(id);
    };
  }, [fetch]);

  return { receipts, loading, error } as const;
}
