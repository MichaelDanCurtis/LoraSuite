#!/usr/bin/env python3
"""Package only the reviewed Git tree; never sweep the local working directory."""
from __future__ import annotations

import hashlib
import io
import json
import subprocess
import tarfile
import zipfile
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]


def git(*args: str) -> bytes:
    return subprocess.check_output(["git", *args], cwd=ROOT)


def main() -> None:
    names = git("ls-tree", "-r", "--name-only", "HEAD").decode().splitlines()
    required = {"README.md", "LICENSE", "NOTICE", "SECURITY.md", "CONTRIBUTING.md", "THIRD_PARTY_NOTICES.md", "package-lock.json", "engine/uv.lock", "src-tauri/Cargo.lock", "extensions/lorasuite-companion/manifest.json"}
    missing = required.difference(names)
    forbidden_roots = {".lorasuite", ".omc", "'", "archive", "node_modules", "release-artifacts"}
    private = [name for name in names if PurePosixPath(name).parts[0] in forbidden_roots or name.startswith(("docs/qualification/", "docs/superpowers/")) or (PurePosixPath(name).name.startswith(".env") and name != ".env.example") or PurePosixPath(name).suffix.lower() in {".safetensors", ".ckpt", ".sqlite", ".sqlite3", ".db", ".pem", ".p12", ".key"}]
    if missing or private:
        raise SystemExit(f"Release inventory failed: missing={sorted(missing)}, private={private}")
    version = json.loads(git("show", "HEAD:package.json"))["version"]
    output = ROOT / "release-artifacts"
    output.mkdir(exist_ok=True)
    archive = output / f"LoraSuite-{version}-source.tar.gz"
    archive.write_bytes(git("archive", "--format=tar.gz", f"--prefix=LoraSuite-{version}/", "HEAD"))
    companion_version = json.loads(git("show", "HEAD:extensions/lorasuite-companion/manifest.json"))["version"]
    companion = output / f"LoraSuite-Companion-{companion_version}.zip"
    with zipfile.ZipFile(companion, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
        for name in sorted(names):
            if name.startswith("extensions/lorasuite-companion/") and ".test." not in name:
                bundle.writestr(zipfile.ZipInfo("lorasuite-companion/" + name.split("/", 2)[2], (2026, 1, 1, 0, 0, 0)), git("show", f"HEAD:{name}"))
        for name in ("LICENSE", "NOTICE", "THIRD_PARTY_NOTICES.md", "docs/companion.md"):
            bundle.writestr(zipfile.ZipInfo("lorasuite-companion/" + PurePosixPath(name).name, (2026, 1, 1, 0, 0, 0)), git("show", f"HEAD:{name}"))
    with tarfile.open(fileobj=io.BytesIO(archive.read_bytes()), mode="r:gz") as bundle:
        if any(name.endswith("/.env.local") for name in bundle.getnames()):
            raise SystemExit("Private configuration in archive")
    sums = "".join(f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}\n" for path in (archive, companion))
    (output / "SHA256SUMS").write_text(sums)
    print(sums, end="")


if __name__ == "__main__":
    main()
