/**
 * useReceipts
 *
 * Fetch and manage receipts for a user; subscribes to changes and polls periodically.
 */

import { useEffect, useRef, useState, useCallback } from 'react';
import { receiptService } from '../services/dataService';
import { subscribe } from '../services/eventBus';
import { formatRelativeDate } from '../utils/formatters';

export type ReceiptShape = {
  /** Unique receipt identifier (string representation of Firestore document ID) */
  id: string;
  /** Formatted label for display (relative date like "2 days ago" or "Yesterday") */
  label: string;
  /** Total purchase amount in currency */
  amount: number;
  /** ISO date string of when receipt was scanned */
  date: string;
  /** Time string (e.g., "14:30") for display purposes */
  time: string;
  /** URI to receipt image in Firebase Storage */
  image: string;
};

/**
 * Fetches receipts for the given user ID and subscribes to changes.
 * Automatically refreshes when 'receipts-changed' event is emitted.
 * Polls every 30 seconds for freshness while mounted.
 */
export default function useReceipts(userId?: string) {
  const [receipts, setReceipts] = useState<ReceiptShape[]>([]);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);
  const mountedRef = useRef(true);

  const fetch = useCallback(
    async (opts: { silent?: boolean } = {}) => {
      if (!opts.silent) setLoading(true);
      setError(null);
      try {
        if (!userId) {
          setReceipts([]);
          return;
        }
        const data = await receiptService.getByUserId(userId);
        if (!mountedRef.current) return;
        const mapped = data.map((r: any) => ({
          id: String(r.id),
          label: formatRelativeDate(r.date_scanned) || 'Receipt',
          amount: r.total_amount || 0,
          date: r.date_scanned || '',
          time: '',
          image: r.image_uri || undefined,
        }));
        setReceipts(mapped);
      } catch (err: any) {
        if (mountedRef.current) setError(err?.message || String(err));
      } finally {
        if (mountedRef.current && !opts.silent) setLoading(false);
      }
    },
    [userId],
  );

  useEffect(() => {
    mountedRef.current = true;
    fetch().catch(() => {});

    const unsub = subscribe('receipts-changed', async (payload) => {
      if (payload?.userId && payload.userId !== userId) return;
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
  }, [fetch, userId]);

  return { receipts, loading, error } as const;
}
