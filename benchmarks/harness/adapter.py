"""Adapter invocation utilities for the benchmark harness.

Provides pure command-building functions and a capabilities query so that
both the benchmark harness (run.py) and any future tooling build adapter
commands from a single source of truth.

None of these functions execute subprocesses directly (except
query_capabilities, which must call the adapter). Timing and subprocess
management remain in run.py.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path


def build_sign_cmd(
    entrypoint: str,
    model_path: Path,
    bundle_path: Path,
    method: str,
    private_key: str,
    extra_flags: list[str] = (),
) -> list[str]:
    """Return the argv list for a sign-model invocation."""
    return [
        entrypoint, "sign-model",
        "--method", method,
        "--model-path", str(model_path),
        "--output-bundle", str(bundle_path),
        "--private-key", private_key,
        *extra_flags,
    ]


def build_verify_cmd(
    entrypoint: str,
    model_path: Path,
    bundle_path: Path,
    method: str,
    public_key: str,
    extra_flags: list[str] = (),
) -> list[str]:
    """Return the argv list for a verify-model invocation."""
    return [
        entrypoint, "verify-model",
        "--method", method,
        "--model-path", str(model_path),
        "--bundle", str(bundle_path),
        "--public-key", public_key,
        *extra_flags,
    ]


def query_capabilities(entrypoint: str) -> dict:
    """Call `<adapter> capabilities` and return the parsed response.

    Returns {"flags": []} if the adapter does not implement the command
    (non-zero exit, unrecognised subcommand, or invalid JSON). This means
    the harness will only run scenarios with requires_flags: [].
    """
    try:
        result = subprocess.run(
            [entrypoint, "capabilities"],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return {"flags": []}

    if result.returncode != 0:
        return {"flags": []}

    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        return {"flags": []}
