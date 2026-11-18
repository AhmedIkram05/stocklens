"""Guards schema.graphql against drift from the Strawberry schema it mirrors.

``schema.graphql`` is the codegen source for ``frontend/src/graphql/generated.ts``,
but nothing regenerates it from ``backend/src/graphql/schema.py``. A schema change
that skips the regen step silently ships frontend types that no longer match the
server. Comparing parsed schemas makes formatting differences irrelevant, so only
real drift fails.
"""

from __future__ import annotations

from pathlib import Path

from graphql import build_schema, print_schema

SDL_PATH = Path(__file__).resolve().parents[2] / "schema.graphql"


def test_committed_sdl_matches_strawberry_schema() -> None:
    from src.graphql.schema import schema

    committed = print_schema(build_schema(SDL_PATH.read_text()))
    generated = print_schema(build_schema(schema.as_str()))

    assert committed == generated, (
        "schema.graphql is out of sync with backend/src/graphql/schema.py.\n"
        "Regenerate the SDL (keep the header comment):\n"
        "  cd backend && uv run python -c "
        '"from src.graphql.schema import schema; print(schema.as_str())"'
        "\nThen run `npm run graphql:codegen` and commit both files."
    )
