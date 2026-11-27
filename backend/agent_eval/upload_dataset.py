"""Upload the StockLens golden evaluation dataset to LangSmith.

Run manually (or via CI) to populate/update the `stocklens-golden` dataset.
Idempotent: re-running adds only questions that are not already present, so
prior experiments and feedback keep their example links.
"""

from __future__ import annotations

import json
from pathlib import Path

from langsmith import Client

DATASET_NAME = "stocklens-golden"
_HERE = Path(__file__).parent
_DATASET_PATH = _HERE / "golden_dataset.json"


def load_questions() -> list[dict]:
    """Read the golden dataset questions array from disk.

    Accepts either a bare JSON array or an object with a ``questions`` key.
    """
    with _DATASET_PATH.open() as f:
        data = json.load(f)
    return data if isinstance(data, list) else data["questions"]


def upload_dataset(client: Client | None = None) -> None:
    """Create (or reset) the golden dataset in LangSmith."""
    client = client or Client()
    questions = load_questions()
    if client.has_dataset(dataset_name=DATASET_NAME):
        dataset = client.read_dataset(dataset_name=DATASET_NAME)
        existing = {
            example.inputs.get("question")
            for example in client.list_examples(dataset_id=dataset.id)
        }
    else:
        dataset = client.create_dataset(
            dataset_name=DATASET_NAME,
            description="StockLens agent golden evaluation questions",
        )
        existing = set()
    new_questions = [q for q in questions if q["question"] not in existing]
    if new_questions:
        client.create_examples(
            inputs=[{"question": q["question"]} for q in new_questions],
            dataset_id=dataset.id,
        )


if __name__ == "__main__":
    upload_dataset()
