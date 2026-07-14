import { categoryService } from '@/services/categories';
import { apiService } from '@/services/api';

jest.mock('@/services/api', () => ({
  apiService: {
    get: jest.fn(),
  },
}));

const mockedApiService = apiService as jest.Mocked<typeof apiService>;

describe('categoryService', () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  it('fetches and returns categories list', async () => {
    const mockCategories = [
      { id: '1', name: 'Food & Dining', description: 'Restaurants and groceries' },
      { id: '2', name: 'Transportation', description: 'Fuel and transit' },
    ];
    mockedApiService.get.mockResolvedValue({ categories: mockCategories, total: 2 });

    const result = await categoryService.listCategories();

    expect(mockedApiService.get).toHaveBeenCalledWith('/categories');
    expect(result).toEqual(mockCategories);
  });

  it('returns empty array when response has no categories', async () => {
    mockedApiService.get.mockResolvedValue({ total: 0 });

    const result = await categoryService.listCategories();

    expect(result).toEqual([]);
  });

  it('handles API errors', async () => {
    mockedApiService.get.mockRejectedValue(new Error('Network error'));

    await expect(categoryService.listCategories()).rejects.toThrow('Network error');
  });
});
