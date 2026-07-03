"""
StockLens ML module - PyTorch LSTM directional forecasting.

This module runs as a separate Docker Compose service (not part of the backend).
It trains a global multi-ticker LSTM model and logs results to MLflow.
"""

from __future__ import annotations
