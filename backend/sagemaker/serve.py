"""
SageMaker serving handler — thin entrypoint that reuses the existing
feature pipeline and GlobalLSTM load_model path.

Runs inside a SageMaker container. Responds to:
  GET  /ping       — health check (model loaded)
  POST /invocations — inference (returns same dict shape as Fargate path)

PREDICTION_SERVING_BACKEND=sagemaker on the Fargate task routes calls here.
"""

from __future__ import annotations

import json
import os
import sys
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import numpy as np

# ── SageMaker extracts model_data_url (tar.gz) to /opt/ml/model/
# Wait for model to appear (SageMaker extracts after container start in some cases)
MODEL_PATH = Path("/opt/ml/model/model.pt")

# Immediate debug
print(f"[sagemaker.serve] START: MODEL_PATH={MODEL_PATH}", file=sys.stderr)
print(f"[sagemaker.serve] START: /opt/ml exists={Path('/opt/ml').exists()}", file=sys.stderr)
if Path("/opt/ml").exists():
    contents = list(Path("/opt/ml").iterdir())
    print(f"[sagemaker.serve] START: /opt/ml contents={contents}", file=sys.stderr)
if Path("/opt/ml/model").exists():
    contents = list(Path("/opt/ml/model").iterdir())
    print(f"[sagemaker.serve] START: /opt/ml/model contents={contents}", file=sys.stderr)

# Wait up to 180s for SageMaker to extract model
for i in range(180):
    if MODEL_PATH.exists():
        print(f"[sagemaker.serve] Found model at {MODEL_PATH} after {i}s", file=sys.stderr)
        break
    if i % 10 == 0:
        print(f"[sagemaker.serve] Waiting for model at {MODEL_PATH}... ({i}s)", file=sys.stderr)
    time.sleep(1)
else:
    warn = f"WARNING: model not found at {MODEL_PATH} after 180s"
    print(f"[sagemaker.serve] {warn}", file=sys.stderr)
    if Path("/opt/ml").exists():
        tree = list(Path("/opt/ml").rglob("*"))
        print(f"[sagemaker.serve] /opt/ml tree: {tree}", file=sys.stderr)

CHAMPION_S3_URI = os.environ.get("CHAMPION_S3_URI", "")
ENVIRONMENT = os.environ.get("ENVIRONMENT", "development")

# Set model path env var BEFORE importing prediction_service
if MODEL_PATH.exists():
    os.environ["PREDICTION_MODEL_PATH"] = str(MODEL_PATH)
    print(f"[sagemaker.serve] Using model from SageMaker model_data_url: {MODEL_PATH}")
elif CHAMPION_S3_URI:
    # Download and extract tar.gz from S3 if SageMaker didn't extract
    import tarfile
    import tempfile

    import boto3

    dest = Path("/model_artifacts/champion/model.pt")
    dest.parent.mkdir(parents=True, exist_ok=True)

    if not dest.exists():
        print(f"[sagemaker.serve] Downloading model from {CHAMPION_S3_URI}")
        parts = CHAMPION_S3_URI.removeprefix("s3://").split("/", 1)
        bucket = parts[0]
        key = parts[1] if len(parts) > 1 else ""

        s3 = boto3.client("s3", region_name=os.environ.get("AWS_REGION", "eu-west-2"))
        with tempfile.NamedTemporaryFile(suffix=".tar.gz", delete=False) as tmp:
            s3.download_file(bucket, key, tmp.name)
            # Extract model.pt from tar.gz
            with tarfile.open(tmp.name, "r:gz") as tf:
                tf.extract("model.pt", path=dest.parent)
            print(f"[sagemaker.serve] Extracted model to {dest}")
        os.unlink(tmp.name)

    os.environ["PREDICTION_MODEL_PATH"] = str(dest)
    print(f"[sagemaker.serve] Using downloaded model: {dest}")

# ── Model load (imports from existing backend code) ──
# ponytail: reuses the same PredictionService singleton pattern as the Fargate path.

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
os.environ.setdefault("AWS_REGION", "eu-west-2")

from src.prediction.service import CLASS_NAMES, prediction_service  # noqa: E402

# Use the model path we set via env var (or the SageMaker extracted path)
model_path = os.environ.get("PREDICTION_MODEL_PATH", str(MODEL_PATH))
loaded = prediction_service.load_model(model_path)
if not loaded:
    print("[sagemaker.serve] WARNING: model not loaded at startup — /ping will return 503")


def model_fn(model_dir: str) -> None:
    """SageMaker calls this on container start to load the model.
    We already loaded at module level in the prediction_service singleton.
    """
    pass


def input_fn(request_body: str, request_content_type: str = "application/json") -> dict:
    """Deserialise the invoke payload."""
    if request_content_type == "application/json":
        return json.loads(request_body)
    raise ValueError(f"Unsupported content type: {request_content_type}")


def predict_fn(input_data: dict, model: None) -> dict:
    """Run inference on the deserialised payload.

    Expected input: {"ticker": "AAPL", "features": [[...], ...]}
    returns: {"direction": "UP", "confidence": 0.75, ...}
    """
    ticker = input_data.get("ticker", "UNKNOWN")
    features = np.array(input_data["features"], dtype=np.float32)  # (30, n_features)

    # Build tensor and run forward pass
    import torch

    ticker_upper = ticker.upper()
    vocab = getattr(prediction_service.model, "_vocab", {})
    ticker_idx_val = vocab.get(ticker_upper, 0)
    ticker_idx = torch.tensor([ticker_idx_val], dtype=torch.long)

    features_tensor = torch.tensor(features, dtype=torch.float32).unsqueeze(0)

    with torch.no_grad():
        features_tensor = features_tensor.to(prediction_service.device)
        ticker_idx = ticker_idx.to(prediction_service.device)
        logits = prediction_service.model(features_tensor, ticker_idx)
        probs = torch.softmax(logits, dim=-1).cpu().numpy()[0]

    pred_class = int(np.argmax(probs))
    return {
        "direction": CLASS_NAMES[pred_class],
        "confidence": float(probs[pred_class]),
        "probabilities": {CLASS_NAMES[i]: float(probs[i]) for i in range(len(CLASS_NAMES))},
    }


def output_fn(prediction: dict, response_content_type: str = "application/json") -> str:
    """Serialise the prediction result."""
    if response_content_type == "application/json":
        return json.dumps(prediction)
    raise ValueError(f"Unsupported content type: {response_content_type}")


# ── Simple HTTP server for SageMaker inference container (when used
# outside the SageMaker PyTorch serving toolkit) ──


def _make_app():
    """Build a minimal HTTP app for /ping and /invocations."""

    class SageMakerHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path == "/ping":
                if prediction_service.is_loaded():
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(b'{"status": "healthy"}')
                else:
                    self.send_response(503)
                    self.end_headers()
            else:
                self.send_response(404)
                self.end_headers()

        def do_POST(self):
            if self.path != "/invocations":
                self.send_response(404)
                self.end_headers()
                return
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length)
            try:
                data = input_fn(body.decode("utf-8"))
                result = predict_fn(data, None)
                output = output_fn(result)
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(output.encode("utf-8"))
            except Exception as exc:
                self.send_response(500)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"error": str(exc)}).encode("utf-8"))

        def log_message(self, format, *args):
            print(f"[sagemaker] {args[0]} {args[1]} {args[2]}", file=sys.stderr)

    return SageMakerHandler


def main():
    port = int(os.environ.get("SAGEMAKER_SERVING_PORT", 8080))
    handler_class = _make_app()
    server = HTTPServer(("0.0.0.0", port), handler_class)
    print(f"[sagemaker.serve] listening on 0.0.0.0:{port}")
    print(f"[sagemaker.serve] model loaded: {prediction_service.is_loaded()}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("[sagemaker.serve] shutting down")
        server.server_close()


if __name__ == "__main__":
    main()
