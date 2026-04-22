"""action.py — GitHub Action entrypoint for model-signing conformance.

Reads inputs from environment variables (set by GitHub Actions from action.yml),
runs pytest, enriches the JSON report with client metadata, and optionally
uploads the report as an artifact.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path


def _env(name: str, default: str = "") -> str:
    """Read a GitHub Actions input from environment."""
    # GitHub Actions sets inputs as INPUT_<UPPERCASED_NAME>
    return os.environ.get(f"INPUT_{name.upper().replace('-', '_')}", default)


def _install_deps() -> None:
    """Install conformance suite dependencies from requirements.txt."""
    import subprocess
    req_file = Path(__file__).parent / "requirements.txt"
    if not req_file.exists():
        return
    print("Installing conformance suite dependencies...", flush=True)
    subprocess.check_call(
        [sys.executable, "-m", "pip", "install", "-q", "-r", str(req_file)],
    )


def main() -> int:
    entrypoint = _env("entrypoint")
    if not entrypoint:
        print("::error::Input 'entrypoint' is required", flush=True)
        return 1

    _install_deps()

    skip_signing = _env("skip-signing", "false").lower() == "true"
    xfail = _env("xfail", "")
    skip_upload = _env("skip-result-upload", "false").lower() == "true"

    # Build pytest args
    report_path = Path("conformance-report.json")
    action_dir = Path(__file__).parent

    pytest_args = [
        str(action_dir / "test"),
        f"--entrypoint={entrypoint}",
        "--json-report",
        f"--json-report-file={report_path}",
        "--json-report-indent=2",
        "-v",
        "--tb=short",
    ]

    if skip_signing:
        pytest_args.append("--skip-signing")

    if xfail.strip():
        pytest_args.append(f"--xfail={xfail}")

    # Run pytest
    import pytest
    print(f"Running: pytest {' '.join(pytest_args)}", flush=True)
    exit_code = pytest.main(pytest_args)

    # Enrich the JSON report with GitHub metadata
    if report_path.exists():
        report = json.loads(report_path.read_text())
        report["client_name"] = os.environ.get("GITHUB_REPOSITORY", "unknown").split("/")[-1]
        report["client_url"] = f"https://github.com/{os.environ.get('GITHUB_REPOSITORY', '')}"
        report["client_sha"] = os.environ.get("GITHUB_SHA", "")
        report["client_sha_url"] = (
            f"https://github.com/{os.environ.get('GITHUB_REPOSITORY', '')}"
            f"/commit/{os.environ.get('GITHUB_SHA', '')}"
        )
        report["workflow_run"] = (
            f"https://github.com/{os.environ.get('GITHUB_REPOSITORY', '')}"
            f"/actions/runs/{os.environ.get('GITHUB_RUN_ID', '')}"
        )
        report_path.write_text(json.dumps(report, indent=2))

        # Print GitHub step summary
        summary = report.get("summary", {})
        passed = summary.get("passed", 0)
        failed = summary.get("failed", 0)
        skipped = summary.get("skipped", 0)
        xfailed = summary.get("xfailed", 0)
        total = summary.get("total", 0)

        pass_rate = f"{passed / total * 100:.0f}%" if total > 0 else "N/A"

        step_summary = os.environ.get("GITHUB_STEP_SUMMARY", "")
        if step_summary:
            with open(step_summary, "a") as f:
                f.write("## model-signing Conformance Results\n\n")
                f.write(f"| Pass Rate | Passed | Failed | Skipped | Xfailed |\n")
                f.write(f"|-----------|--------|--------|---------|----------|\n")
                f.write(f"| {pass_rate} | {passed} | {failed} | {skipped} | {xfailed} |\n\n")
                if failed > 0:
                    f.write("### Failed Tests\n\n")
                    for test in report.get("tests", []):
                        if test.get("outcome") == "failed":
                            f.write(f"- `{test['nodeid']}`\n")
        else:
            print(f"\n=== Conformance Results ===")
            print(f"Pass Rate: {pass_rate}  |  Passed: {passed}  |  Failed: {failed}  |  Skipped: {skipped}  |  Xfailed: {xfailed}")

    return exit_code


if __name__ == "__main__":
    sys.exit(main())
