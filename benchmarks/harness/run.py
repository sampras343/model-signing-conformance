"""Benchmark harness — orchestrates adapter invocations and collects timing results.

Reads a scenario YAML (or a directory of YAMLs), generates synthetic models,
times the adapter's sign-model / verify-model commands, and writes structured
JSON results conforming to benchmarks/schema/result.schema.json.

Usage:
    # Single scenario
    python -m benchmarks.harness.run \\
        --entrypoint ./adapter \\
        --scenario benchmarks/scenarios/sign_throughput.yaml \\
        --private-key test/assets/keys/p384/signing-key.pem \\
        --public-key  test/assets/keys/p384/signing-key-pub.pem \\
        --output benchmark-results.json

    # All scenarios in a directory
    python -m benchmarks.harness.run \\
        --entrypoint ./adapter \\
        --scenarios benchmarks/scenarios/ \\
        --private-key test/assets/keys/p384/signing-key.pem \\
        --public-key  test/assets/keys/p384/signing-key-pub.pem \\
        --output benchmark-results.json

    # CI mode — respects ci_max_size caps in each scenario
    python -m benchmarks.harness.run ... --ci
"""

from __future__ import annotations

import argparse
import datetime
import json
import math
import os
import platform
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

import yaml

from benchmarks.harness.adapter import (
    build_sign_cmd, build_verify_cmd, query_capabilities, run_benchmark,
)
from benchmarks.harness.generate import main as generate_main, _parse_size


# ---------------------------------------------------------------------------
# Size helpers
# ---------------------------------------------------------------------------

def _size_to_bytes(value: str | int) -> int:
    if isinstance(value, int):
        return value
    return _parse_size(str(value))


def _fmt_size(n: int) -> str:
    for unit, thresh in [("GB", 1024**3), ("MB", 1024**2), ("KB", 1024)]:
        if n >= thresh:
            return f"{n / thresh:.0f}{unit}"
    return f"{n}B"


# ---------------------------------------------------------------------------
# Statistics
# ---------------------------------------------------------------------------

def _stats(times_ms: list[float], size_bytes: int) -> dict[str, Any]:
    n = len(times_ms)
    mean = sum(times_ms) / n
    variance = sum((t - mean) ** 2 for t in times_ms) / n
    stddev = math.sqrt(variance)
    throughput = (size_bytes / 1024 / 1024) / (mean / 1000)  # MB/s
    return {
        "repeat": n,
        "times_ms": [round(t, 3) for t in times_ms],
        "mean_ms": round(mean, 3),
        "min_ms": round(min(times_ms), 3),
        "stddev_ms": round(stddev, 3),
        "throughput_mbps": round(throughput, 2),
    }


# ---------------------------------------------------------------------------
# System info
# ---------------------------------------------------------------------------

def _system_info() -> dict[str, Any]:
    info: dict[str, Any] = {
        "cpu_count": os.cpu_count() or 0,
        "platform": platform.platform(),
        "timestamp_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }
    # Enrich with RAM and CPU model if psutil/py-cpuinfo are available.
    # These are optional — benchmarks run fine without them, but the extra
    # context helps reproduce and compare results across machines (mirrors
    # what time_serialize.py captures in the original model-transparency suite).
    try:
        import psutil  # type: ignore[import-untyped]
        info["ram_gb"] = round(psutil.virtual_memory().total / 1024**3, 1)
    except ImportError:
        pass
    try:
        import cpuinfo  # type: ignore[import-untyped]
        info["cpu_model"] = cpuinfo.get_cpu_info().get("brand_raw", "")
    except ImportError:
        pass
    return info


# ---------------------------------------------------------------------------
# Adapter invocation
# ---------------------------------------------------------------------------

def _time_command(cmd: list[str]) -> tuple[float, int, str]:
    """Run a command and return (elapsed_ms, returncode, stderr)."""
    t0 = time.perf_counter()
    result = subprocess.run(cmd, capture_output=True, text=True)
    return (time.perf_counter() - t0) * 1000, result.returncode, result.stderr


def _adapter_name(entrypoint: str) -> str:
    return Path(entrypoint).stem


# ---------------------------------------------------------------------------
# Model generation
# ---------------------------------------------------------------------------

def _generate_model(tmp_dir: Path, size: str, files: int, run_idx: int) -> Path:
    model_root = tmp_dir / f"model_{run_idx}"
    shape = "file" if files == 1 else "dir"
    args = [shape, "--root", str(model_root), "--size", size]
    if shape == "dir":
        args += ["--files", str(files)]
    generate_main(args)
    return model_root


# ---------------------------------------------------------------------------
# Benchmark execution
# ---------------------------------------------------------------------------

def _bench_sign(
    entrypoint: str,
    model_path: Path,
    bundle_path: Path,
    method: str,
    private_key: str,
    repeat: int,
    extra_flags: list[str],
) -> tuple[list[float], list[str]]:
    times, errors = [], []
    for _ in range(repeat):
        bundle_path.unlink(missing_ok=True)
        cmd = build_sign_cmd(entrypoint, model_path, bundle_path,
                             method, private_key, extra_flags)
        elapsed_ms, rc, stderr = _time_command(cmd)
        if rc != 0:
            errors.append(stderr.strip())
        else:
            times.append(elapsed_ms)
    return times, errors


def _bench_verify(
    entrypoint: str,
    model_path: Path,
    bundle_path: Path,
    method: str,
    public_key: str,
    repeat: int,
    extra_flags: list[str],
) -> tuple[list[float], list[str]]:
    times, errors = [], []
    for _ in range(repeat):
        cmd = build_verify_cmd(entrypoint, model_path, bundle_path,
                               method, public_key, extra_flags)
        elapsed_ms, rc, stderr = _time_command(cmd)
        if rc != 0:
            errors.append(stderr.strip())
        else:
            times.append(elapsed_ms)
    return times, errors


def _sign_once(
    entrypoint: str,
    model_path: Path,
    bundle_path: Path,
    method: str,
    private_key: str,
    extra_flags: list[str],
) -> bool:
    """Sign once as untimed setup for a verify benchmark."""
    cmd = build_sign_cmd(entrypoint, model_path, bundle_path,
                         method, private_key, extra_flags)
    result = subprocess.run(cmd, capture_output=True, text=True)
    return result.returncode == 0


# ---------------------------------------------------------------------------
# Scenario loading and sweep expansion
# ---------------------------------------------------------------------------

def _load_scenario(path: Path) -> dict:
    with path.open() as fh:
        return yaml.safe_load(fh)


def _ci_cap_bytes(scenario: dict) -> int | None:
    raw = scenario.get("ci_max_size")
    return _size_to_bytes(str(raw)) if raw is not None else None


def _expand_sweep(scenario: dict, ci: bool) -> list[dict]:
    """Return one parameter dict per benchmark row."""
    ci_cap = _ci_cap_bytes(scenario) if ci else None
    sweep = scenario.get("sweep", {})
    # Scenario-level flags are prepended to every row's extra_flags.
    # Used for material that applies to all rows but isn't a swept parameter,
    # e.g. --signing-cert and --cert-chain for certificate benchmark scenarios.
    scenario_flags: list[str] = scenario.get("flags", [])
    rows = []

    if "model_shape" in sweep:
        # Throughput scenarios: list of {size, files}
        for shape in sweep["model_shape"]:
            size_bytes = _size_to_bytes(str(shape["size"]))
            if ci_cap is not None and size_bytes > ci_cap:
                continue
            rows.append({
                "size": str(shape["size"]),
                "size_bytes": size_bytes,
                "files": shape.get("files", 1),
                "extra_flags": list(scenario_flags),
                "sweep_param": None,
                "sweep_value": None,
            })
    else:
        # Parameter sweep scenarios: single model_shape, one swept flag.
        # YAML keys use hyphens to match adapter flag names, e.g. hash-algorithm.
        base = scenario.get("model_shape", {"size": "100MB", "files": 1})
        size_bytes = _size_to_bytes(str(base["size"]))
        if ci_cap is not None:
            size_bytes = min(size_bytes, ci_cap)
        size_str = _fmt_size(size_bytes)
        files = base.get("files", 1)

        for flag_name, values in sweep.items():
            for value in values:
                rows.append({
                    "size": size_str,
                    "size_bytes": size_bytes,
                    "files": files,
                    "extra_flags": list(scenario_flags) + [f"--{flag_name}", str(value)],
                    # Store in result JSON with underscores, e.g. hash_algorithm
                    "sweep_param": flag_name.replace("-", "_"),
                    "sweep_value": value,
                })

    return rows


# ---------------------------------------------------------------------------
# Capabilities check
# ---------------------------------------------------------------------------

def _check_requires(scenario: dict, capabilities: dict) -> str | None:
    """Return a skip reason string if the scenario cannot run, else None."""
    supported = set(capabilities.get("flags", []))
    required = set(scenario.get("requires_flags", []))
    missing = required - supported
    if missing:
        return f"adapter missing flags: {', '.join(sorted(missing))}"
    return None


# ---------------------------------------------------------------------------
# Result building
# ---------------------------------------------------------------------------

def _build_result(
    client: str,
    scenario_name: str,
    operation: str,
    method: str,
    row: dict,
    times_ms: list[float],
    scenario_defaults: dict | None = None,
) -> dict:
    params: dict[str, Any] = {
        "model_size_bytes": row["size_bytes"],
        "file_count": row["files"],
        "method": method or None,   # None for operation:hash (method-independent)
        "hash_algorithm": None,
        "serialization": None,
        "chunk_size": None,
        "max_workers": None,
        "shard_size": None,
    }
    # Apply scenario-level defaults (e.g. hash_algorithm, serialization)
    if scenario_defaults:
        for k, v in scenario_defaults.items():
            params[k] = v
    # Overlay the swept parameter value — takes precedence over defaults
    if row["sweep_param"] is not None:
        params[row["sweep_param"]] = row["sweep_value"]

    return {
        "client": client,
        "client_version": "",
        "scenario": scenario_name,
        "operation": operation,
        "parameters": params,
        "results": _stats(times_ms, row["size_bytes"]),
        "system": _system_info(),
    }


# ---------------------------------------------------------------------------
# Table printing
# ---------------------------------------------------------------------------

_W = {"scenario": 22, "op": 6, "size": 8, "files": 6,
      "mean_ms": 10, "min_ms": 10, "stddev_ms": 10, "mbps": 9}


def _print_header() -> None:
    h = (f"{'Scenario':<{_W['scenario']}} {'Op':<{_W['op']}} "
         f"{'Size':<{_W['size']}} {'Files':>{_W['files']}} "
         f"{'Mean ms':>{_W['mean_ms']}} {'Min ms':>{_W['min_ms']}} "
         f"{'Stddev':>{_W['stddev_ms']}} {'MB/s':>{_W['mbps']}}")
    print(h)
    print("-" * len(h))


def _print_row(result: dict) -> None:
    p = result["parameters"]
    r = result["results"]
    print(
        f"{result['scenario']:<{_W['scenario']}} "
        f"{result['operation']:<{_W['op']}} "
        f"{_fmt_size(p['model_size_bytes']):<{_W['size']}} "
        f"{p['file_count']:>{_W['files']}} "
        f"{r['mean_ms']:>{_W['mean_ms']}.1f} "
        f"{r['min_ms']:>{_W['min_ms']}.1f} "
        f"{r['stddev_ms']:>{_W['stddev_ms']}.1f} "
        f"{r['throughput_mbps']:>{_W['mbps']}.1f}"
    )


# ---------------------------------------------------------------------------
# Main runner
# ---------------------------------------------------------------------------

def run_scenario(
    scenario: dict,
    entrypoint: str,
    private_key: str,
    public_key: str,
    capabilities: dict,
    ci: bool,
    tmp_dir: Path,
    signing_cert: str = "",
    cert_chain: list[str] | None = None,
) -> list[dict]:
    name = scenario["name"]

    skip_reason = _check_requires(scenario, capabilities)
    if skip_reason:
        print(f"  [skip] {name}: {skip_reason}")
        return []

    operation = scenario["operation"]
    method = scenario.get("method", "")  # empty for operation:hash

    # hash operation requires in-process timing (no standalone CLI command exists).
    if operation == "hash" and not capabilities.get("benchmark_model"):
        print(f"  [skip] {name}: operation:hash requires benchmark_model capability")
        return []
    repeat = scenario.get("repeat", 5)
    rows = _expand_sweep(scenario, ci)

    if not rows:
        print(f"  [skip] {name}: all rows filtered by ci_max_size")
        return []

    results = []
    client = _adapter_name(entrypoint)
    use_inproc = capabilities.get("benchmark_model", False)

    # For certificate method: build extra flags that inject cert material into
    # every adapter invocation (both timed and untimed setup calls).
    cert_extra_flags: list[str] = []
    if method == "certificate":
        if signing_cert:
            cert_extra_flags += ["--signing-cert", signing_cert]
        for cert in (cert_chain or []):
            cert_extra_flags += ["--cert-chain", cert]

    for idx, row in enumerate(rows):
        label = _fmt_size(row["size_bytes"])
        if row["sweep_param"]:
            label += f" {row['sweep_param']}={row['sweep_value']}"
        else:
            label += f" x {row['files']} file(s)"
        mode = "inproc" if use_inproc else "subprocess"
        print(f"  {name} / {operation} / {label} [{mode}] ...", end=" ", flush=True)

        model_path = _generate_model(tmp_dir, row["size"], row["files"], idx)
        bundle_path = tmp_dir / f"bundle_{idx}.sig"

        errors: list[str] = []

        # Merge scenario cert flags with per-row sweep flags.
        row_flags = cert_extra_flags + row["extra_flags"]

        if use_inproc:
            # Adapter handles its own timing loop in-process — one subprocess call
            # per scenario row. Eliminates per-iteration startup overhead.
            if operation == "hash":
                times, err = run_benchmark(
                    entrypoint, model_path, None, "hash",
                    "", "", repeat, row_flags,
                )
                if err:
                    errors.append(err)
            elif operation == "sign":
                times, err = run_benchmark(
                    entrypoint, model_path, bundle_path, "sign",
                    method, private_key, repeat, row_flags,
                    signing_cert=signing_cert, cert_chain=cert_chain,
                )
                if err:
                    errors.append(err)
            elif operation == "verify":
                if not _sign_once(entrypoint, model_path, bundle_path,
                                  method, private_key, row_flags):
                    print("SETUP FAILED (sign step)")
                    continue
                # Certificate verify uses cert chain — no public key concept.
                verify_key = "" if method == "certificate" else public_key
                times, err = run_benchmark(
                    entrypoint, model_path, bundle_path, "verify",
                    method, verify_key, repeat, row_flags,
                    cert_chain=cert_chain,
                )
                if err:
                    errors.append(err)
            else:
                print(f"unknown operation '{operation}', skipping")
                continue
        else:
            # Fallback: separate subprocess per timed iteration.
            if operation == "sign":
                times, errors = _bench_sign(
                    entrypoint, model_path, bundle_path, method,
                    private_key, repeat, row_flags,
                )
            elif operation == "verify":
                if not _sign_once(entrypoint, model_path, bundle_path,
                                  method, private_key, row_flags):
                    print("SETUP FAILED (sign step)")
                    continue
                # Certificate verify: no public key, cert chain is in row_flags.
                verify_key = "" if method == "certificate" else public_key
                times, errors = _bench_verify(
                    entrypoint, model_path, bundle_path, method,
                    verify_key, repeat, row_flags,
                )
            else:
                print(f"unknown operation '{operation}', skipping")
                continue

        if errors:
            print(f"ERRORS ({len(errors)}/{repeat} runs failed):")
            for e in errors[:3]:
                print(f"    {e}")

        if not times:
            print("  no successful runs — skipping result")
            continue

        result = _build_result(client, name, operation, method, row, times,
                               scenario_defaults=scenario.get("defaults"))
        results.append(result)
        r = result["results"]
        print(f"mean={r['mean_ms']:.0f}ms  throughput={r['throughput_mbps']:.1f} MB/s")
        _print_row(result)

    return results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m benchmarks.harness.run",
        description="Run model-signing benchmarks against a conformance adapter.",
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--scenario", metavar="YAML",
                       help="Path to a single scenario YAML file")
    group.add_argument("--scenarios", metavar="DIR",
                       help="Directory of scenario YAML files (runs all *.yaml)")

    parser.add_argument("--entrypoint", required=True,
                        help="Path to the conformance adapter binary/script")
    parser.add_argument("--private-key", required=True,
                        help="Private key PEM (e.g. test/assets/keys/p384/signing-key.pem)")
    parser.add_argument("--public-key", required=True,
                        help="Public key PEM for key-method verification")
    parser.add_argument("--signing-cert", default="",
                        help="Signing certificate PEM for certificate-method scenarios")
    parser.add_argument("--cert-chain", action="append", default=[],
                        metavar="PEM",
                        help="Certificate chain PEM for certificate-method scenarios "
                             "(repeat for multiple: --cert-chain int-ca.pem --cert-chain ca.pem)")
    parser.add_argument("--output", required=True,
                        help="Output JSON file (array of result objects)")
    parser.add_argument("--ci", action="store_true",
                        help="Cap model sizes to ci_max_size defined in each scenario")

    args = parser.parse_args(argv)

    scenario_files = (
        [Path(args.scenario)]
        if args.scenario
        else sorted(Path(args.scenarios).glob("**/*.yaml"))
    )
    if not scenario_files:
        print(f"No *.yaml files found in {args.scenarios}", file=sys.stderr)
        return 1

    # Query capabilities once; all scenarios share the same adapter.
    capabilities = query_capabilities(args.entrypoint)
    supported = capabilities.get("flags", [])
    if supported:
        print(f"Adapter capabilities: {', '.join(supported)}")
    else:
        print("Adapter capabilities: none declared (parameter sweep scenarios will be skipped)")

    all_results: list[dict] = []

    with tempfile.TemporaryDirectory(prefix="msb_") as tmp:
        tmp_dir = Path(tmp)
        print()
        _print_header()

        for scenario_file in scenario_files:
            scenario = _load_scenario(scenario_file)
            print(f"\n[{scenario['name']}] {scenario.get('description', '')}")
            results = run_scenario(
                scenario=scenario,
                entrypoint=args.entrypoint,
                private_key=args.private_key,
                public_key=args.public_key,
                capabilities=capabilities,
                ci=args.ci,
                tmp_dir=tmp_dir,
                signing_cert=args.signing_cert,
                cert_chain=args.cert_chain,
            )
            all_results.extend(results)

    output = Path(args.output)
    output.write_text(json.dumps(all_results, indent=2))
    print(f"\nWrote {len(all_results)} result(s) to {output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
