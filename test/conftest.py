"""Pytest configuration and shared fixtures for model-signing conformance tests."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from .client import ModelSigningClient

ASSETS = Path(__file__).parent / "assets"


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

    # Apply xfail from --xfail option
    xfail_list_raw = item.config.getoption("--xfail")
    if xfail_list_raw:
        separators = "\n,"
        xfail_ids = [
            x.strip()
            for sep in separators
            for x in xfail_list_raw.split(sep)
            if x.strip()
        ]
        # Match against the test's node id or parametrize id
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


def pytest_generate_tests(metafunc: pytest.Metafunc) -> None:
    """Parametrize verify_dir and roundtrip_dir from asset directory listings."""
    if "verify_dir" in metafunc.fixturenames:
        verify_root = ASSETS / "verify"
        dirs = sorted(d for d in verify_root.iterdir() if d.is_dir())
        metafunc.parametrize("verify_dir", dirs, ids=[d.name for d in dirs])

    if "roundtrip_dir" in metafunc.fixturenames:
        roundtrip_root = ASSETS / "roundtrip"
        dirs = sorted(d for d in roundtrip_root.iterdir() if d.is_dir())
        metafunc.parametrize("roundtrip_dir", dirs, ids=[d.name for d in dirs])
