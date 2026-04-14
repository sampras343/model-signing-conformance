"""Synthetic model generator for benchmarks.

Creates reproducible model files of configurable size and shape.
The same command always produces the same file contents (fixed seed),
so benchmark runs are reproducible across machines.

Usage:
    python -m benchmarks.harness.generate file   --root PATH --size SIZE
    python -m benchmarks.harness.generate dir    --root PATH --size SIZE --files N
    python -m benchmarks.harness.generate matrix --root PATH --size SIZE --dirs M --files N

SIZE may use suffixes: KB, MB, GB (case-insensitive). E.g. 100MB, 1GB, 512KB.

Writes a _generate_meta.json alongside the model so the harness knows the
exact byte counts without re-scanning the tree.
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path


_CHUNK = 4 * 1024 * 1024  # 4 MB write chunks — limits peak memory


def _parse_size(value: str) -> int:
    """Parse a human-readable size string to bytes."""
    value = value.strip()
    suffixes = {"kb": 1024, "mb": 1024**2, "gb": 1024**3}
    lower = value.lower()
    for suffix, multiplier in suffixes.items():
        if lower.endswith(suffix):
            return int(float(value[: -len(suffix)]) * multiplier)
    return int(value)


def _write_file(path: Path, size_bytes: int, rng: random.Random) -> None:
    """Write exactly size_bytes of pseudo-random data to path."""
    path.parent.mkdir(parents=True, exist_ok=True)
    remaining = size_bytes
    with path.open("wb") as fh:
        while remaining > 0:
            chunk_size = min(_CHUNK, remaining)
            fh.write(rng.randbytes(chunk_size))
            remaining -= chunk_size


def _write_meta(root: Path, total_bytes: int, file_count: int, shape: str) -> None:
    meta = {
        "shape": shape,
        "total_bytes": total_bytes,
        "file_count": file_count,
    }
    (root / "_generate_meta.json").write_text(json.dumps(meta, indent=2))


def cmd_file(args: argparse.Namespace) -> int:
    """Generate a single model file."""
    size = _parse_size(args.size)
    root = Path(args.root)
    root.mkdir(parents=True, exist_ok=True)

    rng = random.Random(args.seed)
    _write_file(root / "model.bin", size, rng)
    _write_meta(root, size, 1, "file")

    print(f"Generated: {root / 'model.bin'}  ({size:,} bytes)")
    return 0


def cmd_dir(args: argparse.Namespace) -> int:
    """Generate N files in a single directory, total size distributed evenly."""
    total = _parse_size(args.size)
    n = args.files
    root = Path(args.root)
    root.mkdir(parents=True, exist_ok=True)

    per_file = total // n
    remainder = total - per_file * n

    rng = random.Random(args.seed)
    for i in range(n):
        size = per_file + (remainder if i == n - 1 else 0)
        _write_file(root / f"file_{i:04d}.bin", size, rng)

    _write_meta(root, total, n, "dir")
    print(f"Generated: {n} files in {root}  ({total:,} bytes total)")
    return 0


def cmd_matrix(args: argparse.Namespace) -> int:
    """Generate M directories x N files each, total size distributed evenly."""
    total = _parse_size(args.size)
    m, n = args.dirs, args.files
    root = Path(args.root)
    root.mkdir(parents=True, exist_ok=True)

    file_count = m * n
    per_file = total // file_count
    remainder = total - per_file * file_count

    rng = random.Random(args.seed)
    idx = 0
    for d in range(m):
        for f in range(n):
            size = per_file + (remainder if idx == file_count - 1 else 0)
            _write_file(root / f"dir_{d:03d}" / f"file_{f:04d}.bin", size, rng)
            idx += 1

    _write_meta(root, total, file_count, "matrix")
    print(f"Generated: {m}x{n} matrix in {root}  ({total:,} bytes total)")
    return 0


def cmd_nested(args: argparse.Namespace) -> int:
    """Generate N files nested M directories deep (one file per leaf directory).

    Structure: root/d0/d1/.../d(M-1)/file_N.bin
    Each of the N files lives at the bottom of an M-level directory chain,
    simulating deeply nested model repositories (e.g. HuggingFace-style layouts).
    """
    total = _parse_size(args.size)
    m, n = args.dirs, args.files
    root = Path(args.root)
    root.mkdir(parents=True, exist_ok=True)

    per_file = total // n
    remainder = total - per_file * n

    rng = random.Random(args.seed)
    for i in range(n):
        # Build a path that is M levels deep, e.g. level_0/level_1/.../file_i.bin
        deep_dir = root
        for d in range(m):
            deep_dir = deep_dir / f"level_{d}"
        size = per_file + (remainder if i == n - 1 else 0)
        _write_file(deep_dir / f"file_{i:04d}.bin", size, rng)

    _write_meta(root, total, n, "nested")
    print(f"Generated: {n} files nested {m} levels deep in {root}  ({total:,} bytes total)")
    return 0


def read_meta(root: Path) -> dict:
    """Read the metadata written by a previous generate call."""
    meta_path = root / "_generate_meta.json"
    if not meta_path.exists():
        raise FileNotFoundError(f"No _generate_meta.json found in {root}")
    return json.loads(meta_path.read_text())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m benchmarks.harness.generate",
        description="Generate reproducible synthetic model files for benchmarking.",
    )
    parser.add_argument("--seed", type=int, default=42, help="RNG seed (default: 42)")

    sub = parser.add_subparsers(dest="shape", required=True)

    p_file = sub.add_parser("file", help="Single file model")
    p_file.add_argument("--root", required=True, help="Output directory")
    p_file.add_argument("--size", required=True, help="File size, e.g. 100MB")

    p_dir = sub.add_parser("dir", help="N files in one directory")
    p_dir.add_argument("--root", required=True)
    p_dir.add_argument("--size", required=True, help="Total size across all files")
    p_dir.add_argument("--files", type=int, default=10, metavar="N")

    p_mat = sub.add_parser("matrix", help="M directories x N files each")
    p_mat.add_argument("--root", required=True)
    p_mat.add_argument("--size", required=True, help="Total size across all files")
    p_mat.add_argument("--dirs", type=int, default=5, metavar="M")
    p_mat.add_argument("--files", type=int, default=10, metavar="N")

    p_nested = sub.add_parser("nested", help="N files each nested M directories deep")
    p_nested.add_argument("--root", required=True)
    p_nested.add_argument("--size", required=True, help="Total size across all files")
    p_nested.add_argument("--dirs", type=int, default=3, metavar="M",
                          help="Nesting depth (number of directory levels)")
    p_nested.add_argument("--files", type=int, default=5, metavar="N",
                          help="Number of files, each at the bottom of its own M-level chain")

    args = parser.parse_args(argv)

    dispatch = {"file": cmd_file, "dir": cmd_dir, "matrix": cmd_matrix, "nested": cmd_nested}
    return dispatch[args.shape](args)


if __name__ == "__main__":
    sys.exit(main())
