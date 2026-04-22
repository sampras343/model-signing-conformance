"""Sign-then-verify round-trip tests.

Each subdirectory in test/assets/roundtrip/ is one test case with a ``config.json``
that specifies the method, model, key material, and expected outcomes.

These tests require signing capability and are skipped when ``--skip-signing`` is passed.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from .client import ModelSigningClient, CaseConfig
from .schema_validator import validate_bundle, decode_payload

ASSETS = Path(__file__).parent / "assets"


def _assert_resources_sorted(bundle_path: Path) -> None:
    """Assert resource descriptors in the predicate are sorted by name."""
    import json
    bundle = json.loads(bundle_path.read_text())
    statement = decode_payload(bundle)
    resources = statement.get("predicate", {}).get("resources", [])
    names = [r["name"] for r in resources]
    assert names == sorted(names), (
        f"Resource descriptors must be lexicographically sorted by name.\n"
        f"  got: {names}\n"
        f"  want: {sorted(names)}"
    )


@pytest.mark.signing
def test_roundtrip(
    client: ModelSigningClient, roundtrip_dir: Path, tmp_path: Path
) -> None:
    """Sign a model then verify the produced bundle with the same client."""
    config_path = roundtrip_dir / "config.json"
    if not config_path.exists():
        pytest.fail(f"Missing config.json in {roundtrip_dir}")

    cfg = CaseConfig.from_json(config_path)

    # Copy model to tmp workspace
    model_src = ASSETS / cfg.model
    if not model_src.exists():
        pytest.fail(f"Model directory not found: {model_src}")

    model_copy = tmp_path / "model"
    shutil.copytree(model_src, model_copy)

    bundle_path = tmp_path / "bundle.sig"

    # Sign (ignore_paths in cfg are relative names; sign() expands them against model_copy)
    sign_result = client.sign(
        method=cfg.method,
        model_path=model_copy,
        output_bundle=bundle_path,
        cfg=cfg,
        assets_root=ASSETS,
    )
    assert sign_result.returncode == 0, (
        f"Signing failed for {roundtrip_dir.name}\n"
        f"stdout: {sign_result.stdout}\nstderr: {sign_result.stderr}"
    )
    assert bundle_path.exists(), f"bundle.sig not created after signing for {roundtrip_dir.name}"

    validate_bundle(bundle_path, method=cfg.method)
    _assert_resources_sorted(bundle_path)

    # For ignore-unsigned tests: add an unsigned file after signing
    verify_block = cfg.verify
    if verify_block and verify_block.ignore_unsigned_files and verify_block.ignore_paths:
        (model_copy / "injected.bin").write_text("injected after signing\n")

    # Verify using the same config (verify block contains verification params)
    verify_result = client.verify(
        method=cfg.method,
        model_path=model_copy,
        bundle=bundle_path,
        cfg=cfg,
        keys_root=ASSETS,
    )
    assert verify_result.returncode == 0, (
        f"Verification failed for {roundtrip_dir.name}\n"
        f"stdout: {verify_result.stdout}\nstderr: {verify_result.stderr}"
    )

    # Validate signed files if specified
    if cfg.expected_signed_files:
        actual = client.get_signed_files(bundle_path)
        assert actual == sorted(cfg.expected_signed_files), (
            f"Signed files mismatch in {roundtrip_dir.name}:\n"
            f"  expected: {sorted(cfg.expected_signed_files)}\n"
            f"  actual:   {actual}"
        )

    # Determinism check: sign again and compare manifests
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
            f"Non-deterministic signing detected for {roundtrip_dir.name}"
        )
