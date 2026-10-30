from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.generate_update_manifests import (
    create_manifest,
    load_manifest,
    validate_manifest,
    write_manifest,
)


def test_create_manifest_embeds_signed_macos_archive(tmp_path: Path) -> None:
    archive = tmp_path / "LoraSuite.app.tar.gz"
    signature = tmp_path / "LoraSuite.app.tar.gz.sig"
    archive.write_bytes(b"signed updater archive")
    signature.write_text("trusted-minisign-signature\n")

    manifest = create_manifest(
        version="1.2.3",
        archive=archive,
        signature_path=signature,
        base_url="https://github.com/example/project/releases/download/desktop-v1.2.3",
        notes="Qualified desktop release",
        pub_date="2026-07-16T20:00:00Z",
    )

    platform = manifest["platforms"]["darwin-aarch64"]
    assert platform["signature"] == "trusted-minisign-signature"
    assert platform["url"].endswith("/LoraSuite.app.tar.gz")
    assert manifest["version"] == "1.2.3"


def test_manifest_serialization_is_deterministic(tmp_path: Path) -> None:
    manifest = {
        "platforms": {
            "darwin-aarch64": {
                "url": "https://example.test/LoraSuite.app.tar.gz",
                "signature": "signature",
            }
        },
        "version": "2.0.0",
    }
    first = tmp_path / "first.json"
    second = tmp_path / "second.json"
    write_manifest(first, manifest)
    write_manifest(second, json.loads(first.read_text()))
    assert first.read_bytes() == second.read_bytes()
    assert load_manifest(first) == manifest


@pytest.mark.parametrize(
    "manifest",
    [
        {"version": "not-semver", "platforms": {}},
        {"version": "1.0.0", "platforms": {}},
        {
            "version": "1.0.0",
            "platforms": {
                "darwin-aarch64": {
                    "url": "http://unsafe.test/archive",
                    "signature": "signature",
                }
            },
        },
        {
            "version": "1.0.0",
            "platforms": {
                "darwin-aarch64": {
                    "url": "https://example.test/archive",
                    "signature": "",
                }
            },
        },
    ],
)
def test_manifest_validation_rejects_unsigned_or_unsafe_contracts(
    manifest: dict[str, object],
) -> None:
    with pytest.raises(ValueError):
        validate_manifest(manifest)
