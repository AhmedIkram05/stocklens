"""LangSmith-native evaluation harness for the StockLens agent."""

from __future__ import annotations


def __getattr__(name: str):
    """Lazy import — avoid pulling in the full agent stack unless needed.

    ``python -m agent_eval.upload_dataset`` loads this module first; with
    eager imports it would pull ``run_experiment`` → ``src.agent.graph`` →
    ``src.config.Settings`` → crash on missing ``JWT_SECRET_KEY`` in CI.
    """
    import importlib

    _MAP = {
        "run_experiment": "agent_eval.run_experiment",
        "upload_dataset": "agent_eval.upload_dataset",
    }
    if name in _MAP:
        mod = importlib.import_module(_MAP[name])
        return getattr(mod, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = ["run_experiment", "upload_dataset"]
