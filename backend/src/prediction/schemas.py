"""
Pydantic schemas for the prediction endpoint.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class PredictionResponse(BaseModel):
    """Response for a directional forecast prediction."""

    ticker: str
    direction: str = Field(description="Predicted direction: UP, FLAT, or DOWN")
    confidence: float = Field(description="Confidence in the predicted class (0-1)")
    probabilities: dict[str, float] = Field(
        description="Softmax probabilities for each class: {DOWN, FLAT, UP}",
    )
    model_version: str = Field(description="MLflow model version used for prediction")
    cached: bool = Field(False, description="Whether the result was served from cache")
    predicted_at: datetime


class PredictionErrorResponse(BaseModel):
    """Error response for prediction failures."""

    detail: str
    code: str = Field(
        description="Error code: NO_DATA, MODEL_NOT_LOADED, INFERENCE_ERROR, UNKNOWN_TICKER",
    )
