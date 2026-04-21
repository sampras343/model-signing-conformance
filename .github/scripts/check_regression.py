#!/usr/bin/env python3
"""Check for benchmark performance regressions by comparing current vs. previous results.

Loads per-client JSON result files from two directories (current and previous),
matches scenarios by a composite key, and flags any throughput drop exceeding
the configured threshold.

Exit code 0 = no regressions, 1 = at least one regression detected.

Usage:
    python check_regression.py \
        --current-dir  results/ \
        --previous-dir previous/ \
        --threshold 20
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ResultKey = tuple[str, str, str, int, str | None]


def _load_dir(results_dir: Path) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for path in sorted(results_dir.glob("*.json")):
        try:
            data = json.loads(path.read_text())
            if isinstance(data, list):
                out[path.stem] = data
        except Exception:
            pass
    return out


def _result_key(r: dict) -> ResultKey:
    p = r.get("parameters", {})
    return (
        r.get("client", ""),
        r.get("scenario", ""),
        r.get("operation", ""),
        p.get("model_size_bytes", 0),
        p.get("method"),
    )


def _index_results(all_results: dict[str, list[dict]]) -> dict[ResultKey, float]:
    """Build a lookup from result key to throughput (MB/s)."""
    index: dict[ResultKey, float] = {}
    for results in all_results.values():
        for r in results:
            if r.get("status", "ok") != "ok":
                continue
            key = _result_key(r)
            mbps = r.get("results", {}).get("throughput_mbps", 0.0)
            if mbps > 0:
                index[key] = mbps
    return index


def _fmt_size(n: int) -> str:
    for unit, thresh in [("GB", 1024**3), ("MB", 1024**2), ("KB", 1024)]:
        if n >= thresh:
            return f"{n / thresh:.0f}{unit}"
    return f"{n}B"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Check for benchmark throughput regressions."
    )
    parser.add_argument("--current-dir", required=True, metavar="DIR",
                        help="Directory containing current result JSON files")
    parser.add_argument("--previous-dir", required=True, metavar="DIR",
                        help="Directory containing previous result JSON files")
    parser.add_argument("--threshold", type=float, default=20.0, metavar="PCT",
                        help="Throughput drop percentage to flag as regression (default: 20)")
    args = parser.parse_args(argv)

    current = _index_results(_load_dir(Path(args.current_dir)))
    previous = _index_results(_load_dir(Path(args.previous_dir)))

    if not previous:
        print("No previous results found — skipping regression check")
        return 0

    shared_keys = sorted(set(current) & set(previous))
    if not shared_keys:
        print("No matching scenarios between current and previous — skipping")
        return 0

    regressions = []
    print(f"Comparing {len(shared_keys)} scenario(s) (threshold: {args.threshold}% drop)\n")
    print(f"{'Client':<12} {'Scenario':<26} {'Size':<8} {'Prev MB/s':>10} {'Curr MB/s':>10} {'Delta':>8}")
    print("-" * 78)

    for key in shared_keys:
        client, scenario, _op, size_bytes, _method = key
        prev_mbps = previous[key]
        curr_mbps = current[key]
        delta_pct = ((curr_mbps - prev_mbps) / prev_mbps) * 100

        marker = ""
        if delta_pct <= -args.threshold:
            marker = " << REGRESSION"
            regressions.append((client, scenario, size_bytes, prev_mbps, curr_mbps, delta_pct))

        print(f"{client:<12} {scenario:<26} {_fmt_size(size_bytes):<8} "
              f"{prev_mbps:>10.1f} {curr_mbps:>10.1f} {delta_pct:>+7.1f}%{marker}")

    print()
    if regressions:
        print(f"REGRESSION DETECTED: {len(regressions)} scenario(s) dropped "
              f"by more than {args.threshold}%")
        for client, scenario, size_bytes, prev, curr, delta in regressions:
            print(f"  {client}/{scenario} ({_fmt_size(size_bytes)}): "
                  f"{prev:.1f} -> {curr:.1f} MB/s ({delta:+.1f}%)")
        return 1

    print("No regressions detected")
    return 0


if __name__ == "__main__":
    sys.exit(main())
