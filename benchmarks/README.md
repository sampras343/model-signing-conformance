# Benchmarks

Performance benchmarks for OMS signing clients. Measures throughput, not correctness — see `test/` for conformance.

Any adapter that passes the conformance suite can be benchmarked immediately (Phases 1–3 require no additional subcommands).

## Running

```bash
pip install pyyaml

# Single scenario
python -m benchmarks.harness.run \
  --entrypoint ./your-adapter \
  --scenario benchmarks/scenarios/key/sign_throughput.yaml \
  --private-key test/assets/keys/p384/signing-key.pem \
  --public-key  test/assets/keys/p384/signing-key-pub.pem \
  --output results.json

# All scenarios
python -m benchmarks.harness.run \
  --entrypoint ./your-adapter \
  --scenarios benchmarks/scenarios/ \
  --private-key test/assets/keys/p384/signing-key.pem \
  --public-key  test/assets/keys/p384/signing-key-pub.pem \
  --output results.json

# CI mode (capped model sizes)
python -m benchmarks.harness.run \
  --entrypoint ./your-adapter \
  --scenarios benchmarks/scenarios/ \
  --private-key test/assets/keys/p384/signing-key.pem \
  --public-key  test/assets/keys/p384/signing-key-pub.pem \
  --output results.json --ci
```

## Scenarios

Declarative YAML files under `scenarios/` define what to measure:

| Directory | Scenarios |
|---|---|
| `key/` | Sign and verify throughput with EC key |
| `certificate/` | Sign and verify throughput with certificate chain |
| `hash/` | Hash algorithm sweep, shard size sweep, chunk size sweep, worker count sweep |

Schema: `schema/scenario.schema.json`

## Results

Output is structured JSON conforming to `schema/result.schema.json`.

To compare clients, run the harness separately for each adapter and merge:

```bash
python -m benchmarks.harness.run --entrypoint ./python-adapter ... --output py.json
python -m benchmarks.harness.run --entrypoint ./go-adapter    ... --output go.json
```

## Adapter requirements

| Phase | Benchmarked | Additional adapter work |
|---|---|---|
| 1–3 | Sign/verify throughput | None — uses `sign-model` / `verify-model` |
| 4 | Capability negotiation | `capabilities` subcommand |
| 5 | Parameter sweeps | Optional flags: `--hash-algorithm`, `--shard-size`, `--chunk-size`, `--max-workers` |

See [`docs/cli_protocol.md`](../docs/cli_protocol.md) for the full adapter specification.
