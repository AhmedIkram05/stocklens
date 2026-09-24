FROM python:3.12-slim
RUN pip install --no-cache-dir "mlflow>=3.14.0" && mkdir -p /mlflow/artifacts
CMD ["mlflow", "server", "--host", "0.0.0.0", "--port", "5001", "--backend-store-uri", "sqlite:////mlflow/mlflow.db", "--default-artifact-root", "/mlflow/artifacts"]
