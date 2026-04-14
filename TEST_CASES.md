# Conformance Test Cases

Reference document for all 42 test cases in the model-signing conformance suite.

**Suite layout:**
- **22 `verify` tests** — use pre-committed bundles (signed offline, committed to this repo). Every client verifies the same bundles. Passing a verify test proves the client correctly implements the wire format and the verification logic for that scenario.
- **20 `roundtrip` tests** — live sign-then-verify. The client signs a model during the test and immediately verifies it. These prove the signing path is correct and interoperable with the verification path.

**Cross-language interoperability** is implicit: all pre-committed bundles in `verify/` were signed by the Python reference implementation. When a Go (or any other language) client passes these tests, it has verified a Python-signed bundle — no special test name is needed.

---

## Category 1: Verify Tests (`test/assets/verify/`)

These tests call `verify-model` only. The bundle is pre-committed to the repo.

Tests are organized in three subdirectories:
- `positive/` — 6 tests that must succeed (exit 0)
- `negative/` — 9 tests that must fail (exit non-zero)
- `historical/` — 7 backwards compatibility tests

### Positive Cases (`verify/positive/`) — verification must succeed (exit 0)

---

#### `key-simple`

**What it tests:** Baseline key-based verification against a two-file model.

**Setup:** Model has three files (`signme-1`, `signme-2`, `ignore-me`). Bundle was signed with `ignore-me` excluded. Verified with the matching public key.

**Why it exists:** This is the entry-level smoke test. If this fails, the client cannot perform basic key verification at all. It also exercises the `--ignore-paths` flag during verification (the extra `ignore-me` file must not cause failure).

**Expected outcome:** Exit 0. Two files (`signme-1`, `signme-2`) are in the bundle; `ignore-me` is not.

**Impact if it fails:** The entire key-based signing and verification feature is broken. No further debugging of other key tests is useful until this passes.

---

#### `certificate-simple`

**What it tests:** Baseline certificate-based verification against a two-file model.

**Setup:** Bundle was signed with a leaf certificate backed by a 3-level PKI chain (leaf → intermediate CA → root CA). Verified using the root CA certificate as the trust anchor.

**Why it exists:** Mirrors `key-simple` for the certificate signing method. Confirms the client can validate the full certificate chain and match the bundle's signing certificate against the trusted root.

**Expected outcome:** Exit 0.

**Impact if it fails:** The entire certificate-based signing and verification feature is broken. Teams relying on enterprise PKI (common in regulated environments) are blocked.

---

#### `key-multi-file`

**What it tests:** Key verification on a model with files in subdirectories.

**Setup:** Model has `weights.bin`, `config.json`, and `subdir/adapter.bin`. All three are signed. The bundle's `resources` list is verified to contain all three paths with the correct relative names.

**Why it exists:** Many real models are not flat directories — they have nested structure (HuggingFace format, for example). This test ensures path canonicalization works correctly across subdirectories and that the manifest sort order is deterministic regardless of filesystem traversal order.

**Expected outcome:** Exit 0. Exactly `["config.json", "subdir/adapter.bin", "weights.bin"]` in the bundle.

**Impact if it fails:** The client cannot sign or verify models with subdirectories, which covers the majority of real-world model formats.

---

#### `key-ignore-paths`

**What it tests:** That `--ignore-paths` correctly excludes files from the signed manifest.

**Setup:** Model has `signme-1`, `signme-2`, and `ignore-me`. The bundle was created with `ignore-me` excluded. `config.json` asserts `expected_signed_files = ["signme-1", "signme-2"]`.

**Why it exists:** `ignore-me` represents files like metadata, lock files, or auto-generated files that exist in the model directory but must not be part of the integrity guarantee. If `ignore-me` ends up in the bundle, or if its presence breaks verification, the feature is broken.

**Expected outcome:** Exit 0. Bundle contains exactly `signme-1` and `signme-2`.

**Impact if it fails:** Operators cannot exclude non-model files from signing, leading to spurious verification failures whenever tooling creates auxiliary files in the model directory.

---

#### `key-single-file`

**What it tests:** Key verification when the model is a single file (`model.bin`), not a directory.

**Why it exists:** Some model artifacts are single binary files rather than directories. The canonicalization path for a single-file model is different — the resource name is the filename itself, not a relative path. This test ensures that code path is not neglected.

**Expected outcome:** Exit 0. Bundle contains exactly `["model.bin"]`.

**Impact if it fails:** Clients cannot sign or verify single-file models (e.g., ONNX exports, GGUF quantized models).

---

#### `key-simple-ignore-unsigned-files`

**What it tests:** The `--ignore-unsigned-files` flag allows extra unsigned files to pass verification.

**Setup:** The model directory contains `signme-1`, `signme-2`, `ignore-me`, **and** an additional unsigned file (the bundle does not cover all files in the directory). `ignore_unsigned_files: true` is set in the config.

**Why it exists:** In deployment scenarios, operators may add runtime files (logs, configs, caches) to a model directory after signing. Without `--ignore-unsigned-files`, verification would reject the model even though the signed files are intact. This test proves the flag works correctly.

**Expected outcome:** Exit 0, even though the directory contains unsigned files.

**Impact if it fails:** Operators cannot deploy models to directories that may accumulate runtime artifacts; they would be forced to keep the model directory completely frozen post-signing.

---

### Historical Regression Cases (`verify/historical/`) — backwards compatibility

These tests use bundles generated by specific older Go releases. They prove that the current implementation can still read bundles produced by every previous release. Bundles are committed to this repo and never regenerated.

---

#### `historical-v0.2.0-certificate`

**What it tests:** Verifies a certificate-signed bundle produced by Go `v0.2.0`.

**Why it exists:** `v0.2.0` was the first release to use the Sigstore bundle format. Its bundle structure predates several schema changes. The Python reference implementation added a compatibility layer (`payload_compat.go`) to read it. This test ensures both old and new clients can read the oldest supported format.

**Expected outcome:** Exit 0.

**Impact if it fails:** Bundles signed in production with `v0.2.0` can no longer be verified. Customers on long-lived model archives are affected.

---

#### `historical-v0.3.1-elliptic-key`

**What it tests:** Verifies a key-signed (elliptic curve) bundle from Go `v0.3.1`.

**Why it exists:** `v0.3.1` introduced key-based signing. This is the oldest key-signed bundle format. Tests that the elliptic key path was not silently broken by later refactors.

**Expected outcome:** Exit 0.

**Impact if it fails:** Bundles from `v0.3.1` cannot be verified. Any model signed during the `v0.3.x` lifecycle is unverifiable.

---

#### `historical-v0.3.1-certificate`

**What it tests:** Verifies a certificate-signed bundle from Go `v0.3.1`.

**Expected outcome:** Exit 0.

**Impact if it fails:** Certificate-signed bundles from the `v0.3.x` era cannot be verified.

---

#### `historical-v1.0.0-elliptic-key`

**What it tests:** Verifies a key-signed bundle from Go `v1.0.0`, the first stable release.

**Why it exists:** `v1.0.0` was the first semver-stable release. Bundles from this release are likely the most widely deployed. Breaking this is a high-severity regression.

**Expected outcome:** Exit 0.

**Impact if it fails:** All `v1.0.0`-signed model bundles in production are unverifiable. This is the most impactful of the historical regression tests.

---

#### `historical-v1.0.0-certificate`

**What it tests:** Verifies a certificate-signed bundle from Go `v1.0.0`.

**Expected outcome:** Exit 0.

**Impact if it fails:** Same as above — certificate-signed bundles from `v1.0.0` in production are unverifiable.

---

#### `historical-v1.1.0-elliptic-key`

**What it tests:** Verifies a key-signed bundle from Go `v1.1.0`, the most recent historical release captured.

**Why it exists:** `v1.1.0` added `ignore_paths` to the predicate. This test ensures the current code correctly reads a bundle that includes `ignore_paths` in the predicate JSON.

**Expected outcome:** Exit 0.

**Impact if it fails:** Bundles from `v1.1.0` (likely the most common in recent deployments) cannot be verified. Indicates a regression in how `ignore_paths` is deserialized.

---

#### `historical-v1.1.0-certificate`

**What it tests:** Verifies a certificate-signed bundle from Go `v1.1.0` with `ignore_paths`.

**Expected outcome:** Exit 0.

**Impact if it fails:** Same as `historical-v1.1.0-elliptic-key`, for the certificate signing path.

---

### Negative Cases (`verify/negative/`) — verification must fail (exit non-zero)

These test that the client **correctly rejects** invalid or tampered inputs. Passing means the client returns a non-zero exit code; failing means the client returned exit 0 when it should have rejected the input.

---

#### `key-simple-tampered-content_fail`

**What it tests:** Detection of file content modification after signing.

**Setup:** `signme-1` in the model directory has been modified after the bundle was created. The digest in the bundle no longer matches the actual file.

**Why it exists:** This is the primary security property of model signing — tampering must be detected. If this test fails, the client is not checking file digests against the manifest, and the signing feature provides no integrity guarantee whatsoever.

**Expected outcome:** Exit non-zero. Error must indicate digest mismatch.

**Impact if it fails:** **Critical security failure.** The client silently accepts tampered models, completely defeating the purpose of model signing.

---

#### `key-simple-wrong-key_fail`

**What it tests:** Rejection when the verification key does not match the signing key.

**Setup:** The bundle was signed with the standard test key. Verification is attempted using `keys/wrong/wrong-key-pub.pem` (a different, unrelated EC key).

**Why it exists:** Ensures the client validates the DSSE signature cryptographically — not just that a signature exists, but that it was produced by the claimed key. Prevents accepting bundles signed by an untrusted party.

**Expected outcome:** Exit non-zero. Error must indicate signature verification failure.

**Impact if it fails:** **Critical security failure.** The client accepts bundles signed by arbitrary keys, making model provenance unenforceable.

---

#### `key-simple-missing-file_fail`

**What it tests:** Detection of a missing file that was included in the bundle.

**Setup:** `signme-2` was included in the bundle during signing but has been **deleted** from the model directory before verification.

**Why it exists:** An attacker could remove a file from a signed model (e.g., a safety filter, a configuration file) without modifying other files. The verifier must detect the absence of files that were part of the original signed manifest.

**Expected outcome:** Exit non-zero. Error must indicate a file in the bundle is missing from the model directory.

**Impact if it fails:** **Critical security failure.** Attackers can remove components from a signed model without triggering verification failure.

---

#### `key-simple-extra-file_fail`

**What it tests:** Rejection when an unsigned file exists in the model directory (without `--ignore-unsigned-files`).

**Setup:** The model directory contains `injected.bin`, which was not present when the bundle was signed and is not in the manifest.

**Why it exists:** Detects file injection attacks — an attacker who can write to the model directory could add malicious files. By default, unsigned files must be rejected unless the operator explicitly opts in with `--ignore-unsigned-files`.

**Expected outcome:** Exit non-zero. Error must indicate an unsigned file was found.

**Impact if it fails:** **Security failure.** Attackers can inject arbitrary files into signed model directories and have them accepted as part of the verified model.

---

#### `certificate-simple-wrong-ca_fail`

**What it tests:** Rejection when the CA certificate used for verification is not the signing CA.

**Setup:** The bundle was signed with a leaf certificate rooted at the standard test CA. Verification is attempted using `keys/wrong/wrong-ca-cert.pem` (a completely different CA).

**Why it exists:** Ensures the PKI chain validation is enforced. The signer's certificate must chain up to a trusted root provided by the verifier. This is the foundational property of certificate-based signing — the verifier controls which CAs are trusted.

**Expected outcome:** Exit non-zero. Error must indicate certificate chain validation failure.

**Impact if it fails:** **Critical security failure.** Any certificate-signed bundle is accepted regardless of which CA issued the signing certificate, making the trust anchor meaningless.

---

#### `key-simple-corrupted-bundle_fail`

**What it tests:** Rejection of a bundle file that contains invalid JSON.

**Setup:** `bundle.sig` contains literal garbage (`{"not": "valid json}`) — the file is not parseable.

**Why it exists:** The client must gracefully handle malformed input rather than crash, panic, or silently succeed. This also guards against accidentally passing an empty or truncated file.

**Expected outcome:** Exit non-zero. Error must indicate bundle parsing failure (not a crash).

**Impact if it fails:** Clients may crash or return misleading errors. In pipeline automation, a non-crash but silent success would be a security vulnerability.

---

#### `key-simple-truncated-bundle_fail`

**What it tests:** Rejection of a bundle file that is structurally valid JSON but incomplete (first 100 bytes of a real bundle).

**Setup:** `bundle.sig` is the first 100 bytes of a real bundle, producing a syntactically broken JSON object.

**Why it exists:** Complements `corrupted-bundle_fail` by testing a different failure mode — a partially-written file (e.g., from an interrupted download or disk-full error) rather than complete garbage. Ensures the client validates bundle completeness, not just parse success.

**Expected outcome:** Exit non-zero.

**Impact if it fails:** Clients may accept partially-written bundles, leading to non-deterministic verification results depending on which fields happen to be present in the truncated portion.

---

#### `key-simple-wrong-mediatype_fail`

**What it tests:** Rejection of bundles with an incorrect `mediaType` field.

**Setup:** A valid bundle where the `mediaType` field has been changed from `application/vnd.dev.sigstore.bundle.v0.3+json` to `application/vnd.dev.sigstore.bundle.v0.1+json`. The signature remains valid because `mediaType` is outside the DSSE envelope.

**Why it exists:** The spec (step 2 of verification) requires validating `mediaType`. This field indicates the bundle schema version. Accepting wrong versions could lead to misinterpretation of bundle fields. Since `mediaType` is outside the signed envelope, this must be explicitly checked — signature verification alone won't catch it.

**Expected outcome:** Exit non-zero. Error must indicate invalid or unsupported bundle version.

**Impact if it fails:** Clients may misparse bundles from incompatible versions, leading to subtle verification failures or security issues if field semantics differ between versions.

---

#### `key-simple-no-signature_fail`

**What it tests:** Rejection of bundles with an empty `signatures` array.

**Setup:** A bundle where `dsseEnvelope.signatures` has been set to an empty array `[]`. All other fields remain valid.

**Why it exists:** Section 2.1 of the spec states "`dsseEnvelope.signatures` MUST contain at least one entry." A bundle without any signatures cannot be verified and must be rejected explicitly. This test ensures clients validate signature presence before attempting cryptographic verification.

**Expected outcome:** Exit non-zero. Error must indicate no signatures present or signature verification failure.

**Impact if it fails:** Clients may crash, return misleading errors, or (worst case) incorrectly report successful verification for unsigned content.

---

## Category 2: Roundtrip Tests (`test/assets/roundtrip/`)

These tests call `sign-model` followed immediately by `verify-model` within the same test run. They prove the client's signing and verification paths are consistent with each other. The model is copied to a temporary directory before signing so the original assets are not modified.

---

#### `key-simple`

**What it tests:** Basic key sign-then-verify roundtrip on a simple two-file model.

**Why it exists:** The minimal end-to-end test for key-based signing. Proves the client can produce a bundle and then successfully verify it. If this fails, no further key roundtrip tests will pass.

**Expected outcome:** Sign exits 0. Verify exits 0. Bundle contains `["signme-1", "signme-2"]`.

**Impact if it fails:** Key-based signing is fundamentally broken in this client.

---

#### `certificate-simple`

**What it tests:** Certificate sign-then-verify roundtrip using the full 3-level PKI chain.

**Setup:** Signs with `signing-key.pem` + `signing-key-cert.pem` (leaf), providing `int-ca-cert.pem` + `ca-cert.pem` as the certificate chain. Verifies using `ca-cert.pem` as the trust anchor.

**Why it exists:** End-to-end test for certificate-based signing. Also validates that the intermediate CA certificate is correctly embedded in or referenced by the bundle and recovered during verification.

**Expected outcome:** Sign exits 0. Verify exits 0. Bundle contains `["signme-1", "signme-2"]`.

**Impact if it fails:** Certificate-based signing is broken. PKI-based model provenance is unavailable.

---

#### `key-multi-file`

**What it tests:** Key roundtrip on a model with subdirectories.

**Setup:** Uses `models/multi-file` (`weights.bin`, `config.json`, `subdir/adapter.bin`).

**Why it exists:** Validates that the signing path correctly traverses subdirectories, produces relative paths as resource names, and sorts them deterministically. The verifier must then match the same traversal.

**Expected outcome:** Sign exits 0. Verify exits 0. Bundle contains `["config.json", "subdir/adapter.bin", "weights.bin"]`.

**Impact if it fails:** Models with subdirectory structure (most real models) cannot be signed or verified.

---

#### `key-ignore-paths`

**What it tests:** Roundtrip with `--ignore-paths` excluding a file during signing.

**Setup:** `models/simple` with `ignore_paths: ["ignore-me"]`. Signs without `ignore-me`; verifies with the same ignore list.

**Why it exists:** The roundtrip path must correctly pass `--ignore-paths` to both the signer and verifier. If ignore paths are passed to sign but not to verify, the verifier will encounter `ignore-me` in the directory and fail with an unsigned-file error.

**Expected outcome:** Sign exits 0. Verify exits 0. `ignore-me` is not in the bundle.

**Impact if it fails:** Operators cannot sign models with auxiliary files (checksums, lock files, etc.) reliably.

---

#### `key-ignore-unsigned`

**What it tests:** Roundtrip where verification uses `--ignore-unsigned-files` to tolerate a file added after signing.

**Setup:** Signs `models/simple` (excluding `ignore-me`). After signing, an additional file is injected into the model copy. Verifies with `--ignore-unsigned-files`.

**Why it exists:** Tests the complete lifecycle of a model in a deployment environment where runtime artifacts accumulate after the model is signed. The verifier must accept the added file because `--ignore-unsigned-files` is set.

**Expected outcome:** Sign exits 0. Verify exits 0 even with the extra file present.

**Impact if it fails:** Models cannot be deployed to live environments that generate auxiliary files post-signing.

---

#### `key-single-file`

**What it tests:** Key roundtrip for a single-file model.

**Setup:** Uses `models/single-file` which contains only `model.bin`.

**Why it exists:** Validates the single-file code path end-to-end. The signing path for a file (vs. a directory) is structurally different in the canonicalization step.

**Expected outcome:** Sign exits 0. Verify exits 0. Bundle contains `["model.bin"]`.

**Impact if it fails:** Single-file model artifacts (ONNX, GGUF, SafeTensors, etc.) cannot be signed.

---

#### `key-nested`

**What it tests:** Key roundtrip on a multi-level directory structure.

**Setup:** Uses `models/multi-file` (same as `key-multi-file`), but tests the nested directory traversal explicitly.

**Why it exists:** A separate test from `key-multi-file` to isolate nested-directory handling. While the model fixture is currently the same, this test can evolve independently to add deeper nesting without affecting the multi-file baseline test.

**Expected outcome:** Sign exits 0. Verify exits 0. Paths in bundle use `/` separator and are relative to model root.

**Impact if it fails:** Deeply nested models fail to sign or verify correctly.

---

#### `certificate-multi-file`

**What it tests:** Certificate roundtrip on a multi-file model with subdirectories.

**Why it exists:** Combines the multi-file and certificate scenarios. Ensures the certificate signing path handles non-flat model structures, not just the key-based path.

**Expected outcome:** Sign exits 0. Verify exits 0. Bundle contains `["config.json", "subdir/adapter.bin", "weights.bin"]`.

**Impact if it fails:** Certificate-signed multi-file models (the most common enterprise scenario) cannot be used.

---

#### `certificate-chain-verification`

**What it tests:** Certificate roundtrip with an explicit full chain (leaf → intermediate → root), verifying that the intermediate CA is correctly handled.

**Setup:** Provides `int-ca-cert.pem` explicitly in `cert_chain` alongside the root CA. This is distinct from `certificate-simple` which also provides the chain but is less explicit about the intermediate CA role.

**Why it exists:** Some PKI implementations have subtle bugs where they only validate the leaf against the root, skipping the intermediate. This test ensures the full chain is traversed: leaf cert → signed by intermediate CA → intermediate CA → signed by root CA → root CA is trusted.

**Expected outcome:** Sign exits 0. Verify exits 0.

**Impact if it fails:** Bundles signed with 3-tier PKI hierarchies (standard in enterprise environments) fail verification. Root CA verification appears to pass but intermediate chain validation is skipped.

---

#### `key-simple-deterministic`

**What it tests:** That signing the same model twice with the same key produces identical manifests (deterministic output).

**Setup:** Signs `models/simple` twice with the same key and settings. Compares the resource list (names + digests) from both bundles.

**Why it exists:** Non-deterministic signing can cause silent failures in version control workflows where users compare bundles across runs, or in reproducible builds. The manifest must always produce the same hash values and the same sorted resource order for identical inputs.

**Expected outcome:** Both signs exit 0. Both verifies exit 0. The `resources` list (names and digests) in both bundles is identical.

**Impact if it fails:** Signing is non-deterministic — different runs produce different bundles for the same model, breaking bundle comparison, reproducible builds, and any workflow that stores bundles in version control.

---

#### `key-empty-file`

**What it tests:** Key roundtrip on a model containing an empty (zero-byte) file.

**Setup:** Uses `models/with-empty-file` containing `signme-1` (8 bytes) and `empty.bin` (0 bytes).

**Why it exists:** Empty files are a valid edge case — some model formats include empty placeholder files. The hashing and manifest generation must handle zero-byte files correctly. SHA-256 of an empty file is `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855`.

**Expected outcome:** Sign exits 0. Verify exits 0. Bundle contains `["empty.bin", "signme-1"]`.

**Impact if it fails:** Models containing empty files (placeholders, markers, etc.) cannot be signed.

---

#### `key-p384`

**What it tests:** Key roundtrip using an EC P-384 key instead of the default P-256.

**Setup:** Uses a P-384 (secp384r1) key pair for signing and verification.

**Why it exists:** The spec states P-384 MUST be supported. This test ensures clients correctly handle larger EC keys and the corresponding signature algorithms (ECDSA with SHA-384).

**Expected outcome:** Sign exits 0. Verify exits 0. Bundle contains `["signme-1", "signme-2"]`.

**Impact if it fails:** Clients are non-compliant with the spec. Users requiring P-384 (common in government/enterprise security policies) cannot use the client.

---

#### `key-p521`

**What it tests:** Key roundtrip using an EC P-521 key.

**Setup:** Uses a P-521 (secp521r1) key pair for signing and verification.

**Why it exists:** The spec states P-521 MUST be supported (Section 8.1). This completes the EC curve coverage alongside P-256 and P-384 tests.

**Expected outcome:** Sign exits 0. Verify exits 0. Bundle contains `["signme-1", "signme-2"]`.

**Impact if it fails:** Clients are non-compliant with the spec. Users requiring P-521 (required by some government security standards) cannot use the client.

---

#### `certificate-self-signed`

**What it tests:** Certificate roundtrip with a self-signed certificate (no intermediate CA).

**Setup:** Uses a self-signed certificate where the same certificate serves as both the signing cert and the trust anchor.

**Why it exists:** Self-signed certificates are common in development, testing, and air-gapped environments. The certificate chain handling must work when the chain has only one certificate.

**Expected outcome:** Sign exits 0. Verify exits 0. Bundle contains `["signme-1", "signme-2"]`.

**Impact if it fails:** Developers cannot use self-signed certificates for testing. Air-gapped environments requiring simple PKI are unsupported.

---

#### `key-unicode-filename`

**What it tests:** Key roundtrip on a model with Unicode characters in filenames.

**Setup:** Uses `models/unicode-names` containing `weights.bin` and `模型.bin` (Chinese characters meaning "model").

**Why it exists:** Model files from international teams may have non-ASCII filenames. The path handling, JSON serialization, and filesystem operations must correctly handle UTF-8 encoded filenames.

**Expected outcome:** Sign exits 0. Verify exits 0. Bundle contains `["weights.bin", "模型.bin"]`.

**Impact if it fails:** Models with non-ASCII filenames (common in i18n contexts) cannot be signed or verified, excluding international users.

---

#### `key-default-ignores`

**What it tests:** That `.git`, `.github`, `.gitignore`, and `.gitattributes` are automatically excluded from signing even WITHOUT explicit `--ignore-paths`.

**Setup:** Uses `models/with-git-dir` which contains `model.bin` plus `.git/HEAD`, `.github/ci.yml`, `.gitignore`, and `.gitattributes`. No `ignore_paths` is specified in the config.

**Why it exists:** Section 5.1 states implementations "MUST exclude by default: `.git`, `.gitignore`, `.gitattributes`, `.github`". This test verifies the default exclusion behavior works without user intervention.

**Expected outcome:** Sign exits 0. Verify exits 0. Bundle contains only `["model.bin"]` — all git-related files are auto-excluded.

**Impact if it fails:** Users must manually specify `--ignore-paths .git .github .gitignore .gitattributes` for every signing operation, which is error-prone and violates the spec's convenience requirement.

---

#### `key-special-chars-path`

**What it tests:** Signing and verification of models with spaces and special characters in file/directory names.

**Setup:** Uses `models/special-chars` containing `file (copy).bin`, `normal.bin`, and `path with spaces/model.bin`.

**Why it exists:** Real-world models often have paths with spaces, parentheses, or other special characters. Path handling, shell escaping, and JSON serialization must all handle these correctly.

**Expected outcome:** Sign exits 0. Verify exits 0. Bundle contains `["file (copy).bin", "normal.bin", "path with spaces/model.bin"]`.

**Impact if it fails:** Models with human-readable filenames (common when files are manually organized) cannot be signed. Users would need to rename files to avoid spaces/special chars.

---

#### `key-dotfile-included`

**What it tests:** That non-git dotfiles (like `.config`, `.env.example`) ARE signed and not mistakenly excluded.

**Setup:** Uses `models/with-dotfiles` containing `.config`, `.env.example`, and `model.bin`.

**Why it exists:** Section 5.1 specifies only `.git`, `.gitignore`, `.gitattributes`, `.github` are excluded by default. Other dotfiles MUST be included. This test ensures the exclusion logic doesn't over-match.

**Expected outcome:** Sign exits 0. Verify exits 0. Bundle contains `[".config", ".env.example", "model.bin"]`.

**Impact if it fails:** Legitimate configuration files starting with `.` are silently excluded from signing, potentially leaving critical model configuration unsigned and vulnerable to tampering.

---

#### `key-binary-content`

**What it tests:** Signing and verification of models containing true binary data (arbitrary byte sequences including null bytes).

**Setup:** Uses `models/binary-content` containing `weights.bin` (1024 bytes with all values 0x00-0xFF) and `header.bin` (binary with null bytes and PNG-like magic bytes).

**Why it exists:** All other model fixtures use ASCII text content. Real ML models contain binary weight data with arbitrary byte values. This test ensures hashing, base64 encoding, and JSON serialization handle non-text data correctly.

**Expected outcome:** Sign exits 0. Verify exits 0. Bundle contains `["header.bin", "weights.bin"]`.

**Impact if it fails:** Real ML models (which are binary) cannot be signed. This would make the entire tool unusable for its primary purpose.

---

#### `key-files-in-hidden-dir`

**What it tests:** That files inside hidden directories (other than `.git`/`.github`) ARE signed and not excluded.

**Setup:** Uses `models/hidden-subdir` containing `model.bin`, `.cache/weights.bin`, and `.local/share/data.bin`.

**Why it exists:** Section 5.1 specifies only `.git`, `.github`, `.gitignore`, `.gitattributes` are excluded by default. Other hidden directories like `.cache/` or `.local/` MUST have their contents signed. This test ensures the exclusion logic is specific to git-related paths, not all dotfiles/dotdirs.

**Expected outcome:** Sign exits 0. Verify exits 0. Bundle contains `[".cache/weights.bin", ".local/share/data.bin", "model.bin"]`.

**Impact if it fails:** Files in hidden directories are silently excluded, leaving cached model data or local configurations unsigned and vulnerable to tampering.

---

## Test Count Summary

| Category | Count |
|---|---|
| Verify — positive | 6 |
| Verify — negative (failure detection) | 9 |
| Verify — historical regression | 7 |
| Roundtrip | 20 |
| **Total** | **42** |

---

## Model Fixtures (`test/assets/models/`)

| Fixture | Files | Used by |
|---|---|---|
| `models/simple` | `signme-1` (9 bytes), `signme-2` (8 bytes), `ignore-me` (excluded) | Most key and certificate tests |
| `models/multi-file` | `weights.bin`, `config.json`, `subdir/adapter.bin` | Multi-file and nested tests |
| `models/single-file` | `model.bin` | Single-file tests |
| `models/with-empty-file` | `signme-1` (8 bytes), `empty.bin` (0 bytes) | Empty file edge case test |
| `models/unicode-names` | `weights.bin`, `模型.bin` | Unicode filename test |
| `models/with-git-dir` | `model.bin`, `.git/HEAD`, `.github/ci.yml`, `.gitignore`, `.gitattributes` | Default ignores test |
| `models/special-chars` | `file (copy).bin`, `normal.bin`, `path with spaces/model.bin` | Special characters path test |
| `models/with-dotfiles` | `.config`, `.env.example`, `model.bin` | Dotfile inclusion test |
| `models/binary-content` | `weights.bin` (1024 bytes, 0x00-0xFF), `header.bin` (binary with nulls) | Binary data test |
| `models/hidden-subdir` | `model.bin`, `.cache/weights.bin`, `.local/share/data.bin` | Hidden directory inclusion test |

## Key Material (`test/assets/keys/`)

| Path | Purpose |
|---|---|
| `keys/certificate/signing-key.pem` | Private key for signing (EC P-256) |
| `keys/certificate/signing-key-pub.pem` | Public key for key-method verification |
| `keys/certificate/signing-key-cert.pem` | Leaf certificate for certificate-method signing |
| `keys/certificate/int-ca-cert.pem` | Intermediate CA certificate |
| `keys/certificate/ca-cert.pem` | Root CA certificate (trust anchor for verification) |
| `keys/p384/signing-key.pem` | EC P-384 private key — used in P-384 roundtrip test |
| `keys/p384/signing-key-pub.pem` | EC P-384 public key |
| `keys/p521/signing-key.pem` | EC P-521 private key — used in P-521 roundtrip test |
| `keys/p521/signing-key-pub.pem` | EC P-521 public key |
| `keys/self-signed/signing-key.pem` | Private key for self-signed certificate test |
| `keys/self-signed/signing-cert.pem` | Self-signed certificate (EC P-256) |
| `keys/wrong/wrong-key-pub.pem` | Unrelated public key — used in wrong-key failure test |
| `keys/wrong/wrong-ca-cert.pem` | Unrelated CA certificate — used in wrong-CA failure test |
