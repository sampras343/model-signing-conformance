"""Pytest configuration and shared fixtures for model-signing conformance tests."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from .client import ModelSigningClient

ASSETS = Path(__file__).parent / "assets"
TEST_CASES = Path(__file__).parent / "test-cases"


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--entrypoint",
        required=True,
        help="Path to the conformance adapter binary/script",
    )
    parser.addoption(
        "--skip-signing",
        action="store_true",
        default=False,
        help="Skip sign+verify roundtrip tests (verify-only tests still run)",
    )
    parser.addoption(
        "--xfail",
        default="",
        help="Newline- or comma-separated list of test IDs to mark as xfail",
    )


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers", "signing: test requires signing capability"
    )


def pytest_runtest_setup(item: pytest.Item) -> None:
    """Skip signing tests when --skip-signing is passed."""
    if item.get_closest_marker("signing"):
        if item.config.getoption("--skip-signing"):
            pytest.skip("Skipping sign+verify test (--skip-signing)")

    xfail_list_raw = item.config.getoption("--xfail")
    if xfail_list_raw:
        separators = "\n,"
        xfail_ids = [
            x.strip()
            for sep in separators
            for x in xfail_list_raw.split(sep)
            if x.strip()
        ]
        for xfail_id in xfail_ids:
            if xfail_id in item.nodeid or item.name.startswith(xfail_id):
                item.add_marker(
                    pytest.mark.xfail(reason=f"Known xfail: {xfail_id}", strict=False)
                )
                break


@pytest.fixture
def client(request: pytest.FixtureRequest) -> ModelSigningClient:
    return ModelSigningClient(
        entrypoint=request.config.getoption("--entrypoint"),
    )


def _load_test_id(case_dir: Path, category: str | None = None) -> str:
    """Build a pytest ID from the config description, falling back to dir name."""
    config_path = case_dir / "config.json"
    base = f"{category}/{case_dir.name}" if category else case_dir.name
    if config_path.exists():
        try:
            data = json.loads(config_path.read_text())
            desc = data.get("description", "")
            if desc:
                return f"{base} | {desc}"
        except (json.JSONDecodeError, KeyError):
            pass
    return base


def pytest_generate_tests(metafunc: pytest.Metafunc) -> None:
    """Parametrize verify_dir and roundtrip_dir from test-cases/ listings."""
    if "verify_dir" in metafunc.fixturenames:
        verify_root = TEST_CASES / "verify"
        categories = ["positive", "negative", "historical"]
        dirs = []
        ids = []
        for category in categories:
            category_dir = verify_root / category
            if category_dir.exists():
                for d in sorted(category_dir.iterdir()):
                    if d.is_dir():
                        dirs.append(d)
                        ids.append(_load_test_id(d, category))
        metafunc.parametrize("verify_dir", dirs, ids=ids)

    if "roundtrip_dir" in metafunc.fixturenames:
        roundtrip_root = TEST_CASES / "roundtrip"
        dirs = sorted(d for d in roundtrip_root.iterdir() if d.is_dir())
        ids = [_load_test_id(d) for d in dirs]
        metafunc.parametrize("roundtrip_dir", dirs, ids=ids)
