"""Sign-then-verify round-trip tests.

Each subdirectory in test/test-cases/roundtrip/ is one test case with a
``config.json`` that specifies the method, model, key material, and expected
outcomes.  Shared assets (models, keys) live in test/assets/.

These tests require signing capability and are skipped when ``--skip-signing`` is passed.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import pytest

from .client import ModelSigningClient, CaseConfig, _read_identity_token
from .schema_validator import validate_bundle, decode_payload


def _sigstore_token_available() -> bool:
    return bool(_read_identity_token("SIGSTORE_ID_TOKEN"))

ASSETS = Path(__file__).parent / "assets"


def _assert_resources_sorted(bundle_path: Path) -> None:
    """Assert resource descriptors in the predicate are sorted by name (§6.4)."""
    bundle = json.loads(bundle_path.read_text())
    statement = decode_payload(bundle)
    resources = statement.get("predicate", {}).get("resources", [])
    names = [r["name"] for r in resources]
    assert names == sorted(names), (
        f"Resource descriptors must be lexicographically sorted by name.\n"
        f"  got: {names}\n"
        f"  want: {sorted(names)}"
    )


def _assert_root_digest(bundle_path: Path) -> None:
    """Assert subject digest matches SHA-256 over concatenated resource digests (§6.5.1).

    The root digest is computed as:
      SHA-256( raw_bytes(resource[0].digest) || raw_bytes(resource[1].digest) || ... )
    where resources are in canonical (sorted-by-name) order and each hex digest
    is decoded to raw bytes before concatenation.
    """
    bundle = json.loads(bundle_path.read_text())
    statement = decode_payload(bundle)

    resources = statement["predicate"]["resources"]
    concat = b""
    for r in resources:
        concat += bytes.fromhex(r["digest"])
    expected = hashlib.sha256(concat).hexdigest()

    subjects = statement.get("subject", [])
    assert len(subjects) == 1, f"Expected exactly 1 subject, got {len(subjects)}"
    actual = subjects[0].get("digest", {}).get("sha256")
    assert actual is not None, "subject[0].digest.sha256 is missing"
    assert actual == expected, (
        f"Root digest mismatch (§6.5.1):\n"
        f"  subject.digest.sha256: {actual}\n"
        f"  recomputed from resources: {expected}"
    )


def _assert_statement_fields(bundle_path: Path) -> None:
    """Assert in-toto statement has correct _type, predicateType, and payload type (§5.1, §8.3)."""
    bundle = json.loads(bundle_path.read_text())

    payload_type = bundle["dsseEnvelope"]["payloadType"]
    assert payload_type == "application/vnd.in-toto+json", (
        f"payloadType must be 'application/vnd.in-toto+json', got '{payload_type}'"
    )

    statement = decode_payload(bundle)

    stmt_type = statement.get("_type")
    assert stmt_type == "https://in-toto.io/Statement/v1", (
        f"_type must be 'https://in-toto.io/Statement/v1', got '{stmt_type}'"
    )

    pred_type = statement.get("predicateType")
    assert pred_type == "https://model_signing/signature/v1.0", (
        f"predicateType must be 'https://model_signing/signature/v1.0', got '{pred_type}'"
    )


def _assert_subject(bundle_path: Path) -> None:
    """Assert subject has exactly one entry with non-empty name and sha256 digest (§6.5)."""
    bundle = json.loads(bundle_path.read_text())
    statement = decode_payload(bundle)
    subjects = statement.get("subject", [])
    assert len(subjects) == 1, f"subject must contain exactly one entry, got {len(subjects)}"
    subj = subjects[0]
    name = subj.get("name", "")
    assert name and isinstance(name, str), (
        f"subject[0].name must be a non-empty string, got '{name}'"
    )
    digest = subj.get("digest", {})
    assert "sha256" in digest, "subject[0].digest must contain 'sha256' key (§6.5.1)"


def _assert_serialization_fields(bundle_path: Path) -> None:
    """Assert serialization object has all required fields (§5.2.2)."""
    bundle = json.loads(bundle_path.read_text())
    statement = decode_payload(bundle)
    serialization = statement.get("predicate", {}).get("serialization", {})

    method = serialization.get("method")
    assert method in ("files", "shards"), (
        f"serialization.method must be 'files' or 'shards', got '{method}'"
    )

    assert "hash_type" in serialization, "serialization.hash_type is required (§5.2.2)"
    assert "allow_symlinks" in serialization, "serialization.allow_symlinks is required (§5.2.2)"

    if method == "files":
        assert "shard_size" not in serialization, (
            "shard_size must be absent when method is 'files' (§5.2.2)"
        )
    elif method == "shards":
        shard_size = serialization.get("shard_size")
        assert isinstance(shard_size, int) and shard_size > 0, (
            f"shard_size must be a positive integer when method is 'shards', got {shard_size}"
        )


def _assert_resource_fields(bundle_path: Path) -> None:
    """Assert each resource descriptor has required fields (§5.2.1)."""
    bundle = json.loads(bundle_path.read_text())
    statement = decode_payload(bundle)
    resources = statement.get("predicate", {}).get("resources", [])
    assert len(resources) >= 1, "resources must contain at least one entry (§5.2.1)"
    for i, r in enumerate(resources):
        assert "name" in r, f"resources[{i}] missing 'name' (§5.2.1)"
        assert "digest" in r, f"resources[{i}] missing 'digest' (§5.2.1)"
        assert "algorithm" in r, f"resources[{i}] missing 'algorithm' (§5.2.1)"
        name = r["name"]
        assert not name.startswith("/"), f"resources[{i}].name must not start with '/' (§6.1.2)"
        assert "../" not in name, f"resources[{i}].name must not contain '../' (§6.1.2)"
        assert not name.endswith("/"), f"resources[{i}].name must not end with '/' (§6.1.2)"


def _assert_signature_excluded(bundle_path: Path, model_path: Path) -> None:
    """Assert the bundle file itself is not listed in resources (§6.2)."""
    bundle = json.loads(bundle_path.read_text())
    statement = decode_payload(bundle)
    names = {r["name"] for r in statement["predicate"]["resources"]}

    bundle_name = bundle_path.name
    try:
        rel = bundle_path.resolve().relative_to(model_path.resolve())
        bundle_name = str(rel).replace("\\", "/")
    except ValueError:
        pass

    assert bundle_name not in names, (
        f"Signature file '{bundle_name}' must be excluded from resources (§6.2)"
    )


@pytest.mark.signing
def test_roundtrip(
    client: ModelSigningClient, roundtrip_dir: Path, tmp_path: Path,
    request: pytest.FixtureRequest,
) -> None:
    """Sign a model then verify the produced bundle with the same client."""
    config_path = roundtrip_dir / "config.json"
    if not config_path.exists():
        pytest.fail(f"Missing config.json in {roundtrip_dir}")

    cfg = CaseConfig.from_json(config_path)
    label = f"{roundtrip_dir.name}: {cfg.description}"

    if cfg.method == "sigstore" and request.config.getoption("--skip-sigstore"):
        pytest.skip(f"[{label}] skipped (--skip-sigstore)")
    if cfg.requires_ci and not _sigstore_token_available():
        pytest.skip(f"[{label}] requires OIDC token (set SIGSTORE_ID_TOKEN or SIGSTORE_ID_TOKEN_FILE)")

    model_src = ASSETS / cfg.model
    if not model_src.exists():
        pytest.fail(f"Model directory not found: {model_src}")

    model_copy = tmp_path / "model"
    shutil.copytree(model_src, model_copy)

    if cfg.model_modifications:
        cfg.model_modifications.apply(model_copy)

    if cfg.sig_inside_model:
        bundle_path = model_copy / "bundle.sig"
    else:
        bundle_path = tmp_path / "bundle.sig"

    sign_result = client.sign(
        method=cfg.method,
        model_path=model_copy,
        output_bundle=bundle_path,
        cfg=cfg,
        assets_root=ASSETS,
    )

    if cfg.expect == "fail":
        assert sign_result.returncode != 0, (
            f"[{label}] Expected signing to FAIL but it succeeded.\n"
            f"stdout: {sign_result.stdout}\nstderr: {sign_result.stderr}"
        )
        return

    assert sign_result.returncode == 0, (
        f"[{label}] Signing failed.\n"
        f"stdout: {sign_result.stdout}\nstderr: {sign_result.stderr}"
    )
    assert bundle_path.exists(), f"[{label}] bundle.sig not created after signing"

    validate_bundle(bundle_path, method=cfg.method)
    _assert_statement_fields(bundle_path)
    _assert_subject(bundle_path)
    _assert_serialization_fields(bundle_path)
    _assert_resource_fields(bundle_path)
    _assert_resources_sorted(bundle_path)
    _assert_root_digest(bundle_path)
    if cfg.sig_inside_model:
        _assert_signature_excluded(bundle_path, model_copy)

    verify_block = cfg.verify
    if verify_block and verify_block.ignore_unsigned_files and verify_block.ignore_paths:
        (model_copy / "injected.bin").write_text("injected after signing\n")

    verify_result = client.verify(
        method=cfg.method,
        model_path=model_copy,
        bundle=bundle_path,
        cfg=cfg,
        keys_root=ASSETS,
    )
    assert verify_result.returncode == 0, (
        f"[{label}] Verification failed.\n"
        f"stdout: {verify_result.stdout}\nstderr: {verify_result.stderr}"
    )

    if cfg.expected_signed_files:
        actual = client.get_signed_files(bundle_path)
        assert actual == sorted(cfg.expected_signed_files), (
            f"[{label}] Signed files mismatch:\n"
            f"  expected: {sorted(cfg.expected_signed_files)}\n"
            f"  actual:   {actual}"
        )

    if "deterministic" in roundtrip_dir.name:
        bundle_path2 = tmp_path / "bundle2.sig"
        sign_result2 = client.sign(
            method=cfg.method,
            model_path=model_copy,
            output_bundle=bundle_path2,
            cfg=cfg,
            assets_root=ASSETS,
        )
        assert sign_result2.returncode == 0
        assert client.get_signed_files(bundle_path) == client.get_signed_files(bundle_path2), (
            f"[{label}] Non-deterministic signing detected"
        )
