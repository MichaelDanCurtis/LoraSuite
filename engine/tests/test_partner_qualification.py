import json

from lorasuite_engine.dataset_projects import CharacterProjectService
from lorasuite_engine.partner_qualification import PartnerQualificationService


def test_empty_project_reports_every_provider_and_comfyui_evidence_gate(tmp_path) -> None:
    vault = tmp_path / "vault"
    project = CharacterProjectService(vault).create_project(name="Qualification Matrix")

    report = PartnerQualificationService(vault).report(project.id)

    assert report.format == "lorasuite.partner-qualification.v1"
    assert report.status == "in_progress"
    assert report.passed_count == 0
    assert report.total_count == 52
    assert {(lane.partner, lane.lane) for lane in report.lanes} == {
        ("runcomfy", "image"),
        ("runpod", "image"),
        ("runcomfy", "video"),
        ("runpod", "video"),
        ("runpod", "voice"),
        ("runpod", "id_lora"),
        ("comfyui", "image"),
        ("comfyui", "video"),
    }
    assert all(lane.status == "in_progress" for lane in report.lanes)
    assert report.next_actions

    serialized = json.dumps(report.model_dump(mode="json"), sort_keys=True)
    assert str(vault) not in serialized
    assert "source_export_path" not in serialized


def test_report_rejects_an_unknown_project(tmp_path) -> None:
    try:
        PartnerQualificationService(tmp_path / "vault").report("missing")
    except KeyError as error:
        assert error.args == ("missing",)
    else:
        raise AssertionError("unknown projects must not produce qualification reports")
