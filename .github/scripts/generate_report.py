#!/usr/bin/env python3
"""generate_report.py — Generate HTML conformance report from per-client JSON results.

Usage:
    python generate_report.py --reports-dir ./results --output results/index.html
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path


def load_report(path: Path) -> dict:
    try:
        return json.loads(path.read_text())
    except Exception:
        return {}


def compute_pass_rate(summary: dict) -> str:
    total = summary.get("total", 0)
    passed = summary.get("passed", 0)
    if total == 0:
        return "N/A"
    return f"{passed / total * 100:.0f}%"


def row_class(summary: dict) -> str:
    if not summary:
        return "missing"
    if summary.get("failed", 0) > 0:
        return "fail"
    return "pass"


def generate_html(reports: dict[str, dict], output: Path) -> None:
    now = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    rows = []
    for client_name in sorted(reports):
        report = reports[client_name]
        summary = report.get("summary", {})
        client_url = report.get("client_url", "#")
        sha = report.get("client_sha", "")[:7]
        sha_url = report.get("client_sha_url", "#")
        workflow_url = report.get("workflow_run", "#")

        passed = summary.get("passed", "—")
        failed = summary.get("failed", "—")
        skipped = summary.get("skipped", "—")
        xfailed = summary.get("xfailed", "—")
        pass_rate = compute_pass_rate(summary) if summary else "—"
        css_class = row_class(summary)

        client_link = f'<a href="{client_url}">{client_name}</a>'
        if sha:
            client_link += f' <small>(<a href="{sha_url}">{sha}</a>)</small>'
        if workflow_url != "#":
            client_link += f' <small>[<a href="{workflow_url}">run</a>]</small>'

        rows.append(
            f'<tr class="{css_class}">'
            f"<td>{client_link}</td>"
            f"<td>{pass_rate}</td>"
            f"<td>{passed}</td>"
            f"<td>{failed}</td>"
            f"<td>{skipped}</td>"
            f"<td>{xfailed}</td>"
            f"</tr>"
        )

    table_rows = "\n        ".join(rows)

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>model-signing Conformance Report</title>
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
            max-width: 900px; margin: 0 auto; padding: 0 1rem 2rem; color: #333; }}
    nav {{ background: #1a1a2e; padding: .6rem 1rem; margin: 0 -1rem 1.5rem;
           display: flex; gap: 1.5rem; align-items: center; }}
    nav a {{ color: #ccd6f6; text-decoration: none; font-size: .9rem; font-weight: 500; }}
    nav a:hover {{ color: #fff; }}
    nav a.active {{ color: #fff; border-bottom: 2px solid #7eb3ff; padding-bottom: 1px; }}
    h1 {{ color: #1a1a2e; }}
    .subtitle {{ color: #666; margin-top: -0.5rem; }}
    table {{ border-collapse: collapse; width: 100%; margin-top: 1.5rem; }}
    th {{ background: #1a1a2e; color: white; padding: 0.75rem 1rem; text-align: left; }}
    td {{ padding: 0.6rem 1rem; border-bottom: 1px solid #ddd; }}
    tr.pass td {{ background: #f0fff4; }}
    tr.fail td {{ background: #fff0f0; }}
    tr.missing td {{ background: #f5f5f5; color: #999; }}
    tr:hover td {{ filter: brightness(0.97); }}
    a {{ color: #0066cc; text-decoration: none; }}
    a:hover {{ text-decoration: underline; }}
    nav a {{ color: #ccd6f6; }}
    nav a:hover {{ color: #fff; }}
    .footer {{ margin-top: 2rem; font-size: 0.85rem; color: #999; text-align: center; }}
    small {{ font-size: 0.8em; color: #777; }}
  </style>
</head>
<body>
  <nav>
    <a class="active" href="./">Conformance</a>
    <a href="./benchmarks/">Benchmarks</a>
  </nav>
  <h1>model-signing Conformance Report</h1>
  <p class="subtitle">
    Conformance test results for OpenSSF Model Signing (OMS) language clients.
    See <a href="https://github.com/sampras343/model-signing-conformance">model-signing-conformance</a>
    for the test suite and protocol specification.
  </p>

  <table>
    <thead>
      <tr>
        <th>Client</th>
        <th>Pass Rate</th>
        <th>Passed</th>
        <th>Failed</th>
        <th>Skipped</th>
        <th>Xfailed</th>
      </tr>
    </thead>
    <tbody>
        {table_rows}
    </tbody>
  </table>

  <div class="footer">Last updated: {now}</div>
</body>
</html>
"""
    output.write_text(html)
    print(f"Report written to {output}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate HTML conformance report")
    parser.add_argument("--reports-dir", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    reports_dir = args.reports_dir
    if not reports_dir.is_dir():
        print(f"ERROR: --reports-dir {reports_dir} is not a directory", file=sys.stderr)
        return 1

    reports: dict[str, dict] = {}
    for json_file in sorted(reports_dir.glob("*.json")):
        if json_file.name == "conformance-report.json":
            continue
        client_name = json_file.stem
        reports[client_name] = load_report(json_file)

    if not reports:
        print("WARNING: No client report files found", file=sys.stderr)

    generate_html(reports, args.output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
