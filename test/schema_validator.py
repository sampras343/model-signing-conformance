"""OMS bundle schema validation against the model-signing-spec JSON Schemas.

Schemas are installed as the ``oms-schemas`` package from the
model-signing-spec repository — the same pattern sigstore-conformance
uses with ``sigstore-protobuf-specs``.  Single source of truth, no
vendored copies.

Two-level validation:
  Level 1 (bundle):    bundle.schema.json validates outer structure
  Level 2 (statement): statement.schema.json validates decoded DSSE payload
"""

from __future__ import annotations

import base64
import json
from typing import Any

from jsonschema import Draft202012Validator
from oms_schemas import SCHEMA_DIR
from pathlib import Path
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

_bundle_validator: Draft202012Validator | None = None
_statement_validator: Draft202012Validator | None = None


def _init_validators() -> tuple[Draft202012Validator, Draft202012Validator]:
    """Load schemas from the oms-schemas package and compile validators.

    Validators are cached after first call — schemas are resolved once
    per pytest session.
    """
    global _bundle_validator, _statement_validator
    if _bundle_validator is not None and _statement_validator is not None:
        return _bundle_validator, _statement_validator

    schemas: dict[str, Any] = {}
    for f in SCHEMA_DIR.glob("*.json"):
        schemas[f.name] = json.loads(f.read_text())

    pairs = [
        (s["$id"], Resource.from_contents(s, default_specification=DRAFT202012))
        for s in schemas.values()
    ]
    registry = Registry().with_resources(pairs)

    _bundle_validator = Draft202012Validator(
        schemas["bundle.schema.json"], registry=registry
    )
    _statement_validator = Draft202012Validator(
        schemas["statement.schema.json"], registry=registry
    )
    return _bundle_validator, _statement_validator


def _decode_payload(bundle: dict[str, Any]) -> dict[str, Any]:
    """Decode the Base64-encoded DSSE payload into an in-toto Statement."""
    raw = bundle["dsseEnvelope"]["payload"]
    padded = raw + "=" * (-len(raw) % 4)
    return json.loads(base64.b64decode(padded))


DEPRECATED_PREDICATE_TYPE = "https://model_signing/Digests/v0.1"


def validate_bundle(bundle_path: Path, method: str | None = None) -> None:
    """Validate an OMS bundle file against the spec schemas.

    Args:
        bundle_path: Path to the bundle JSON file.
        method: Signing method (``key``, ``certificate``, ``sigstore``).
            Used for method-specific assertions beyond schema validation.

    Raises:
        ValidationError: If the bundle fails schema validation.
        json.JSONDecodeError: If the bundle is not valid JSON.
        AssertionError: If method-specific structural checks fail.
    """
    bundle_v, statement_v = _init_validators()

    raw = bundle_path.read_text()
    bundle = json.loads(raw)

    # Level 1: validate outer bundle structure
    bundle_v.validate(bundle)

    # Level 2: decode DSSE payload and validate statement + predicate.
    # Bundles with the deprecated predicateType (v0.2.0) have a different
    # predicate layout that the current statement schema does not cover.
    # Per SPEC.md §11, verifiers MAY support this for backward compatibility.
    statement = _decode_payload(bundle)
    if statement.get("predicateType") == DEPRECATED_PREDICATE_TYPE:
        import warnings
        warnings.warn(
            f"Bundle uses deprecated predicateType {DEPRECATED_PREDICATE_TYPE!r}; "
            f"skipping statement-level schema validation (see SPEC.md §11)",
            stacklevel=2,
        )
    else:
        statement_v.validate(statement)

    # Method-specific assertions (beyond what schema anyOf can express)
    if method:
        vm = bundle.get("verificationMaterial", {})
        _validate_method_fields(vm, method)


def _validate_method_fields(vm: dict[str, Any], method: str) -> None:
    """Assert verificationMaterial fields match the declared signing method.

    The schema uses ``anyOf`` to accept all three method variants, but it
    cannot enforce that a ``key``-method bundle uses ``publicKey`` (it would
    also pass if it had ``x509CertificateChain``). This function checks
    the correct branch was taken.
    """
    if method == "key":
        assert "publicKey" in vm, (
            "key-method bundle must contain verificationMaterial.publicKey"
        )
        assert "x509CertificateChain" not in vm, (
            "key-method bundle must not contain x509CertificateChain"
        )
        assert "certificate" not in vm, (
            "key-method bundle must not contain certificate (sigstore field)"
        )

    elif method == "certificate":
        assert "x509CertificateChain" in vm, (
            "certificate-method bundle must contain "
            "verificationMaterial.x509CertificateChain"
        )
        assert "certificate" not in vm, (
            "certificate-method bundle must not contain certificate "
            "(that is the sigstore field)"
        )

    elif method == "sigstore":
        assert "certificate" in vm, (
            "sigstore-method bundle must contain "
            "verificationMaterial.certificate (Fulcio cert)"
        )
        assert "tlogEntries" in vm, (
            "sigstore-method bundle must contain tlogEntries"
        )
        tlog = vm["tlogEntries"]
        assert isinstance(tlog, list) and len(tlog) >= 1, (
            "sigstore-method bundle must have at least one tlogEntry"
        )
