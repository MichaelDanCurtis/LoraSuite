from pathlib import Path

from PIL import Image, ImageDraw

from lorasuite_engine.models import VideoFrameDecision
from lorasuite_engine.video_analysis import analyze_video_frames


def test_video_analysis_selects_sparse_keepers_and_collapses_duplicates(tmp_path):
    frame_paths: list[Path] = []
    for index in range(12):
        frame_path = tmp_path / f"frame_{index:02d}.jpg"
        image = Image.new("RGB", (320, 180), color=(28 + index * 4, 52, 76))
        draw = ImageDraw.Draw(image)
        position = (index // 3) * 28
        draw.rectangle((40 + position, 30, 150 + position, 160), fill=(220, 170, 120))
        draw.ellipse((72 + position, 46, 118 + position, 92), fill=(245, 210, 175))
        image.save(frame_path)
        frame_paths.append(frame_path)

    analysis = analyze_video_frames(
        source_media_item_id="media_video",
        duration_seconds=6,
        frame_paths=frame_paths,
        sample_fps=2,
        max_keeper_count=12,
    )

    keepers = [
        frame for frame in analysis.frames if frame.decision == VideoFrameDecision.KEEPER
    ]
    duplicates = [
        frame for frame in analysis.frames if frame.decision == VideoFrameDecision.DUPLICATE
    ]
    assert analysis.frames
    assert analysis.stable_ranges
    assert analysis.clip_proposals
    assert all(0 <= clip.scores.quality <= 1 for clip in analysis.clip_proposals)
    assert all(clip.end_seconds > clip.start_seconds for clip in analysis.clip_proposals)
    assert 1 <= len(keepers) <= 5
    assert duplicates
    assert all(frame.reasons for frame in keepers)
    assert all(frame.stable_range_id for frame in analysis.frames)
    assert analysis.selection_method == "quality-weighted-diversity-v1"
    assert analysis.semantic_backend in {
        "apple-vision-feature-print",
        "portable-visual-descriptor",
    }
    assert any(frame.scores.diversity > 0 for frame in keepers)


def test_video_analysis_records_quality_scores_and_source_timestamps(tmp_path):
    frame_paths = []
    for index, color in enumerate(((12, 12, 12), (128, 128, 128), (245, 245, 245))):
        frame_path = tmp_path / f"exposure_{index}.jpg"
        Image.new("RGB", (120, 80), color=color).save(frame_path)
        frame_paths.append(frame_path)

    analysis = analyze_video_frames(
        source_media_item_id="source_1",
        duration_seconds=3,
        frame_paths=frame_paths,
        sample_fps=1,
        max_keeper_count=2,
    )

    assert [frame.timestamp_seconds for frame in analysis.frames] == [0.0, 1.0, 2.0]
    assert all(frame.source_media_item_id == "source_1" for frame in analysis.frames)
    assert analysis.frames[1].scores.exposure > analysis.frames[0].scores.exposure
    assert analysis.frames[1].scores.exposure > analysis.frames[2].scores.exposure
    assert all(0 <= frame.scores.overall <= 1 for frame in analysis.frames)
