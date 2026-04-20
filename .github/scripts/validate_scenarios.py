#!/usr/bin/env python3
"""Validate all benchmark scenario YAML files against the scenario schema.

Performs two levels of validation:
  1. JSON Schema validation (structure, types, enums, required fields)
  2. Semantic validation (cross-field rules the schema can't express)

Exit code 0 = all scenarios valid, 1 = at least one failure.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import jsonschema
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SCENARIOS_DIR = REPO_ROOT / "benchmarks" / "scenarios"
SCHEMA_PATH = REPO_ROOT / "benchmarks" / "schema" / "scenario.schema.json"


def _load_schema() -> dict:
    with SCHEMA_PATH.open() as fh:
        return json.load(fh)


def _validate_schema(scenario: dict, schema: dict, path: Path) -> list[str]:
    """Run JSON Schema validation, return list of error messages."""
    errors = []
    validator = jsonschema.Draft202012Validator(schema)
    for err in sorted(validator.iter_errors(scenario), key=lambda e: list(e.path)):
        location = ".".join(str(p) for p in err.absolute_path) or "(root)"
        errors.append(f"  {location}: {err.message}")
    return errors


def _validate_semantics(scenario: dict, path: Path) -> list[str]:
    """Cross-field rules that JSON Schema conditionals can't fully express."""
    errors = []
    sweep = scenario.get("sweep", {})
    has_model_shape_sweep = "model_shape" in sweep
    has_top_model_shape = "model_shape" in scenario

    if has_model_shape_sweep and has_top_model_shape:
        errors.append(
            "  model_shape defined both at top level and inside sweep — use one or the other"
        )

    if not has_model_shape_sweep and not has_top_model_shape:
        non_shape_keys = [k for k in sweep if k != "model_shape"]
        if non_shape_keys:
            errors.append(
                "  parameter sweep has no top-level model_shape — "
                "required when sweep doesn't contain model_shape"
            )

    if has_model_shape_sweep:
        shapes = sweep["model_shape"]
        if not isinstance(shapes, list) or not shapes:
            errors.append("  sweep.model_shape must be a non-empty list of {size, files} objects")
        else:
            for i, shape in enumerate(shapes):
                if not isinstance(shape, dict) or "size" not in shape:
                    errors.append(f"  sweep.model_shape[{i}]: must be an object with 'size' key")

    name = scenario.get("name", "")
    fname = path.stem
    dir_prefixed = f"{path.parent.name}_{fname}"
    if name and name != fname and name != dir_prefixed and not fname.startswith(name):
        errors.append(
            f"  name '{name}' doesn't match filename '{fname}.yaml' or "
            f"'{dir_prefixed}' — consider aligning them for discoverability"
        )

    return errors


def main() -> int:
    schema = _load_schema()
    scenario_files = sorted(SCENARIOS_DIR.rglob("*.yaml"))

    if not scenario_files:
        print(f"ERROR: No scenario files found in {SCENARIOS_DIR}")
        return 1

    total = 0
    failed = 0

    for path in scenario_files:
        total += 1
        rel = path.relative_to(REPO_ROOT)

        with path.open() as fh:
            try:
                scenario = yaml.safe_load(fh)
            except yaml.YAMLError as exc:
                print(f"FAIL {rel}")
                print(f"  YAML parse error: {exc}")
                failed += 1
                continue

        if not isinstance(scenario, dict):
            print(f"FAIL {rel}")
            print("  File does not contain a YAML mapping")
            failed += 1
            continue

        errors = _validate_schema(scenario, schema, path)
        errors += _validate_semantics(scenario, path)

        if errors:
            print(f"FAIL {rel}")
            for e in errors:
                print(e)
            failed += 1
        else:
            print(f"OK   {rel}")

    print(f"\n{total} scenarios checked, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
