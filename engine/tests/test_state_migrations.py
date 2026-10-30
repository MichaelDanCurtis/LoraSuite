import json

from lorasuite_engine.state_migrations import StateMigrationService


def test_migrates_legacy_state_with_backups_and_is_idempotent(tmp_path):
    vault_root = tmp_path / "vault"
    vault_root.mkdir()
    vault_payload = {
        "sources": [{"id": "source-1", "kind": "local"}],
        "media_items": [{"id": "media-1", "source_id": "source-1"}],
    }
    candidates_payload = {
        "candidates": [{"id": "candidate-1", "selected": True}],
    }
    processing_payload = {
        "processing-job-1": {"id": "processing-job-1", "status": "complete"},
    }
    (vault_root / "vault.json").write_text(json.dumps(vault_payload), encoding="utf-8")
    (vault_root / "ingress_candidates.json").write_text(
        json.dumps(candidates_payload),
        encoding="utf-8",
    )
    (vault_root / "processing_jobs.json").write_text(
        json.dumps(processing_payload),
        encoding="utf-8",
    )
    service = StateMigrationService(vault_root)

    preview = service.inspect()

    assert preview.dry_run is True
    assert preview.pending_count == 3
    assert json.loads((vault_root / "vault.json").read_text(encoding="utf-8")) == vault_payload
    assert not service.ledger_path.exists()

    migrated = service.migrate()

    assert migrated.ready is True
    assert migrated.updated_count == 3
    assert migrated.backup_root is not None
    assert json.loads((migrated.backup_root / "vault.json").read_text(encoding="utf-8")) == vault_payload
    assert json.loads((migrated.backup_root / "ingress_candidates.json").read_text(encoding="utf-8")) == candidates_payload
    assert not (migrated.backup_root / "processing_jobs.json").exists()
    migrated_vault = json.loads((vault_root / "vault.json").read_text(encoding="utf-8"))
    assert migrated_vault["version"] == 1
    assert migrated_vault["sources"] == vault_payload["sources"]
    assert migrated_vault["media_items"] == vault_payload["media_items"]
    assert json.loads((vault_root / "ingress_candidates.json").read_text(encoding="utf-8")) == {
        **candidates_payload,
        "version": 1,
    }
    assert json.loads((vault_root / "processing_jobs.json").read_text(encoding="utf-8")) == processing_payload
    ledger = json.loads(service.ledger_path.read_text(encoding="utf-8"))
    assert ledger["format"] == "lorasuite.state-schema.v1"
    assert ledger["files"]["processing_jobs.json"]["version"] == 1

    second = service.migrate()

    assert second.ready is True
    assert second.updated_count == 0
    assert second.backup_root is None
    assert all(
        item.status in {"current", "missing"}
        for item in second.files
    )


def test_wraps_legacy_collection_lists_without_changing_entries(tmp_path):
    vault_root = tmp_path / "vault"
    vault_root.mkdir()
    projects = [{"id": "character-project-1", "name": "Recovered project"}]
    (vault_root / "character_projects.json").write_text(
        json.dumps(projects),
        encoding="utf-8",
    )

    report = StateMigrationService(vault_root).migrate()

    assert report.ready is True
    payload = json.loads(
        (vault_root / "character_projects.json").read_text(encoding="utf-8"),
    )
    assert payload == {"version": 1, "projects": projects}


def test_reports_invalid_json_without_overwriting_it(tmp_path):
    vault_root = tmp_path / "vault"
    vault_root.mkdir()
    invalid = "{not-json"
    path = vault_root / "vault.json"
    path.write_text(invalid, encoding="utf-8")

    preview = StateMigrationService(vault_root).inspect()
    applied = StateMigrationService(vault_root).migrate()

    assert preview.ready is False
    assert preview.invalid_count == 1
    assert applied.ready is False
    assert applied.invalid_count == 1
    assert applied.updated_count == 0
    assert path.read_text(encoding="utf-8") == invalid
