#!/usr/bin/env bash
# generate-verify-assets.sh — Generate pre-committed bundles for verify/ test cases.
#
# Run this script once when:
#   - Adding new test cases that require fresh bundles
#   - Updating key material
#   - Regenerating cross-language interop bundles
#
# Requires:
#   - model-signing (Go binary) in PATH or passed via GO_BIN env var
#   - model_signing (Python package) installed: pip install model-signing
#   - openssl (for wrong-key generation, already done if keys/wrong/ exists)
#
# Usage:
#   ./tools/generate-verify-assets.sh
#   GO_BIN=/path/to/model-signing ./tools/generate-verify-assets.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"
ASSETS="$REPO_ROOT/test/assets"
VERIFY="$ASSETS/verify"
KEYS="$ASSETS/keys/certificate"

GO_BIN="${GO_BIN:-model-signing}"
PYTHON_BIN="${PYTHON_BIN:-python3}"

# Verify tools are available
if ! command -v "$GO_BIN" &>/dev/null; then
    echo "ERROR: Go binary not found: $GO_BIN"
    echo "  Build it with: make build && cp bin/model-signing /usr/local/bin/"
    exit 1
fi

if ! "$PYTHON_BIN" -m model_signing --help &>/dev/null; then
    echo "ERROR: Python model_signing not available"
    echo "  Install it with: pip install model-signing"
    exit 1
fi

echo "Using Go:    $($GO_BIN version 2>/dev/null || echo $GO_BIN)"
echo "Using Python: $($PYTHON_BIN -m model_signing --version 2>/dev/null || echo model_signing)"
echo ""

sign_with_go() {
    local method="$1" model_dir="$2" bundle_out="$3" ; shift 3
    echo "  [GO] sign $method → $bundle_out"
    # Note: Go --ignore-paths requires a full path to an existing file/dir
    case "$method" in
        key)
            "$GO_BIN" sign key \
                --signature "$bundle_out" \
                --private-key "$KEYS/signing-key.pem" \
                "$@" "$model_dir"
            ;;
        certificate)
            "$GO_BIN" sign certificate \
                --signature "$bundle_out" \
                --private-key "$KEYS/signing-key.pem" \
                --signing-certificate "$KEYS/signing-key-cert.pem" \
                --certificate-chain "$KEYS/int-ca-cert.pem" \
                "$@" "$model_dir"
            ;;
    esac
}

sign_with_python() {
    local method="$1" model_dir="$2" bundle_out="$3" ; shift 3
    echo "  [PYTHON] sign $method → $bundle_out"
    # Python 1.1.1 uses underscores in flag names
    case "$method" in
        key)
            "$PYTHON_BIN" -m model_signing sign key \
                --signature "$bundle_out" \
                --private_key "$KEYS/signing-key.pem" \
                "$@" "$model_dir"
            ;;
        certificate)
            "$PYTHON_BIN" -m model_signing sign certificate \
                --signature "$bundle_out" \
                --private_key "$KEYS/signing-key.pem" \
                --signing_certificate "$KEYS/signing-key-cert.pem" \
                --certificate_chain "$KEYS/int-ca-cert.pem" \
                "$@" "$model_dir"
            ;;
    esac
}

# All canonical verify/ bundles are signed by the Python reference implementation.
# The signer identity is documented in each test case's README but is NOT reflected
# in the test name — the test describes the scenario, not who signed it.
# Every client (Go, Python, future clients) runs the same set of tests.

echo "=== Generating canonical bundles (signed by Python reference implementation) ==="

# key-simple
MODEL="$VERIFY/key-simple/model"
sign_with_python key "$MODEL" "$VERIFY/key-simple/bundle.sig" \
    --ignore-paths "$MODEL/ignore-me"

# certificate-simple
MODEL="$VERIFY/certificate-simple/model"
sign_with_python certificate "$MODEL" "$VERIFY/certificate-simple/bundle.sig" \
    --ignore-paths "$MODEL/ignore-me"

# key-multi-file
MODEL="$VERIFY/key-multi-file/model"
sign_with_python key "$MODEL" "$VERIFY/key-multi-file/bundle.sig"

# key-ignore-paths
MODEL="$VERIFY/key-ignore-paths/model"
sign_with_python key "$MODEL" "$VERIFY/key-ignore-paths/bundle.sig" \
    --ignore-paths "$MODEL/ignore-me"

# key-single-file
MODEL="$VERIFY/key-single-file/model"
sign_with_python key "$MODEL" "$VERIFY/key-single-file/bundle.sig"

# key-simple-ignore-unsigned-files (signed over clean model; extra.bin added after)
MODEL="$VERIFY/key-simple-ignore-unsigned-files/model"
sign_with_python key "$MODEL" "$VERIFY/key-simple-ignore-unsigned-files/bundle.sig" \
    --ignore-paths "$MODEL/ignore-me"
# Add extra file AFTER signing — verifier must use --ignore-unsigned-files to pass
printf 'extra file added after signing\n' > "$VERIFY/key-simple-ignore-unsigned-files/model/extra.bin"

echo ""
echo "=== Generating failure test bundles ==="

# key-simple-tampered-content_fail:
# Sign first (over clean model), then tamper signme-1 in the test dir
TMPDIR_TC="$(mktemp -d)"
cp "$ASSETS/models/simple/signme-1" "$ASSETS/models/simple/signme-2" \
   "$ASSETS/models/simple/ignore-me" "$TMPDIR_TC/"
sign_with_python key "$TMPDIR_TC" "$VERIFY/key-simple-tampered-content_fail/bundle.sig" \
    --ignore-paths "$TMPDIR_TC/ignore-me"
rm -rf "$TMPDIR_TC"
# Now tamper signme-1 in the verify directory
printf 'TAMPERED CONTENT\n' > "$VERIFY/key-simple-tampered-content_fail/model/signme-1"

# key-simple-wrong-key_fail: sign with correct key, bundle goes to wrong-key dir
#   (model is the same, only the public key in config.json is wrong)
MODEL="$VERIFY/key-simple-wrong-key_fail/model"
sign_with_python key "$MODEL" "$VERIFY/key-simple-wrong-key_fail/bundle.sig" \
    --ignore-paths "$MODEL/ignore-me"

# certificate-simple-wrong-ca_fail: sign with correct cert, bundle goes to wrong-ca dir
MODEL="$VERIFY/certificate-simple-wrong-ca_fail/model"
sign_with_python certificate "$MODEL" "$VERIFY/certificate-simple-wrong-ca_fail/bundle.sig" \
    --ignore-paths "$MODEL/ignore-me"

# key-simple-missing-file_fail: sign over all files, then test dir only has signme-1
TMPDIR_MF="$(mktemp -d)"
cp "$ASSETS/models/simple/signme-1" "$ASSETS/models/simple/signme-2" \
   "$ASSETS/models/simple/ignore-me" "$TMPDIR_MF/"
sign_with_python key "$TMPDIR_MF" "$VERIFY/key-simple-missing-file_fail/bundle.sig" \
    --ignore-paths "$TMPDIR_MF/ignore-me"
rm -rf "$TMPDIR_MF"
# signme-2 is already absent in the test case model dir

# key-simple-extra-file_fail: sign the simple model (no extra file), extra.bin already in model dir
TMPDIR_EF="$(mktemp -d)"
cp "$ASSETS/models/simple/signme-1" "$ASSETS/models/simple/signme-2" \
   "$ASSETS/models/simple/ignore-me" "$TMPDIR_EF/"
sign_with_python key "$TMPDIR_EF" "$VERIFY/key-simple-extra-file_fail/bundle.sig" \
    --ignore-paths "$TMPDIR_EF/ignore-me"
rm -rf "$TMPDIR_EF"
# injected.bin is already in the test case model dir

# key-simple-truncated-bundle_fail: truncate the canonical key-simple bundle
head -c 100 "$VERIFY/key-simple/bundle.sig" > "$VERIFY/key-simple-truncated-bundle_fail/bundle.sig"

echo ""
echo "=== Generating structural / crypto failure bundles ==="

NEGATIVE="$VERIFY/negative"

# malformed-empty-bundle_fail: zero-byte bundle
: > "$NEGATIVE/malformed-empty-bundle_fail/bundle.sig"

# malformed-missing-envelope_fail: valid JSON with mediaType + verificationMaterial but no dsseEnvelope
cat > "$NEGATIVE/malformed-missing-envelope_fail/bundle.sig" <<'ENDJSON'
{"mediaType":"application/vnd.dev.sigstore.bundle.v0.3+json","verificationMaterial":{"publicKey":{"hint":"e8450dec4eb99dae995da9af1bc2cc9f76ed669ee2e744f57abba763df3e3f8e"},"tlogEntries":[]}}
ENDJSON

# malformed-wrong-predicate_fail: valid bundle structure but predicateType swapped
"$PYTHON_BIN" -c "
import json, base64
bundle = json.loads(open('$NEGATIVE/../positive/key-simple/bundle.sig').read())
payload = json.loads(base64.b64decode(bundle['dsseEnvelope']['payload']))
payload['predicateType'] = 'https://example.com/wrong-predicate/v1.0'
bundle['dsseEnvelope']['payload'] = base64.b64encode(json.dumps(payload, indent=2).encode()).decode()
open('$NEGATIVE/malformed-wrong-predicate_fail/bundle.sig', 'w').write(json.dumps(bundle))
"

# certificate-expired_fail: sign with an expired cert (notAfter: 2020-01-02)
# Cannot use sign_with_python() because it hardcodes key material from $KEYS.
EXPIRED_KEYS="$ASSETS/keys/expired"
TMPDIR_EX="$(mktemp -d)"
cp "$ASSETS/models/simple/signme-1" "$ASSETS/models/simple/signme-2" "$TMPDIR_EX/"
echo "  [PYTHON] sign certificate (expired) → $NEGATIVE/certificate-expired_fail/bundle.sig"
"$PYTHON_BIN" -m model_signing sign certificate \
    --signature "$NEGATIVE/certificate-expired_fail/bundle.sig" \
    --private_key "$EXPIRED_KEYS/signing-key.pem" \
    --signing_certificate "$EXPIRED_KEYS/signing-key-cert.pem" \
    --certificate_chain "$KEYS/int-ca-cert.pem" \
    "$TMPDIR_EX"
rm -rf "$TMPDIR_EX"

echo ""
echo "=== Generating cross-client interop bundles (signed by Go) ==="

# key-simple-go: same model/keys as key-simple, signed by Go adapter
MODEL="$ASSETS/models/simple"
sign_with_go key "$MODEL" "$VERIFY/positive/key-simple-go/bundle.sig" \
    --ignore-paths "$MODEL/ignore-me"

# certificate-simple-go: same model/keys as certificate-simple, signed by Go adapter
sign_with_go certificate "$MODEL" "$VERIFY/positive/certificate-simple-go/bundle.sig" \
    --ignore-paths "$MODEL/ignore-me"

echo ""
echo "Done! All pre-committed bundles generated."
echo ""
echo "Spot-check: Go verifies canonical bundles (proves spec compliance + cross-language interop):"
"$GO_BIN" verify key \
    --signature "$VERIFY/key-simple/bundle.sig" \
    --public-key "$KEYS/signing-key-pub.pem" \
    --ignore-paths "$VERIFY/key-simple/model/ignore-me" \
    "$VERIFY/key-simple/model" && echo "  key-simple: PASS" || echo "  key-simple: FAIL"

"$GO_BIN" verify certificate \
    --signature "$VERIFY/certificate-simple/bundle.sig" \
    --certificate-chain "$KEYS/ca-cert.pem" \
    --ignore-paths "$VERIFY/certificate-simple/model/ignore-me" \
    "$VERIFY/certificate-simple/model" && echo "  certificate-simple: PASS" || echo "  certificate-simple: FAIL"
