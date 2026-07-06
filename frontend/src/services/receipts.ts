/**
 * receipts.ts
 *
 * Receipt service using the StockLens FastAPI backend.
 *
 * Replaces the SQLite-based receiptService from dataService.ts.
 * All receipt CRUD operations now go through the backend API.
 */

import { apiService, ApiError } from './api';

// ── Types ─────────────────────────────────────────────────────────────────────

export interface Receipt {
  id: string;
  user_id: string;
  total_amount: number;
  merchant_name: string | null;
  category_id: string | null;
  ocr_raw_text: string | null;
  ocr_confidence: number | null;
  line_items: Record<string, unknown> | null;
  receipt_image_s3_key: string | null;
  source?: string;
  scanned_at: string;
  created_at: string;
}

export interface ReceiptCreate {
  user_id?: string;
  total_amount?: number;
  merchant_name?: string;
  category_id?: string;
  ocr_raw_text?: string;
  ocr_confidence?: number;
  line_items?: Record<string, unknown>;
  receipt_image_s3_key?: string;
}

export interface ReceiptUpdate {
  total_amount?: number;
  merchant_name?: string;
  category_id?: string;
  ocr_raw_text?: string;
  ocr_confidence?: number;
  line_items?: Record<string, unknown>;
}

export interface ReceiptListResponse {
  items: Receipt[];
  total: number;
  limit: number;
  offset: number;
}

export interface ScanResponse {
  id: string;
  extraction: {
    merchant_name: string | null;
    total: number | null;
    date: string | null;
    currency: string;
    items: Array<{ name: string; quantity: number; price: number }>;
  };
  raw_text: string;
  source: string;
  confidence: number;
  processing_time_ms: number;
  error?: string | null;
}

// ── Service ───────────────────────────────────────────────────────────────────

export const receiptService = {
  /**
   * Create a new receipt.
   *
   * @param receipt - Receipt data to create
   * @returns Created receipt with ID
   */
  async create(receipt: ReceiptCreate): Promise<Receipt> {
    // user_id is set by the backend from the JWT token
    const data = { ...receipt };
    delete data.user_id;
    return apiService.post<Receipt>('/receipts', data);
  },

  /**
   * Get all receipts for the authenticated user.
   *
   * @param limit - Maximum number of receipts to return (default 50)
   * @param offset - Number of receipts to skip (default 0)
   * @returns Paginated list of receipts
   */
  async list(limit = 50, offset = 0): Promise<Receipt[]> {
    const response = await apiService.get<ReceiptListResponse>(
      `/receipts?limit=${limit}&offset=${offset}`,
    );
    return response.items;
  },

  /**
   * Get a single receipt by ID.
   *
   * @param id - Receipt ID
   * @returns Receipt or null if not found
   */
  async getById(id: string): Promise<Receipt | null> {
    try {
      return await apiService.get<Receipt>(`/receipts/${id}`);
    } catch (error) {
      if (error instanceof ApiError && error.status === 404) {
        return null;
      }
      throw error;
    }
  },

  /**
   * Update a receipt.
   *
   * @param id - Receipt ID
   * @param receipt - Partial receipt data to update
   */
  async update(id: string, receipt: ReceiptUpdate): Promise<void> {
    await apiService.put<void>(`/receipts/${id}`, receipt);
  },

  /**
   * Delete a receipt.
   *
   * @param id - Receipt ID
   */
  async delete(id: string): Promise<void> {
    await apiService.delete<void>(`/receipts/${id}`);
  },

  /**
   * Delete all receipts for the authenticated user.
   *
   * Note: This is a convenience method that fetches all receipts and deletes them one by one.
   * The backend doesn't have a bulk delete endpoint, so this may be slow for large datasets.
   */
  async deleteAll(): Promise<void> {
    const receipts = await this.list(1000, 0); // Fetch up to 1000 receipts
    await Promise.all(receipts.map((r) => this.delete(r.id)));
  },

  /**
   * Scan a receipt image and extract data via the cascade OCR backend.
   *
   * @param imageUri - Local URI of the receipt image
   * @returns Scan response with extracted receipt data
   */
  async scan(imageUri: string): Promise<ScanResponse> {
    const formData = new FormData();
    formData.append('file', {
      uri: imageUri,
      type: 'image/jpeg',
      name: 'receipt.jpg',
    } as any);
    return apiService.upload<ScanResponse>('/receipts/scan', formData);
  },

  /**
   * Check the health of the cascade OCR pipeline.
   *
   * @returns Health status with individual component checks
   */
  async checkHealth(): Promise<{
    status: string;
    checks: Record<string, string>;
    cascade_threshold: number;
  }> {
    return apiService.get('/receipts/cascade/health');
  },
};
