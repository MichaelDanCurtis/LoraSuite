from pathlib import Path
from types import SimpleNamespace

from lorasuite_engine.ingress_analysis import IngressCandidateAnalyzer
from lorasuite_engine.models import IngressCandidate, MediaType, SourceKind


def visual_candidate(preview_path: Path, media_type: MediaType = MediaType.IMAGE) -> IngressCandidate:
    preview_path.write_bytes(b"preview")
    return IngressCandidate(
        id="candidate_visual",
        source_kind=SourceKind.INSTAGRAM,
        source_locator="https://instagram.com/p/example",
        display_name="Example",
        media_type=media_type,
        thumbnail_path=preview_path,
    )


def test_visual_preflight_keeps_a_strong_single_subject(tmp_path: Path) -> None:
    analyzer = IngressCandidateAnalyzer()
    analyzer.image_analyzer.analyze = lambda _path: SimpleNamespace(
        quality_score=0.82,
        face_area=0.18,
        face_count=1,
        body_coverage=0.42,
        pose_coverage=0.7,
        aesthetic_score=0.76,
        analyzer="fixture",
    )

    result = analyzer.analyze([visual_candidate(tmp_path / "poster.jpg")], "image")[0]

    assert result["recommendation"] == "keep"
    assert result["confidence"] == 0.88
    assert result["face_count"] == 1


def test_voice_preflight_sends_reused_music_to_human_review() -> None:
    candidate = IngressCandidate(
        id="candidate_audio",
        source_kind=SourceKind.INSTAGRAM,
        source_locator="https://instagram.com/reel/example",
        display_name="Reused track",
        media_type=MediaType.AUDIO,
        duration=22.0,
        metadata_json={"audio_original": False, "audio_kind": "music"},
    )

    result = IngressCandidateAnalyzer().analyze([candidate], "voice")[0]

    assert result["recommendation"] == "review"
    assert result["confidence"] == 0.55
    assert result["analyzer"] == "ingress-audio-metadata-v2"


def test_voice_preflight_does_not_treat_original_audio_as_verified_speech() -> None:
    candidate = IngressCandidate(
        id="candidate_original_audio",
        source_kind=SourceKind.INSTAGRAM,
        source_locator="https://instagram.com/reel/silent-example",
        display_name="A silent GRWM",
        media_type=MediaType.AUDIO,
        duration=22.0,
        metadata_json={"audio_original": True, "audio_kind": "original"},
    )

    result = IngressCandidateAnalyzer().analyze([candidate], "voice")[0]

    assert result["recommendation"] == "review"
    assert result["confidence"] == 0.78
    assert result["reasons"] == [
        "original audio may contain target speech; speaker ownership requires confirmation"
    ]


def test_voice_preflight_still_rejects_objectively_short_audio() -> None:
    candidate = IngressCandidate(
        id="candidate_short_audio",
        source_kind=SourceKind.INSTAGRAM,
        source_locator="https://instagram.com/reel/short-example",
        display_name="Short audio",
        media_type=MediaType.AUDIO,
        duration=1.0,
        metadata_json={"audio_original": True, "audio_kind": "original"},
    )

    result = IngressCandidateAnalyzer().analyze([candidate], "voice")[0]

    assert result["recommendation"] == "reject"
    assert result["confidence"] == 0.9


def test_non_voice_preflight_can_still_reject_reused_music() -> None:
    candidate = IngressCandidate(
        id="candidate_audio_for_image",
        source_kind=SourceKind.INSTAGRAM,
        source_locator="https://instagram.com/reel/example",
        display_name="Reused track",
        media_type=MediaType.AUDIO,
        duration=22.0,
        metadata_json={"audio_original": False, "audio_kind": "music"},
    )

    result = IngressCandidateAnalyzer().analyze([candidate], "image")[0]

    assert result["recommendation"] == "reject"
    assert result["confidence"] == 0.96
