"""
Prediction module — LSTM directional forecasting endpoint.

Loads the champion GlobalLSTM model at startup and serves predictions
via GET /predict/{ticker} with Redis 6h caching.
"""

from __future__ import annotations
