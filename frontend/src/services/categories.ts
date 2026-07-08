/**
 * categories.ts
 *
 * Spending-category service backed by the StockLens FastAPI backend.
 * Used to display and let the user correct the category assigned to a receipt.
 */

import { apiService } from './api';

export interface Category {
  id: string;
  name: string;
  description?: string | null;
  merchant_keywords?: string[];
  associated_tickers?: string[];
}

export interface CategoryListResponse {
  categories: Category[];
  total: number;
}

export const categoryService = {
  /** List all spending categories. */
  async listCategories(): Promise<Category[]> {
    const res = await apiService.get<CategoryListResponse>('/categories');
    return res.categories ?? [];
  },
};
