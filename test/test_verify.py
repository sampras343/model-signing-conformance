"""Parametrized bundle verification tests.

Test cases are organized in test/test-cases/verify/ under three categories:
  - ``positive/``   — tests that must verify successfully (expect: pass)
  - ``negative/``   — tests that must fail verification (expect: fail)
  - ``historical/`` — backwards compatibility tests for older bundle formats

Each test case directory must contain:
  - ``config.json``  — verification parameters (see client.CaseConfig)
  - ``bundle.sig``   — the pre-committed bundle to verify

Shared assets (models, keys) live in test/assets/ and are referenced by
config fields resolved against that root.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from .client import ModelSigningClient, CaseConfig
from .schema_validator import validate_bundle

ASSETS = Path(__file__).parent / "assets"


def _load_xfail_reason(case_dir: Path) -> str | None:
    f = case_dir / "xfail_reason.txt"
    if f.exists():
        return f.read_text().strip()
    return None


def _resolve_model(
    cfg: CaseConfig, verify_dir: Path, tmp_path: Path
) -> Path:
    """Resolve model path and copy to temp dir."""
    if cfg.model_relative_to == "test_dir":
        model_src = verify_dir / cfg.model
    else:
        model_src = ASSETS / cfg.model

    if not model_src.exists():
        pytest.fail(f"Model not found: {model_src}")

    if model_src.is_file():
        model_copy = tmp_path / model_src.name
        shutil.copy2(model_src, model_copy)
    else:
        model_copy = tmp_path / "model"
        shutil.copytree(model_src, model_copy)

    if cfg.model_modifications:
        target = model_copy if model_copy.is_dir() else model_copy.parent
        cfg.model_modifications.apply(target)

    return model_copy


def test_verify(client: ModelSigningClient, verify_dir: Path, tmp_path: Path) -> None:
    """Verify a pre-committed bundle."""
    xfail_reason = _load_xfail_reason(verify_dir)
    if xfail_reason:
        pytest.xfail(xfail_reason)

    config_path = verify_dir / "config.json"
    if not config_path.exists():
        pytest.fail(f"Missing config.json in {verify_dir}")
    cfg = CaseConfig.from_json(config_path)

    expected_fail = cfg.expect == "fail"
    label = f"{verify_dir.name}: {cfg.description}"

    bundle = verify_dir / "bundle.sig"
    if not bundle.exists():
        pytest.fail(f"Missing bundle.sig in {verify_dir}")

    if not expected_fail and bundle.stat().st_size > 0:
        validate_bundle(bundle, method=cfg.method)

    model_path = _resolve_model(cfg, verify_dir, tmp_path)

    result = client.verify(
        method=cfg.method,
        model_path=model_path,
        bundle=bundle,
        cfg=cfg,
        keys_root=ASSETS,
    )

    if expected_fail:
        assert result.returncode != 0, (
            f"[{label}] Expected verification to FAIL but it succeeded.\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )
    else:
        assert result.returncode == 0, (
            f"[{label}] Expected verification to PASS but it failed.\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )

        if cfg.expected_signed_files:
            actual = client.get_signed_files(bundle)
            assert actual == sorted(cfg.expected_signed_files), (
                f"[{label}] Signed files mismatch:\n"
                f"  expected: {sorted(cfg.expected_signed_files)}\n"
                f"  actual:   {actual}"
            )
