"""ModelSigningClient — wraps the conformance adapter entrypoint."""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class ModelModifications:
    """Modifications to apply to a copied model before verification."""
    tamper: dict[str, str] = field(default_factory=dict)  # {filename: new_content}
    delete: list[str] = field(default_factory=list)       # filenames to delete
    inject: dict[str, str] = field(default_factory=dict)  # {filename: content}

    @classmethod
    def from_dict(cls, data: dict) -> "ModelModifications":
        return cls(
            tamper=data.get("tamper", {}),
            delete=data.get("delete", []),
            inject=data.get("inject", {}),
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


@dataclass
class VerifyConfig:
    """Verification parameters loaded from a verify/ test case config.json."""
    method: str
    model_path: Optional[str] = None         # relative to test case dir (legacy)
    model: Optional[str] = None              # relative to assets/ (new style)
    public_key: Optional[str] = None         # relative to assets/keys/
    cert_chain: list[str] = field(default_factory=list)
    ignore_paths: list[str] = field(default_factory=list)
    ignore_unsigned_files: bool = False
    expected_signed_files: Optional[list[str]] = None
    model_modifications: Optional[ModelModifications] = None

    @classmethod
    def from_json(cls, path: Path) -> "VerifyConfig":
        data = json.loads(path.read_text())
        mods = None
        if "model_modifications" in data:
            mods = ModelModifications.from_dict(data["model_modifications"])
        return cls(
            method=data["method"],
            model_path=data.get("model_path"),
            model=data.get("model"),
            public_key=data.get("public_key"),
            cert_chain=data.get("cert_chain", []),
            ignore_paths=data.get("ignore_paths", []),
            ignore_unsigned_files=data.get("ignore_unsigned_files", False),
            expected_signed_files=data.get("expected_signed_files"),
            model_modifications=mods,
        )


@dataclass
class SignConfig:
    """Sign parameters loaded from a roundtrip/ test case config.json."""
    method: str
    model: str                               # relative to test/assets/
    private_key: Optional[str] = None        # relative to test/assets/
    signing_cert: Optional[str] = None       # relative to test/assets/
    cert_chain: list[str] = field(default_factory=list)
    public_key: Optional[str] = None         # relative to test/assets/
    ignore_paths: list[str] = field(default_factory=list)
    ignore_unsigned_files: bool = False
    expected_signed_files: Optional[list[str]] = None

    @classmethod
    def from_json(cls, path: Path) -> "SignConfig":
        data = json.loads(path.read_text())
        return cls(
            method=data["method"],
            model=data["model"],
            private_key=data.get("private_key"),
            signing_cert=data.get("signing_cert"),
            cert_chain=data.get("cert_chain", []),
            public_key=data.get("public_key"),
            ignore_paths=data.get("ignore_paths", []),
            ignore_unsigned_files=data.get("ignore_unsigned_files", False),
            expected_signed_files=data.get("expected_signed_files"),
        )


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
        cfg: SignConfig,
        assets_root: Path,
    ) -> subprocess.CompletedProcess:
        args = [
            "sign-model",
            "--method", method,
            "--model-path", str(model_path),
            "--output-bundle", str(output_bundle),
        ]
        if cfg.private_key:
            args += ["--private-key", str(assets_root / cfg.private_key)]
        if cfg.signing_cert:
            args += ["--signing-cert", str(assets_root / cfg.signing_cert)]
        for cert in cfg.cert_chain:
            args += ["--cert-chain", str(assets_root / cert)]
        # Expand relative ignore path names to absolute paths within the model dir
        for p in cfg.ignore_paths:
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
        cfg: VerifyConfig,
        keys_root: Path,
        ignore_paths_abs: list[str] | None = None,
    ) -> subprocess.CompletedProcess:
        """Verify a bundle.

        Args:
            model_path: Absolute path to the model directory or file.
            bundle: Absolute path to the bundle file.
            cfg: Verification config (key paths relative to keys_root).
            keys_root: Root directory for resolving key/cert paths in cfg.
            ignore_paths_abs: Absolute paths to ignore. If None, derived from
                cfg.ignore_paths by resolving relative names against model_path.
        """
        args = [
            "verify-model",
            "--method", method,
            "--model-path", str(model_path),
            "--bundle", str(bundle),
        ]
        if cfg.public_key:
            args += ["--public-key", str(keys_root / cfg.public_key)]
        for cert in cfg.cert_chain:
            args += ["--cert-chain", str(keys_root / cert)]

        # Resolve ignore paths to absolute paths
        effective_ignore = ignore_paths_abs if ignore_paths_abs is not None else []
        if not effective_ignore and cfg.ignore_paths:
            model_dir = model_path if model_path.is_dir() else model_path.parent
            effective_ignore = [str(model_dir / p) for p in cfg.ignore_paths]
        for p in effective_ignore:
            args += ["--ignore-paths", p]

        if cfg.ignore_unsigned_files:
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
        # Filter out shard entries (name contains ':shard-')
        names = [r["name"] for r in resources if ":shard-" not in r["name"]]
        return sorted(names)
