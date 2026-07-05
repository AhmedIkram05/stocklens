/**
 * Prediction service - LSTM directional forecasts from backend.
 */

import { apiService } from './api';

export interface PredictionResponse {
  ticker: string;
  direction: 'UP' | 'FLAT' | 'DOWN';
  confidence: number;
  probabilities: {
    DOWN: number;
    FLAT: number;
    UP: number;
  };
  model_version: string;
  cached: boolean;
  predicted_at: string;
}

export const predictionService = {
  async getPrediction(ticker: string): Promise<PredictionResponse> {
    return apiService.get<PredictionResponse>(`/predict/${ticker}`);
  },
};
