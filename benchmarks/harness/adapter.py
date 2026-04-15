"""Adapter invocation utilities for the benchmark harness.

Provides pure command-building functions and a capabilities query so that
both the benchmark harness (run.py) and any future tooling build adapter
commands from a single source of truth.

None of these functions execute subprocesses directly (except
query_capabilities and run_benchmark, which must call the adapter).
Timing and subprocess management remain in run.py.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from benchmarks.harness.run import KeyMaterial


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
    """Return the argv list for a verify-model invocation.

    ``public_key`` is omitted from the command when empty — certificate
    verification uses ``--cert-chain`` flags (supplied via ``extra_flags``)
    rather than a public key.
    """
    cmd = [
        entrypoint, "verify-model",
        "--method", method,
        "--model-path", str(model_path),
        "--bundle", str(bundle_path),
    ]
    if public_key:
        cmd += ["--public-key", public_key]
    cmd += list(extra_flags)
    return cmd


def build_benchmark_cmd(
    entrypoint: str,
    model_path: Path,
    bundle_path: Path | None,
    operation: str,
    method: str,
    keys: KeyMaterial,
    repeat: int,
    extra_flags: list[str] = (),
) -> list[str]:
    """Return the argv list for a benchmark-model invocation.

    Uses KeyMaterial to derive key paths and method-specific flags,
    keeping this function consistent with how run.py works.
    """
    cmd = [
        entrypoint, "benchmark-model",
        "--operation", operation,
        "--model-path", str(model_path),
        "--repeat", str(repeat),
    ]
    if operation != "hash":
        cmd += ["--method", method]
        if bundle_path is not None:
            bundle_flag = "--output-bundle" if operation == "sign" else "--bundle"
            cmd += [bundle_flag, str(bundle_path)]
        key = keys.sign_key(method) if operation == "sign" else keys.verify_key(method)
        if key:
            key_flag = "--private-key" if operation == "sign" else "--public-key"
            cmd += [key_flag, key]
    cmd += list(extra_flags)
    return cmd


def run_benchmark(
    entrypoint: str,
    model_path: Path,
    bundle_path: Path | None,
    operation: str,
    method: str,
    keys: KeyMaterial,
    repeat: int,
    extra_flags: list[str] = (),
) -> tuple[list[float], str]:
    """Call benchmark-model and return (times_ms, error_string).

    Returns an empty list and an error string on failure.
    The adapter handles its own timing loop and returns JSON:
        {"times_ms": [123.4, 121.8, ...]}
    """
    cmd = build_benchmark_cmd(entrypoint, model_path, bundle_path,
                               operation, method, keys, repeat, extra_flags)
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=3600)
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        return [], str(exc)

    if result.returncode != 0:
        return [], result.stderr.strip()

    try:
        data = json.loads(result.stdout)
        if "error" in data and "times_ms" not in data:
            return [], data["error"]
        times = [float(t) for t in data["times_ms"]]
        return times, ""
    except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        return [], f"invalid response ({exc}): {result.stdout[:200]}"


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
