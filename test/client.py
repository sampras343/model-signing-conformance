"""ModelSigningClient — wraps the conformance adapter entrypoint."""

from __future__ import annotations

import json
import os
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, Optional

_VALID_EXPECT = ("pass", "fail")
_VALID_RELATIVE_TO = ("assets", "test_dir")

_SHARD_SUFFIX_RE = re.compile(r":\d+:\d+$")


def _is_shard_resource(name: str) -> bool:
    """Return True if *name* looks like a shard resource (``path:start:end``)."""
    return _SHARD_SUFFIX_RE.search(name) is not None


def _read_identity_token(env_name: str) -> str:
    """Read an OIDC identity token.

    Checks two sources in order:
    1. Direct value from env var ``env_name`` (e.g. SIGSTORE_ID_TOKEN).
    2. File path from ``{env_name}_FILE`` (e.g. SIGSTORE_ID_TOKEN_FILE).
    """
    direct = os.environ.get(env_name, "")
    if direct:
        return direct
    file_path = os.environ.get(f"{env_name}_FILE", "")
    if file_path and Path(file_path).is_file():
        return Path(file_path).read_text().strip()
    return ""


class ConfigError(Exception):
    """Raised when a test config.json is invalid."""


@dataclass
class ModelModifications:
    """Modifications to apply to a copied model before verification."""
    tamper: dict[str, str] = field(default_factory=dict)
    delete: list[str] = field(default_factory=list)
    inject: dict[str, str] = field(default_factory=dict)
    symlinks: dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict) -> "ModelModifications":
        return cls(
            tamper=data.get("tamper", {}),
            delete=data.get("delete", []),
            inject=data.get("inject", {}),
            symlinks=data.get("symlinks", {}),
        )

    def apply(self, model_dir: Path) -> None:
        """Apply modifications to a model directory."""
        for filename, content in self.tamper.items():
            (model_dir / filename).write_text(content)
        for filename in self.delete:
            path = model_dir / filename
            if path.exists():
                path.unlink()
        for filename, content in self.inject.items():
            (model_dir / filename).write_text(content)
        for name, target in self.symlinks.items():
            link = model_dir / name
            link.parent.mkdir(parents=True, exist_ok=True)
            link.symlink_to(target)


@dataclass
class SignBlock:
    """Signing parameters within a config."""
    private_key: Optional[str] = None
    signing_cert: Optional[str] = None
    cert_chain: list[str] = field(default_factory=list)
    identity_token_env: Optional[str] = None
    use_staging: bool = False

    @classmethod
    def from_dict(cls, data: dict) -> "SignBlock":
        return cls(
            private_key=data.get("private_key"),
            signing_cert=data.get("signing_cert"),
            cert_chain=data.get("cert_chain", []),
            identity_token_env=data.get("identity_token_env"),
            use_staging=data.get("use_staging", False),
        )


@dataclass
class VerifyBlock:
    """Verification parameters within a config."""
    public_key: Optional[str] = None
    cert_chain: list[str] = field(default_factory=list)
    ignore_paths: list[str] = field(default_factory=list)
    ignore_unsigned_files: bool = False
    identity: Optional[str] = None
    identity_provider: Optional[str] = None
    use_staging: bool = False

    @classmethod
    def from_dict(cls, data: dict) -> "VerifyBlock":
        return cls(
            public_key=data.get("public_key"),
            cert_chain=data.get("cert_chain", []),
            ignore_paths=data.get("ignore_paths", []),
            ignore_unsigned_files=data.get("ignore_unsigned_files", False),
            identity=data.get("identity"),
            identity_provider=data.get("identity_provider"),
            use_staging=data.get("use_staging", False),
        )


@dataclass
class CaseConfig:
    """Unified test configuration for both verify and roundtrip tests."""
    description: str
    method: str
    model: str
    model_relative_to: Literal["assets", "test_dir"] = "assets"
    expect: Literal["pass", "fail"] = "pass"
    sig_inside_model: bool = False
    requires_ci: bool = False
    sign: Optional[SignBlock] = None
    verify: Optional[VerifyBlock] = None
    expected_signed_files: Optional[list[str]] = None
    model_modifications: Optional[ModelModifications] = None

    @classmethod
    def from_json(cls, path: Path) -> "CaseConfig":
        data = json.loads(path.read_text())
        cls._validate_raw(data, path)

        sign_block = None
        if "sign" in data:
            sign_block = SignBlock.from_dict(data["sign"])

        verify_block = None
        if "verify" in data:
            verify_block = VerifyBlock.from_dict(data["verify"])

        mods = None
        if "model_modifications" in data:
            mods = ModelModifications.from_dict(data["model_modifications"])

        return cls(
            description=data["description"],
            method=data["method"],
            model=data["model"],
            model_relative_to=data.get("model_relative_to", "assets"),
            expect=data.get("expect", "pass"),
            sig_inside_model=data.get("sig_inside_model", False),
            requires_ci=data.get("requires_ci", False),
            sign=sign_block,
            verify=verify_block,
            expected_signed_files=data.get("expected_signed_files"),
            model_modifications=mods,
        )

    @staticmethod
    def _validate_raw(data: dict, path: Path) -> None:
        """Validate required fields and enum values."""
        for key in ("description", "method", "model"):
            if key not in data:
                raise ConfigError(f"{path}: missing required field '{key}'")
        rel = data.get("model_relative_to", "assets")
        if rel not in _VALID_RELATIVE_TO:
            raise ConfigError(
                f"{path}: 'model_relative_to' must be one of {_VALID_RELATIVE_TO}, got '{rel}'"
            )
        expect = data.get("expect", "pass")
        if expect not in _VALID_EXPECT:
            raise ConfigError(
                f"{path}: 'expect' must be one of {_VALID_EXPECT}, got '{expect}'"
            )


TestConfig = CaseConfig


class ModelSigningClient:
    """Wrapper around the conformance adapter entrypoint."""

    def __init__(self, entrypoint: str) -> None:
        self.entrypoint = entrypoint

    def _run(self, args: list[str]) -> subprocess.CompletedProcess:
        cmd = [self.entrypoint] + args
        return subprocess.run(cmd, capture_output=True, text=True)

    def sign(
        self,
        method: str,
        model_path: Path,
        output_bundle: Path,
        cfg: CaseConfig,
        assets_root: Path,
    ) -> subprocess.CompletedProcess:
        args = [
            "sign-model",
            "--method", method,
            "--model-path", str(model_path),
            "--output-bundle", str(output_bundle),
        ]

        sign_block = cfg.sign
        if sign_block:
            if sign_block.private_key:
                args += ["--private-key", str(assets_root / sign_block.private_key)]
            if sign_block.signing_cert:
                args += ["--signing-cert", str(assets_root / sign_block.signing_cert)]
            for cert in sign_block.cert_chain:
                args += ["--cert-chain", str(assets_root / cert)]
            if sign_block.identity_token_env:
                token = _read_identity_token(sign_block.identity_token_env)
                if token:
                    args += ["--identity-token", token]
            if sign_block.use_staging:
                args += ["--use-staging"]

        verify_block = cfg.verify
        if verify_block:
            for p in verify_block.ignore_paths:
                abs_p = str(model_path / p) if not Path(p).is_absolute() else p
                args += ["--ignore-paths", abs_p]

        result = self._run(args)
        if result.returncode != 0:
            print(f"[sign stdout] {result.stdout}")
            print(f"[sign stderr] {result.stderr}")
        return result

    def verify(
        self,
        method: str,
        model_path: Path,
        bundle: Path,
        cfg: CaseConfig,
        keys_root: Path,
        ignore_paths_abs: list[str] | None = None,
    ) -> subprocess.CompletedProcess:
        """Verify a bundle.

        Args:
            model_path: Absolute path to the model directory or file.
            bundle: Absolute path to the bundle file.
            cfg: Test config with verify block (key paths relative to keys_root).
            keys_root: Root directory for resolving key/cert paths in cfg.
            ignore_paths_abs: Absolute paths to ignore. If None, derived from
                cfg.verify.ignore_paths by resolving relative names against model_path.
        """
        args = [
            "verify-model",
            "--method", method,
            "--model-path", str(model_path),
            "--bundle", str(bundle),
        ]

        verify_block = cfg.verify
        if verify_block:
            if verify_block.public_key:
                args += ["--public-key", str(keys_root / verify_block.public_key)]
            for cert in verify_block.cert_chain:
                args += ["--cert-chain", str(keys_root / cert)]

            if verify_block.identity:
                identity = verify_block.identity
                if identity.startswith("${") and identity.endswith("}"):
                    identity = os.environ.get(identity[2:-1], identity)
                args += ["--identity", identity]
            if verify_block.identity_provider:
                provider = verify_block.identity_provider
                if provider.startswith("${") and provider.endswith("}"):
                    provider = os.environ.get(provider[2:-1], provider)
                args += ["--identity-provider", provider]
            if verify_block.use_staging:
                args += ["--use-staging"]

            effective_ignore = ignore_paths_abs if ignore_paths_abs is not None else []
            if not effective_ignore and verify_block.ignore_paths:
                model_dir = model_path if model_path.is_dir() else model_path.parent
                effective_ignore = [str(model_dir / p) for p in verify_block.ignore_paths]
            for p in effective_ignore:
                args += ["--ignore-paths", p]

            if verify_block.ignore_unsigned_files:
                args += ["--ignore-unsigned-files"]

        result = self._run(args)
        if result.returncode != 0:
            print(f"[verify stdout] {result.stdout}")
            print(f"[verify stderr] {result.stderr}")
        return result

    def get_signed_files(self, bundle: Path) -> list[str]:
        """Extract sorted list of signed file names from a bundle."""
        import base64
        bundle_data = json.loads(bundle.read_text())
        payload_b64 = bundle_data["dsseEnvelope"]["payload"]
        payload = json.loads(base64.b64decode(payload_b64))
        resources = payload["predicate"]["resources"]
        names = [r["name"] for r in resources if not _is_shard_resource(r["name"])]
        return sorted(names)
