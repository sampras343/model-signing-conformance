"""Parametrized bundle verification tests.

Each subdirectory in test/assets/verify/ is one test case.
- Directories without a ``_fail`` suffix must verify successfully.
- Directories with a ``_fail`` suffix must fail verification (non-zero exit).

Each directory must contain:
  - ``config.json``  — verification parameters (see client.VerifyConfig)
  - ``bundle.sig``   — the pre-committed bundle to verify
  - model files      — at the path specified by config.json ``model_path``
  - key material     — at paths specified in config.json (relative to the case dir)

Optional:
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

    # Resolve model path (relative to the test case directory)
    model_path = verify_dir / cfg.model_path
    if not model_path.exists():
        pytest.fail(f"Model path does not exist: {model_path}")

    # Run verification — key paths are relative to ASSETS, not the case dir
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
