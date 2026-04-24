# OMS Conformance Suite

Conformance tests for [OpenSSF Model Signing (OMS)](https://github.com/ossf/model-signing-spec) language clients.

**67 tests** — 28 roundtrip (sign-then-verify) + 39 verify (pre-committed bundles).
Every client runs the same tests. See [`TEST_CASES.md`](TEST_CASES.md) for the full test index and spec coverage matrix.

---

## Integration

### 1. Write a conformance adapter

Your adapter implements two subcommands — exit 0 on success, non-zero on failure:

```
<adapter> sign-model \
  --method key|certificate|sigstore \
  --model-path <dir> --output-bundle <file> \
  [--private-key <pem>] [--signing-cert <pem>] \
  [--cert-chain <pem>...] [--ignore-paths <abs-path>...]

<adapter> verify-model \
  --method key|certificate|sigstore \
  --model-path <dir> --bundle <file> \
  [--public-key <pem>] [--cert-chain <pem>...] \
  [--ignore-paths <abs-path>...] [--ignore-unsigned-files]
```

Reference adapters: [`selftest-client`](selftest-client) (Python), [`test/conformance/main.go`](https://github.com/sampras343/model-transparency-go/blob/main/test/conformance/main.go) (Go).

### 2. Add a workflow

```yaml
jobs:
  conformance:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: <build your adapter>
      - uses: sampras343/model-signing-conformance@v1
        with:
          entrypoint: path/to/your-adapter
          xfail: |
            test_roundtrip[certificate-simple]
      - uses: actions/upload-artifact@v4
        if: always()
        with:
          name: conformance-report
          path: conformance-report.json
```

---

## Running Locally

```bash
pip install -r requirements.txt
pytest test/ --entrypoint=./selftest-client -v

# Verify-only (skip signing tests)
pytest test/ --entrypoint=./selftest-client --skip-signing -v
```

---

## Adding Test Cases

1. Create a directory under `test/test-cases/roundtrip/` or `test/test-cases/verify/<category>/`
2. Add a `config.json` (see [`TEST_CASES.md`](TEST_CASES.md) for the schema and examples)
3. For verify tests, include a pre-committed `bundle.sig`
4. For expected failures, set `"expect": "fail"` in config
