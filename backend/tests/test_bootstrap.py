"""Champion bootstrap: follow the pointer, keep a legacy fallback."""

from __future__ import annotations

import importlib.util
from pathlib import Path

_BOOTSTRAP_PATH = Path(__file__).resolve().parents[1] / "docker" / "bootstrap.py"
_spec = importlib.util.spec_from_file_location("stocklens_bootstrap", _BOOTSTRAP_PATH)
assert _spec and _spec.loader
bootstrap = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bootstrap)


class _Body:
    def __init__(self, value: str) -> None:
        self._value = value

    def read(self) -> bytes:
        return self._value.encode()


class _FakeS3:
    def __init__(self, keys: list[str], pointer: str | None = None) -> None:
        self.keys = keys
        self.pointer = pointer
        self.downloaded: list[str] = []

    def get_object(self, Bucket: str, Key: str):  # noqa: N803
        if self.pointer and Key.endswith("/current"):
            return {"Body": _Body(self.pointer)}
        raise KeyError(Key)

    def list_objects_v2(self, Bucket: str, Prefix: str):  # noqa: N803
        return {"Contents": [{"Key": key} for key in self.keys if key.startswith(Prefix)]}

    def download_file(self, bucket: str, key: str, filename: str) -> None:
        self.downloaded.append(key)
        Path(filename).parent.mkdir(parents=True, exist_ok=True)
        Path(filename).write_bytes(b"x")


def _run(monkeypatch, tmp_path, s3: _FakeS3) -> None:
    monkeypatch.setenv("CHAMPION_S3_URI", "s3://bucket/champion/")
    monkeypatch.setenv("MODEL_ARTIFACT_DIR", str(tmp_path))
    monkeypatch.setenv("ENVIRONMENT", "test")
    monkeypatch.setattr(bootstrap.boto3, "client", lambda *a, **k: s3)
    bootstrap.main()


def test_bootstrap_follows_pointer(monkeypatch, tmp_path) -> None:
    s3 = _FakeS3(
        [
            "champion/versions/v1/model.pt",
            "champion/versions/v1/model_seed0.pt",
            "champion/current",
        ],
        pointer="v1",
    )
    _run(monkeypatch, tmp_path, s3)

    assert (tmp_path / "versions" / "v1" / "model.pt").exists()
    assert (tmp_path / "versions" / "v1" / "model_seed0.pt").exists()
    assert (tmp_path / "current").read_text() == "v1"
    assert all("/versions/v1/" in key for key in s3.downloaded)


def test_bootstrap_legacy_layout(monkeypatch, tmp_path) -> None:
    (tmp_path / "current").write_text("stale")
    s3 = _FakeS3(["champion/model.pt", "champion/model_seed0.pt"])
    _run(monkeypatch, tmp_path, s3)

    assert (tmp_path / "model.pt").exists()
    assert (tmp_path / "model_seed0.pt").exists()
    assert not (tmp_path / "current").exists()
    assert s3.downloaded == ["champion/model.pt", "champion/model_seed0.pt"]
