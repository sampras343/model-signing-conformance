"""Parametrized bundle verification tests.

Test cases are organized in test/assets/verify/ under three categories:
  - ``positive/``   — tests that must verify successfully (exit 0)
  - ``negative/``   — tests that must fail verification (exit non-zero, ``_fail`` suffix)
  - ``historical/`` — backwards compatibility tests for older bundle formats

Each test case directory must contain:
  - ``config.json``  — verification parameters (see client.VerifyConfig)
  - ``bundle.sig``   — the pre-committed bundle to verify

Model specification (one of):
  - ``model`` field in config.json — path relative to assets/ (preferred)
  - ``model_path`` field in config.json — path relative to test case dir (legacy)

Optional:
  - ``model_modifications`` in config.json — changes to apply before verification
  - ``xfail_reason.txt`` — if present, the test is marked xfail with that text
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from .client import ModelSigningClient, VerifyConfig

ASSETS = Path(__file__).parent / "assets"


def _load_xfail_reason(case_dir: Path) -> str | None:
    f = case_dir / "xfail_reason.txt"
    if f.exists():
        return f.read_text().strip()
    return None


def _resolve_model(
    cfg: VerifyConfig, verify_dir: Path, tmp_path: Path
) -> Path:
    """Resolve model path, copying to temp dir if using shared models."""
    if cfg.model:
        # New style: model path relative to assets/
        model_src = ASSETS / cfg.model
        if not model_src.exists():
            pytest.fail(f"Shared model not found: {model_src}")

        # Copy to temp directory
        if model_src.is_file():
            # For single-file models, preserve the filename
            model_copy = tmp_path / model_src.name
            shutil.copy2(model_src, model_copy)
        else:
            model_copy = tmp_path / "model"
            shutil.copytree(model_src, model_copy)

        # Apply modifications if specified
        if cfg.model_modifications:
            target = model_copy if model_copy.is_dir() else model_copy.parent
            cfg.model_modifications.apply(target)

        return model_copy
    elif cfg.model_path:
        # Legacy style: model path relative to test case directory
        model_path = verify_dir / cfg.model_path
        if not model_path.exists():
            pytest.fail(f"Model path does not exist: {model_path}")
        return model_path
    else:
        pytest.fail(f"Config must specify either 'model' or 'model_path'")


def test_verify(client: ModelSigningClient, verify_dir: Path, tmp_path: Path) -> None:
    """Verify a pre-committed bundle.

    Expects success for directories without ``_fail`` suffix,
    expects failure for directories with ``_fail`` suffix.
    """
    expected_fail = verify_dir.name.endswith("_fail")

    # Apply xfail from file if present
    xfail_reason = _load_xfail_reason(verify_dir)
    if xfail_reason:
        pytest.xfail(xfail_reason)

    # Load config
    config_path = verify_dir / "config.json"
    if not config_path.exists():
        pytest.fail(f"Missing config.json in {verify_dir}")
    cfg = VerifyConfig.from_json(config_path)

    # Verify bundle exists
    bundle = verify_dir / "bundle.sig"
    if not bundle.exists():
        pytest.fail(f"Missing bundle.sig in {verify_dir}")

    # Resolve model path (copy to temp if using shared models)
    model_path = _resolve_model(cfg, verify_dir, tmp_path)

    # Run verification — key paths are relative to ASSETS
    result = client.verify(
        method=cfg.method,
        model_path=model_path,
        bundle=bundle,
        cfg=cfg,
        keys_root=ASSETS,
    )

    if expected_fail:
        assert result.returncode != 0, (
            f"Expected verification to FAIL for {verify_dir.name} "
            f"but it succeeded.\nstdout: {result.stdout}\nstderr: {result.stderr}"
        )
    else:
        assert result.returncode == 0, (
            f"Expected verification to PASS for {verify_dir.name} "
            f"but it failed.\nstdout: {result.stdout}\nstderr: {result.stderr}"
        )

        # Optionally validate signed files list
        if cfg.expected_signed_files:
            actual = client.get_signed_files(bundle)
            assert actual == sorted(cfg.expected_signed_files), (
                f"Signed files mismatch in {verify_dir.name}:\n"
                f"  expected: {sorted(cfg.expected_signed_files)}\n"
                f"  actual:   {actual}"
            )
