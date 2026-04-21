#!/usr/bin/env python3
"""generate_benchmark_report.py — Generate HTML benchmark report from per-client JSON results.

Each client uploads a JSON array of result objects conforming to
benchmarks/schema/result.schema.json.  This script reads all per-client
files from --results-dir and renders a single HTML page with tables and
a plain-text comparison section.

Usage:
    python generate_benchmark_report.py --results-dir ./results --output results/index.html
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------

def load_results(results_dir: Path) -> dict[str, list[dict]]:
    """Return {client_name: [result, ...]} from all *.json in results_dir."""
    out: dict[str, list[dict]] = {}
    for path in sorted(results_dir.glob("*.json")):
        if path.name == "index.html":
            continue
        client_name = path.stem
        try:
            data = json.loads(path.read_text())
            if isinstance(data, list):
                out[client_name] = data
            else:
                out[client_name] = []
        except Exception:
            out[client_name] = []
    return out


# ---------------------------------------------------------------------------
# HTML helpers
# ---------------------------------------------------------------------------

def _esc(s: object) -> str:
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _fmt_size(n: int) -> str:
    for unit, thresh in [("GB", 1024**3), ("MB", 1024**2), ("KB", 1024)]:
        if n >= thresh:
            return f"{n / thresh:.0f} {unit}"
    return f"{n} B"


def _param_summary(params: dict) -> str:
    parts = [_fmt_size(params.get("model_size_bytes", 0))]
    if params.get("method"):
        parts.append(params["method"])
    fc = params.get("file_count", 1)
    if fc != 1:
        parts.append(f"{fc} files")
    for key in ("hash_algorithm", "serialization", "chunk_size", "max_workers", "shard_size"):
        val = params.get(key)
        if val is not None:
            parts.append(f"{key}={val}")
    return ", ".join(parts)


# ---------------------------------------------------------------------------
# Report sections
# ---------------------------------------------------------------------------

def _render_group_table(rows: list[dict]) -> str:
    """Render a <table> for a list of result rows within a group."""
    rows_html = ""
    for r in rows:
        params = r.get("parameters", {})
        res = r.get("results", {})
        rows_html += (
            f"<tr>"
            f"<td>{_esc(r.get('scenario', ''))}</td>"
            f"<td>{_esc(_param_summary(params))}</td>"
            f"<td class='num'>{res.get('mean_ms', ''):.1f}</td>"
            f"<td class='num'>{res.get('min_ms', ''):.1f}</td>"
            f"<td class='num'>{res.get('stddev_ms', ''):.1f}</td>"
            f"<td class='num'>{res.get('throughput_mbps', ''):.1f}</td>"
            f"</tr>\n"
        )
    return f"""<table>
  <thead>
    <tr>
      <th>Scenario</th><th>Parameters</th>
      <th>Mean ms</th><th>Min ms</th><th>Stddev ms</th><th>MB/s</th>
    </tr>
  </thead>
  <tbody>
{rows_html}  </tbody>
</table>"""


def _render_client_table(client: str, results: list[dict]) -> str:
    if not results:
        return f"<p><em>No benchmark results uploaded for <strong>{_esc(client)}</strong>.</em></p>"

    sys_info = results[0].get("system", {}) if results else {}
    client_ver = results[0].get("client_version", "") if results else ""
    sys_parts = [
        f"Platform: {_esc(sys_info.get('platform', 'unknown'))}",
        f"CPUs: {_esc(sys_info.get('cpu_count', '?'))}",
        f"RAM: {_esc(sys_info.get('ram_gb', '?'))} GB",
        f"CPU: {_esc(sys_info.get('cpu_model', 'unknown'))}",
    ]
    if client_ver:
        sys_parts.insert(0, f"Version: <code>{_esc(client_ver)}</code>")
    sys_line = " &bull; ".join(sys_parts)

    groups: dict[str, list[dict]] = {}
    for r in results:
        op = r.get("operation", "other")
        groups.setdefault(op, []).append(r)

    op_order = ["hash", "sign", "verify"]
    sorted_ops = [op for op in op_order if op in groups]
    sorted_ops += [op for op in sorted(groups) if op not in op_order]

    sections = ""
    for op in sorted_ops:
        label = {"hash": "Hash", "sign": "Sign", "verify": "Verify"}.get(op, _esc(op))
        count = len(groups[op])
        sections += (
            f'<details open><summary><strong>{label}</strong> ({count} result{"s" if count != 1 else ""})</summary>\n'
            f'{_render_group_table(groups[op])}\n'
            f'</details>\n'
        )

    return f"""
<h2>{_esc(client)}</h2>
<p class="sys-info">{sys_line}</p>
{sections}
"""


def _render_comparison(all_results: dict[str, list[dict]]) -> str:
    """Side-by-side throughput comparison for scenarios present in >1 client."""
    # Index: (scenario, operation, model_size_bytes, method) → {client: mbps}
    index: dict[tuple, dict[str, float]] = {}
    for client, results in all_results.items():
        for r in results:
            p = r.get("parameters", {})
            key = (
                r.get("scenario", ""),
                r.get("operation", ""),
                p.get("model_size_bytes", 0),
                p.get("method", ""),
            )
            index.setdefault(key, {})[client] = r.get("results", {}).get("throughput_mbps", 0.0)

    clients = sorted(all_results.keys())
    shared = {k: v for k, v in index.items() if len(v) > 1}
    if not shared:
        return "<p><em>No scenarios present in more than one client yet — comparison will appear here once multiple clients upload results.</em></p>"

    header_cells = "".join(f"<th>{_esc(c)}<br>MB/s</th>" for c in clients)
    rows_html = ""
    for (scenario, op, size, method), client_mbps in sorted(shared.items()):
        cells = "".join(
            f"<td class='num'>{client_mbps.get(c, '—'):.1f}</td>" if isinstance(client_mbps.get(c), float)
            else "<td class='num'>—</td>"
            for c in clients
        )
        rows_html += (
            f"<tr>"
            f"<td>{_esc(scenario)}</td><td>{_esc(op)}</td>"
            f"<td>{_esc(_fmt_size(size))}</td><td>{_esc(method)}</td>"
            f"{cells}"
            f"</tr>\n"
        )

    return f"""
<h2>Cross-client Throughput Comparison</h2>
<table>
  <thead>
    <tr>
      <th>Scenario</th><th>Op</th><th>Size</th><th>Method</th>
      {header_cells}
    </tr>
  </thead>
  <tbody>
{rows_html}  </tbody>
</table>
"""


# ---------------------------------------------------------------------------
# Full page
# ---------------------------------------------------------------------------

def render_page(all_results: dict[str, list[dict]], generated_at: str) -> str:
    client_sections = "\n".join(
        _render_client_table(client, results)
        for client, results in sorted(all_results.items())
    )
    comparison = _render_comparison(all_results)
    total_runs = sum(len(v) for v in all_results.values())

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>OMS Benchmark Report</title>
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
            max-width: 1100px; margin: 0 auto; padding: 0 1rem 2rem; color: #1a1a1a; }}
    nav {{ background: #1a1a2e; padding: .6rem 1rem; margin: 0 -1rem 1.5rem;
           display: flex; gap: 1.5rem; align-items: center; }}
    nav a {{ color: #ccd6f6; text-decoration: none; font-size: .9rem; font-weight: 500; }}
    nav a:hover {{ color: #fff; }}
    nav a.active {{ color: #fff; border-bottom: 2px solid #7eb3ff; padding-bottom: 1px; }}
    h1   {{ border-bottom: 2px solid #0057b7; padding-bottom: .4rem; color: #1a1a2e; }}
    h2   {{ margin-top: 2rem; color: #0057b7; }}
    table {{ border-collapse: collapse; width: 100%; margin-top: .5rem; font-size: .9rem; }}
    th, td {{ border: 1px solid #ccc; padding: .35rem .6rem; text-align: left; }}
    th   {{ background: #1a1a2e; color: #fff; }}
    tr:nth-child(even) {{ background: #fafafa; }}
    tr:hover td {{ filter: brightness(0.97); }}
    a {{ color: #0066cc; text-decoration: none; }}
    a:hover {{ text-decoration: underline; }}
    nav a {{ color: #ccd6f6; }}
    nav a:hover {{ color: #fff; }}
    .num {{ text-align: right; font-variant-numeric: tabular-nums; }}
    .sys-info {{ font-size: .8rem; color: #555; margin: .2rem 0 .4rem; }}
    .meta {{ font-size: .8rem; color: #777; margin-top: 2rem; }}
  </style>
</head>
<body>
  <nav>
    <a href="../">Conformance</a>
    <a class="active" href="./">Benchmarks</a>
  </nav>
  <h1>OpenSSF Model Signing — Benchmark Report</h1>
  <p>
    Aggregated performance results across all OMS language clients.
    {total_runs} benchmark run(s) across {len(all_results)} client(s).
  </p>

  {comparison}

  {client_sections}

  <p class="meta">Generated: {_esc(generated_at)}</p>
</body>
</html>
"""


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Generate HTML benchmark report from per-client JSON result files."
    )
    parser.add_argument("--results-dir", required=True, metavar="DIR",
                        help="Directory containing <client>.json result arrays")
    parser.add_argument("--output", required=True, metavar="FILE",
                        help="Output HTML file path")
    args = parser.parse_args(argv)

    results_dir = Path(args.results_dir)
    all_results = load_results(results_dir)

    if not any(all_results.values()):
        print("WARNING: no benchmark results found — generating empty report", file=sys.stderr)

    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    html = render_page(all_results, generated_at)
    Path(args.output).write_text(html)
    print(f"Wrote benchmark report to {args.output}  ({len(all_results)} client(s))")
    return 0


if __name__ == "__main__":
    sys.exit(main())
