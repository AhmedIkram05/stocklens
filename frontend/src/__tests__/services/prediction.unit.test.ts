import { predictionService } from '@/services/prediction';
import { apiService } from '@/services/api';

jest.mock('@/services/api', () => ({
  apiService: {
    get: jest.fn(),
  },
}));

const mockedApiGet = apiService.get as jest.MockedFunction<typeof apiService.get>;

describe('predictionService', () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  it('fetches prediction for a ticker', async () => {
    const mockPrediction = {
      ticker: 'AAPL',
      direction: 'UP' as const,
      confidence: 0.85,
      probabilities: { DOWN: 0.1, FLAT: 0.05, UP: 0.85 },
      model_version: 'v1.0',
      cached: false,
      predicted_at: '2025-01-01T10:00:00Z',
    };
    mockedApiGet.mockResolvedValue(mockPrediction);

    const result = await predictionService.getPrediction('AAPL');

    expect(apiService.get).toHaveBeenCalledWith('/predict/AAPL');
    expect(result).toEqual(mockPrediction);
  });

  it('handles API errors', async () => {
    mockedApiGet.mockRejectedValue(new Error('Prediction service unavailable'));

    await expect(predictionService.getPrediction('AAPL')).rejects.toThrow(
      'Prediction service unavailable',
    );
  });
});
