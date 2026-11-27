"""Tests for the LangSmith golden-dataset upsert."""

from __future__ import annotations

from types import SimpleNamespace

from agent_eval import upload_dataset as upload


class _FakeClient:
    def __init__(self, existing: list[str]) -> None:
        self._existing = existing
        self.created: list[dict] = []

    def has_dataset(self, dataset_name: str) -> bool:
        return True

    def read_dataset(self, dataset_name: str):
        return SimpleNamespace(id="dataset-1")

    def list_examples(self, dataset_id: str):
        return [SimpleNamespace(inputs={"question": q}) for q in self._existing]

    def create_examples(self, inputs, dataset_id):
        self.created = list(inputs)

    def delete_dataset(self, dataset_name: str):
        raise AssertionError("must not delete the dataset")


def test_adds_only_missing_questions(monkeypatch):
    monkeypatch.setattr(
        upload,
        "load_questions",
        lambda: [{"question": "Q1"}, {"question": "Q2"}],
    )
    client = _FakeClient(existing=["Q1"])

    upload.upload_dataset(client)

    assert client.created == [{"question": "Q2"}]


def test_no_write_when_all_present(monkeypatch):
    monkeypatch.setattr(upload, "load_questions", lambda: [{"question": "Q1"}])
    client = _FakeClient(existing=["Q1"])

    upload.upload_dataset(client)

    assert client.created == []
