#!/usr/bin/env python3
"""
bootstrap.py — download champion model from S3 before the app starts.

Runs as Docker ENTRYPOINT. Downloads model.pt from CHAMPION_S3_URI to
/model_artifacts/champion/model.pt, then execs the CMD (uvicorn).
"""

import os
import sys
from pathlib import Path

import boto3


def main() -> None:
    champion_s3_uri = os.environ.get("CHAMPION_S3_URI", "")
    environment = os.environ.get("ENVIRONMENT", "development")

    # Production fast-fail: champion required in prod
    if environment == "production" and not champion_s3_uri:
        print("[bootstrap] FATAL: CHAMPION_S3_URI required in production", file=sys.stderr)
        sys.exit(1)

    if not champion_s3_uri:
        print("[bootstrap] CHAMPION_S3_URI not set — skipping S3 download")
        return  # fall through to os.execvp below

    # s3://bucket/prefix/ → bucket, prefix
    parts = champion_s3_uri.removeprefix("s3://").rstrip("/").split("/", 1)
    bucket = parts[0]
    key = f"{parts[1]}/model.pt" if len(parts) > 1 else "model.pt"
    dest = Path("/model_artifacts/champion/model.pt")
    dest.parent.mkdir(parents=True, exist_ok=True)

    s3 = boto3.client("s3", region_name=os.environ.get("AWS_REGION", "eu-west-2"))
    try:
        s3.download_file(bucket, key, str(dest))
        print(f"[bootstrap] champion model downloaded from s3://{bucket}/{key}")
    except Exception as exc:
        print(f"[bootstrap] WARNING: champion download failed ({exc})", file=sys.stderr)
        if environment == "production":
            sys.exit(1)


if __name__ == "__main__":
    main()
    # hand off to uvicorn (CMD)
    os.execvp(sys.argv[1], sys.argv[1:])
