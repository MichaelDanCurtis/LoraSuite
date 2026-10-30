import json
import zipfile

from PIL import Image

from lorasuite_engine.diagnostics import DiagnosticBundleService
from lorasuite_engine.dataset_projects import CharacterProjectService
from lorasuite_engine.vault import VaultService, sha256_file


def test_creates_privacy_safe_diagnostic_bundle_without_media_or_credentials(
    tmp_path,
    monkeypatch,
):
    vault_root = tmp_path / "vault"
    source = tmp_path / "private-person-photo.png"
    Image.new("RGB", (16, 16), (120, 80, 40)).save(source)
    imported = VaultService(vault_root).import_local_paths([source])
    assert len(imported.media_items) == 1
    secrets = [
        "runpod-secret-value-that-must-not-leak",
        "hugging-face-secret-that-must-not-leak",
        "kimi-code-secret-that-must-not-leak",
    ]
    monkeypatch.setenv("RUNPOD_API_KEY", secrets[0])
    monkeypatch.setenv("HF_TOKEN", secrets[1])
    monkeypatch.setenv("KIMI_CODE_API_KEY", secrets[2])

    record = DiagnosticBundleService(vault_root).create()

    assert record.archive_path.is_file()
    assert record.archive_sha256 == sha256_file(record.archive_path)
    assert record.included_files == [
        "diagnostic_report.json",
        "partner_readiness.json",
        "README.txt",
    ]
    with zipfile.ZipFile(record.archive_path) as archive:
        assert sorted(archive.namelist()) == [
            "README.txt",
            "diagnostic_report.json",
            "partner_readiness.json",
        ]
        report_text = archive.read("diagnostic_report.json").decode("utf-8")
        report = json.loads(report_text)
        combined = "\n".join(
            archive.read(name).decode("utf-8")
            for name in archive.namelist()
        )
    assert report["privacy"] == {
        "absolute_paths_included": False,
        "captions_or_transcripts_included": False,
        "credentials_included": False,
        "media_included": False,
        "source_urls_or_handles_included": False,
    }
    assert report["inventory"]["media_total"] == 1
    assert report["inventory"]["media_by_type"] == {"image": 1}
    assert all(secret not in combined for secret in secrets)
    assert str(vault_root) not in combined
    assert str(source) not in combined
    assert source.name not in combined
    assert source.read_bytes() not in record.archive_path.read_bytes()


def test_diagnostic_registry_is_persistent(tmp_path):
    service = DiagnosticBundleService(tmp_path / "vault")

    created = service.create()
    restored = DiagnosticBundleService(tmp_path / "vault").list_bundles()

    assert [record.id for record in restored] == [created.id]
    assert restored[0].archive_sha256 == created.archive_sha256


def test_includes_privacy_safe_project_qualification_when_requested(tmp_path):
    vault_root = tmp_path / "vault"
    project = CharacterProjectService(vault_root).create_project(
        name="Private Person Name",
    )

    record = DiagnosticBundleService(vault_root).create(project_id=project.id)

    assert record.partner_qualification_included is True
    assert "partner_qualification.json" in record.included_files
    with zipfile.ZipFile(record.archive_path) as archive:
        qualification = json.loads(
            archive.read("partner_qualification.json").decode("utf-8")
        )
        combined = "\n".join(
            archive.read(name).decode("utf-8")
            for name in archive.namelist()
        )
    assert qualification["format"] == "lorasuite.partner-qualification.v1"
    assert qualification["project_id"] == project.id
    assert qualification["total_count"] > 0
    assert "Private Person Name" not in combined
    assert str(vault_root) not in combined
