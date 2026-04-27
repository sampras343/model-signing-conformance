"""OMS bundle schema validation — delegates to the ``oms-schemas`` package.

The ``oms-schemas`` package (from the model-signing-spec repository) is the
single source of truth for schema definitions, validation logic, and
method-specific structural checks.  This module re-exports its API so that
the conformance test code has a stable local import path.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from oms_schemas import (
    validate_bundle as _validate_bundle,
    validate_method_fields,
    decode_payload,
)

SCHEMA_VERSION = "v1.0"


def validate_bundle(
    bundle_path: Path,
    method: Optional[str] = None,
    schema_version: Optional[str] = None,
) -> None:
    """Validate a bundle, defaulting to the conformance suite's pinned schema version."""
    _validate_bundle(
        bundle_path,
        method=method,
        schema_version=schema_version or SCHEMA_VERSION,
    )


__all__ = ["validate_bundle", "validate_method_fields", "decode_payload", "SCHEMA_VERSION"]
