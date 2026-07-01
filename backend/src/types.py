"""
Shared type aliases for Pydantic v2 JSON serialisation.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Annotated

from pydantic import PlainSerializer

# Serialise ``Decimal`` as ``float`` in JSON output.
# Replaces the deprecated ``ConfigDict(json_encoders={Decimal: float})`` pattern.
DecimalAsFloat = Annotated[
    Decimal,
    PlainSerializer(lambda x: float(x), return_type=float, when_used="json"),
]
