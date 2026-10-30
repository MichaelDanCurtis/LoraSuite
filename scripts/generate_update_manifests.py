#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from urllib.parse import quote


VERSION_PATTERN = re.compile(
    r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)"
    r"(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?$"
)
DEFAULT_PLATFORM = "darwin-aarch64"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Create or normalize signed Tauri static update manifests."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    create = subparsers.add_parser("create", help="Create a release manifest.")
    create.add_argument("--version", required=True)
    create.add_argument("--archive", type=Path, required=True)
    create.add_argument("--signature", type=Path, required=True)
    create.add_argument("--base-url", required=True)
    create.add_argument("--output", type=Path, required=True)
    create.add_argument("--platform", default=DEFAULT_PLATFORM)
    create.add_argument("--notes", default="")
    create.add_argument("--pub-date", default="")

    copy = subparsers.add_parser(
        "copy", help="Validate and normalize an existing signed release manifest."
    )
    copy.add_argument("--source", type=Path, required=True)
    copy.add_argument("--output", type=Path, required=True)

    args = parser.parse_args()
    if args.command == "create":
        manifest = create_manifest(
            version=args.version,
            archive=args.archive,
            signature_path=args.signature,
            base_url=args.base_url,
            platform=args.platform,
            notes=args.notes,
            pub_date=args.pub_date,
        )
    else:
        manifest = load_manifest(args.source)
    write_manifest(args.output, manifest)


def create_manifest(
    *,
    version: str,
    archive: Path,
    signature_path: Path,
    base_url: str,
    platform: str = DEFAULT_PLATFORM,
    notes: str = "",
    pub_date: str = "",
) -> dict[str, object]:
    validate_version(version)
    if not archive.is_file():
        raise ValueError(f"Updater archive does not exist: {archive}")
    if not signature_path.is_file():
        raise ValueError(f"Updater signature does not exist: {signature_path}")
    signature = signature_path.read_text(encoding="utf-8").strip()
    if not signature:
        raise ValueError("Updater signature is empty.")
    if not platform.strip():
        raise ValueError("Updater platform cannot be empty.")
    if not base_url.startswith("https://"):
        raise ValueError("Updater assets must use an HTTPS base URL.")

    manifest: dict[str, object] = {
        "version": version,
        "platforms": {
            platform: {
                "signature": signature,
                "url": f"{base_url.rstrip('/')}/{quote(archive.name)}",
            }
        },
    }
    if notes.strip():
        manifest["notes"] = notes.strip()
    if pub_date.strip():
        manifest["pub_date"] = pub_date.strip()
    validate_manifest(manifest)
    return manifest


def load_manifest(path: Path) -> dict[str, object]:
    if not path.is_file():
        raise ValueError(f"Update manifest does not exist: {path}")
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ValueError(f"Update manifest is not valid JSON: {error}") from error
    validate_manifest(manifest)
    return manifest


def validate_manifest(manifest: object) -> None:
    if not isinstance(manifest, dict):
        raise ValueError("Update manifest must be a JSON object.")
    version = manifest.get("version")
    if not isinstance(version, str):
        raise ValueError("Update manifest requires a string version.")
    validate_version(version)
    platforms = manifest.get("platforms")
    if not isinstance(platforms, dict) or not platforms:
        raise ValueError("Update manifest requires at least one platform.")
    for platform, artifact in platforms.items():
        if not isinstance(platform, str) or not platform.strip():
            raise ValueError("Update manifest platform names cannot be empty.")
        if not isinstance(artifact, dict):
            raise ValueError(f"Update platform {platform} must be an object.")
        signature = artifact.get("signature")
        url = artifact.get("url")
        if not isinstance(signature, str) or not signature.strip():
            raise ValueError(f"Update platform {platform} requires a signature.")
        if not isinstance(url, str) or not url.startswith("https://"):
            raise ValueError(f"Update platform {platform} requires an HTTPS URL.")


def validate_version(version: str) -> None:
    if not VERSION_PATTERN.fullmatch(version.strip()):
        raise ValueError(f"Invalid semantic version: {version}")


def write_manifest(path: Path, manifest: dict[str, object]) -> None:
    validate_manifest(manifest)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    try:
        main()
    except ValueError as error:
        raise SystemExit(str(error)) from error
