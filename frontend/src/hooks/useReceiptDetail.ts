/**
 * useReceiptDetail
 *
 * Loads and normalises a single receipt: fetches the authoritative record from
 * the backend (the scan endpoint persists merchant + line items; route params
 * are only a fast path), loads the category list, and derives the display
 * values (total, merchant, line-item subtotal, mismatch flag, category name).
 */

import { useCallback, useEffect, useState } from 'react';
import { receiptService } from '../services/receipts';
import { categoryService, type Category } from '../services/categories';

type RouteParams = {
  receiptId?: string;
  totalAmount?: number;
  merchantName?: string | null;
  lineItems?: any[];
};

export default function useReceiptDetail({
  receiptId,
  totalAmount: initialAmount,
  merchantName: initialMerchant,
  lineItems: initialItems,
}: RouteParams) {
  const [receipt, setReceipt] = useState<any>(null);
  const [categories, setCategories] = useState<Category[]>([]);

  // The scan endpoint already persisted these; route params are only a fast path.
  const loadReceiptDetail = useCallback(async () => {
    if (!receiptId) return;
    try {
      const r = await receiptService.getById(receiptId);
      if (r) setReceipt(r);
    } catch {
      // Keep previous receipt on failure
    }
  }, [receiptId]);

  useEffect(() => {
    loadReceiptDetail().catch(() => {});
  }, [loadReceiptDetail]);

  const loadCategories = useCallback(async () => {
    try {
      setCategories(await categoryService.listCategories());
    } catch {
      // Keep previous categories on failure
    }
  }, []);

  useEffect(() => {
    loadCategories().catch(() => {});
  }, [loadCategories]);

  const totalAmount = receipt?.total_amount ?? initialAmount ?? 0;
  const merchantName: string | null = receipt?.merchant_name ?? initialMerchant ?? null;
  const rawLineItems = receipt?.line_items;
  const lineItems: any[] = rawLineItems
    ? Array.isArray(rawLineItems)
      ? rawLineItems
      : Object.values(rawLineItems)
    : (initialItems ?? []);

  // Cross-check: sum of line items vs scanned total (flags likely OCR total misread)
  const itemsSubtotal = lineItems.reduce(
    (sum: number, it: any) => sum + (Number(it?.price ?? it?.amount ?? 0) || 0),
    0,
  );
  const totalMismatch =
    lineItems.length > 0 &&
    Math.abs(itemsSubtotal - totalAmount) > Math.max(0.02, (totalAmount || 0) * 0.01);

  const categoryName: string | null = categories.length
    ? (categories.find((c) => c.id === (receipt?.category_id ?? null))?.name ?? null)
    : null;

  return {
    receipt,
    setReceipt,
    categories,
    categoryName,
    totalAmount,
    merchantName,
    lineItems,
    itemsSubtotal,
    totalMismatch,
    loadReceiptDetail,
    loadCategories,
  } as const;
}
