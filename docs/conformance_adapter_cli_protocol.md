# Conformance Adapter — CLI Protocol

This document defines the CLI contract that every OMS conformance adapter
must implement. It is designed to be **machine-readable context**: given
this document and a language client's API reference, an AI model should
be able to generate a working adapter.

---

## Overview

The adapter is a **thin CLI wrapper** around your signing library.
It does three things:

1. Parse the flags defined below.
2. Translate them into your library's native API calls.
3. Exit 0 on success, non-zero on failure.

The conformance test harness invokes the adapter as a subprocess.
No stdin interaction — all input is via flags. No stdout parsing for
conformance tests — only the exit code matters.

---

## Required subcommands

### `sign-model`

```
${ENTRYPOINT} sign-model [FLAGS]
```

| Flag | Type | Required | Repeatable | Description |
|---|---|---|---|---|
| `--method` | string | yes | no | One of: `key`, `certificate`, `sigstore` |
| `--model-path` | path | yes | no | Absolute path to the model directory or single file |
| `--output-bundle` | path | yes | no | Absolute path where the signed `.sig` bundle must be written |
| `--private-key` | path | when method=key or certificate | no | PEM-encoded EC private key |
| `--signing-cert` | path | when method=certificate | no | PEM-encoded leaf signing certificate |
| `--cert-chain` | path | when method=certificate | **yes** | PEM-encoded certificate (intermediate or root). Pass once per cert file. Order: leaf-to-root |
| `--ignore-paths` | path | no | **yes** | Absolute path to exclude from signing. Pass once per path |

**Exit code:** `0` = bundle written successfully. Non-zero = signing failed.

**Adapter logic (pseudocode):**

```
function sign_model(args):
    if args.method == "key":
        result = client.sign(
            model_path = args.model_path,
            private_key = load_pem(args.private_key),
            ignore_paths = args.ignore_paths or [],
        )

    elif args.method == "certificate":
        result = client.sign(
            model_path = args.model_path,
            private_key = load_pem(args.private_key),
            signing_cert = load_pem(args.signing_cert),
            cert_chain = [load_pem(c) for c in args.cert_chain],
            ignore_paths = args.ignore_paths or [],
        )

    write_file(args.output_bundle, result.bundle_bytes)
    exit(0)
```

---

### `verify-model`

```
${ENTRYPOINT} verify-model [FLAGS]
```

| Flag | Type | Required | Repeatable | Description |
|---|---|---|---|---|
| `--method` | string | yes | no | One of: `key`, `certificate`, `sigstore` |
| `--model-path` | path | yes | no | Absolute path to the model directory or single file |
| `--bundle` | path | yes | no | Absolute path to the `.sig` bundle to verify |
| `--public-key` | path | when method=key | no | PEM-encoded EC public key |
| `--cert-chain` | path | when method=certificate | **yes** | PEM-encoded trust anchor certificate(s). Pass once per cert file |
| `--ignore-paths` | path | no | **yes** | Absolute path to exclude from verification. Pass once per path |
| `--ignore-unsigned-files` | flag | no | no | Boolean flag (no value). When present, tolerate files on disk not covered by the bundle |

**Exit code:** `0` = verification succeeded. Non-zero = verification failed.

**Adapter logic (pseudocode):**

```
function verify_model(args):
    bundle = read_file(args.bundle)

    if args.method == "key":
        ok = client.verify(
            model_path = args.model_path,
            bundle = bundle,
            public_key = load_pem(args.public_key),
            ignore_paths = args.ignore_paths or [],
            ignore_unsigned = args.ignore_unsigned_files,
        )

    elif args.method == "certificate":
        ok = client.verify(
            model_path = args.model_path,
            bundle = bundle,
            trusted_certs = [load_pem(c) for c in args.cert_chain],
            ignore_paths = args.ignore_paths or [],
            ignore_unsigned = args.ignore_unsigned_files,
        )

    exit(0 if ok else 1)
```

---

## Flag parsing rules

1. **All paths are absolute.** The test harness resolves paths before invocation.
2. **Repeatable flags** appear multiple times (not comma-separated):
   `--ignore-paths /a/b --ignore-paths /a/c`
3. **`--ignore-unsigned-files`** is a boolean flag with no value argument.
4. **Unknown flags** should be ignored or cause a non-zero exit (either is acceptable).
5. **Flag order** is not guaranteed — use a proper argument parser.

---

## Method-to-flag mapping

This table shows which flags are relevant for each method:

| Flag | `key` | `certificate` | `sigstore` |
|---|---|---|---|
| `--private-key` | sign | sign | — |
| `--signing-cert` | — | sign | — |
| `--cert-chain` | — | sign + verify | — |
| `--public-key` | verify | — | — |
| `--ignore-paths` | both | both | both |
| `--ignore-unsigned-files` | verify | verify | verify |

---

## How to build an adapter

### Step 1: Identify your client's API

Find the equivalent of these operations in your library:

| Concept | What to look for |
|---|---|
| Sign a model with a private key | Function that takes a model path + key and produces a bundle |
| Sign with a certificate chain | Same, but also accepts a signing cert + intermediates |
| Verify with a public key | Function that takes a model path + bundle + public key |
| Verify with a trust anchor | Same, but accepts root CA cert(s) instead of a public key |
| Ignore paths | Parameter to exclude files/directories from the manifest |
| Ignore unsigned files | Parameter to tolerate extra files not in the manifest |

### Step 2: Map flags to API parameters

Create a mapping from each CLI flag to the corresponding API parameter:

```
# Example mapping for a hypothetical Go client:
--model-path    →  opts.ModelPath
--private-key   →  opts.PrivateKeyPath
--signing-cert  →  opts.SigningCertPath
--cert-chain    →  opts.CertChainPaths (append each)
--public-key    →  opts.PublicKeyPath
--ignore-paths  →  opts.IgnorePaths (append each)
--output-bundle →  write result to this path
--bundle        →  read bundle from this path
--ignore-unsigned-files → opts.IgnoreUnsignedFiles = true
```

### Step 3: Write the adapter

The adapter is a CLI entrypoint (~50–100 lines) that:

1. Parses `sign-model` or `verify-model` as the first argument
2. Parses the remaining flags
3. Calls the appropriate client API function
4. Writes the bundle (sign) or checks the result (verify)
5. Exits with the correct code

### Step 4: Test locally

```bash
pip install -r requirements.txt
pytest test/ --entrypoint=path/to/your-adapter -v
```

---

## Optional: benchmark subcommands

These are **not required** for conformance. Only implement them if you
want performance benchmarking.

### `capabilities`

```
${ENTRYPOINT} capabilities
```

Exit 0. Print JSON to stdout:

```json
{
  "flags": ["--hash-algorithm", "--shard-size"],
  "hash_algorithms": ["sha256", "blake2b"],
  "benchmark_model": true,
  "client_version": "1.2.0"
}
```

| Field | Type | Description |
|---|---|---|
| `flags` | `string[]` | Optional flags the adapter accepts beyond the required set |
| `hash_algorithms` | `string[]` | Hash algorithms the client supports |
| `benchmark_model` | `boolean` | Whether `benchmark-model` is implemented |
| `client_version` | `string` | Version of the underlying library (optional) |

### `benchmark-model`

```
${ENTRYPOINT} benchmark-model --operation sign|verify --method METHOD --model-path DIR --repeat N [FLAGS]
```

All flags from `sign-model`/`verify-model` apply, plus:

| Flag | Type | Description |
|---|---|---|
| `--operation` | string | `sign` or `verify` |
| `--repeat` | integer | Number of timed iterations |
| `--hash-algorithm` | string | Override hash algorithm (e.g. `sha256`, `blake2b`) |
| `--shard-size` | integer | Shard size in bytes for `file-shard-N` serialization |
| `--chunk-size` | integer | Read chunk size in bytes |
| `--max-workers` | integer | Max parallel hashing workers |

Exit 0. Print JSON to stdout:

```json
{"times_ms": [123.4, 121.8, 119.2]}
```

---

## Reference implementations

| Language | Adapter | Client library |
|---|---|---|
| Python | [`selftest-client`](../selftest-client) | `model_signing` |
| Go | [`test/conformance/main.go`](https://github.com/sampras343/model-transparency-go/blob/main/test/conformance/main.go) | `model-transparency-go` |
