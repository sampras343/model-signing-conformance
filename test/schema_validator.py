"""OMS bundle schema validation — delegates to the ``oms-schemas`` package.

The ``oms-schemas`` package (from the model-signing-spec repository) is the
single source of truth for schema definitions, validation logic, and
method-specific structural checks.  This module re-exports its API so that
the conformance test code has a stable local import path.
"""

from oms_schemas import validate_bundle, validate_method_fields, decode_payload

__all__ = ["validate_bundle", "validate_method_fields", "decode_payload"]
