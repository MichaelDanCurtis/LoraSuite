from __future__ import annotations

from dataclasses import dataclass
from math import ceil, exp
from pathlib import Path
from typing import Any

from PIL import Image, ImageFilter, ImageStat

from lorasuite_engine.models import (
    VideoAnalysisFrame,
    VideoBreakdownAnalysis,
    VideoClipDecision,
    VideoClipProposal,
    VideoClipScores,
    VideoFrameDecision,
    VideoFrameScores,
    VideoStableRange,
    new_id,
)


@dataclass
class _MeasuredFrame:
    frame: VideoAnalysisFrame
    gray_pixels: list[int]
    color_histogram: list[float]
    difference_hash: int
    feature_print: Any | None


@dataclass
class _VisionEvidence:
    face_quality: float = 0.0
    face_area: float = 0.0
    face_count: int = 0
    body_coverage: float = 0.0
    pose_coverage: float = 0.0
    aesthetic: float = 0.5
    head_yaw: float | None = None
    head_pitch: float | None = None
    head_roll: float | None = None
    feature_print: Any | None = None


class _AppleVisionAnalyzer:
    def __init__(self) -> None:
        try:
            from Foundation import NSURL
            import Vision
        except ImportError:
            self.available = False
            self.NSURL = None
            self.Vision = None
        else:
            self.available = True
            self.NSURL = NSURL
            self.Vision = Vision

    def inspect(self, path: Path) -> _VisionEvidence:
        if not self.available or self.NSURL is None or self.Vision is None:
            return _VisionEvidence()

        try:
            handler = self.Vision.VNImageRequestHandler.alloc().initWithURL_options_(
                self.NSURL.fileURLWithPath_(str(path)),
                {},
            )
            face_request = self.Vision.VNDetectFaceLandmarksRequest.alloc().init()
            quality_request = self.Vision.VNDetectFaceCaptureQualityRequest.alloc().init()
            human_request = self.Vision.VNDetectHumanRectanglesRequest.alloc().init()
            pose_request = self.Vision.VNDetectHumanBodyPoseRequest.alloc().init()
            feature_request = self.Vision.VNGenerateImageFeaturePrintRequest.alloc().init()
            aesthetic_request = self.Vision.VNCalculateImageAestheticsScoresRequest.alloc().init()
            succeeded, _error = handler.performRequests_error_(
                [
                    face_request,
                    quality_request,
                    human_request,
                    pose_request,
                    feature_request,
                    aesthetic_request,
                ],
                None,
            )
        except Exception:
            return _VisionEvidence()
        if not succeeded:
            return _VisionEvidence()

        faces = face_request.results() or []
        qualities = quality_request.results() or []
        humans = human_request.results() or []
        poses = pose_request.results() or []
        features = feature_request.results() or []
        aesthetics = aesthetic_request.results() or []
        primary_face = max(
            faces,
            key=lambda face: float(
                face.boundingBox().size.width * face.boundingBox().size.height
            ),
            default=None,
        )
        face_area = max(
            (float(face.boundingBox().size.width * face.boundingBox().size.height) for face in faces),
            default=0.0,
        )
        face_quality = max(
            (float(observation.faceCaptureQuality()) for observation in qualities),
            default=0.0,
        )
        body_coverage = max(
            (
                float(human.confidence())
                * float(human.boundingBox().size.width * human.boundingBox().size.height)
                for human in humans
            ),
            default=0.0,
        )
        pose_coverage = max(
            (_vision_pose_coverage(pose, self.Vision) for pose in poses),
            default=0.0,
        )
        aesthetic = 0.5
        if aesthetics:
            try:
                aesthetic = _clamp((float(aesthetics[0].overallScore()) + 1.0) / 2.0)
            except Exception:
                pass
        return _VisionEvidence(
            face_quality=face_quality,
            face_area=face_area,
            face_count=len(faces),
            body_coverage=body_coverage,
            pose_coverage=pose_coverage,
            aesthetic=aesthetic,
            head_yaw=_optional_face_angle(primary_face, "yaw"),
            head_pitch=_optional_face_angle(primary_face, "pitch"),
            head_roll=_optional_face_angle(primary_face, "roll"),
            feature_print=features[0] if features else None,
        )


def analyze_video_frames(
    *,
    source_media_item_id: str,
    duration_seconds: float,
    frame_paths: list[Path],
    sample_fps: float,
    max_keeper_count: int,
) -> VideoBreakdownAnalysis:
    vision = _AppleVisionAnalyzer()
    measured = [
        _measure_frame(
            source_media_item_id=source_media_item_id,
            path=path,
            timestamp_seconds=index / sample_fps,
            vision=vision,
        )
        for index, path in enumerate(frame_paths)
    ]
    _measure_motion_and_scene_changes(measured)
    stable_ranges = _assign_stable_ranges(measured, source_media_item_id, sample_fps)
    _select_keepers(measured, max_keeper_count)
    clip_proposals = _propose_video_clips(
        measured,
        stable_ranges,
        source_media_item_id,
        duration_seconds,
    )
    return VideoBreakdownAnalysis(
        source_media_item_id=source_media_item_id,
        duration_seconds=duration_seconds,
        sample_fps=sample_fps,
        analyzer="apple-vision" if vision.available else "portable-image-analysis",
        selection_method="quality-weighted-diversity-v1",
        semantic_backend=(
            "apple-vision-feature-print" if vision.available else "portable-visual-descriptor"
        ),
        requested_keeper_count=max_keeper_count,
        frames=[item.frame for item in measured],
        stable_ranges=stable_ranges,
        clip_proposals=clip_proposals,
    )


def _measure_frame(
    *,
    source_media_item_id: str,
    path: Path,
    timestamp_seconds: float,
    vision: _AppleVisionAnalyzer,
) -> _MeasuredFrame:
    with Image.open(path) as source_image:
        image = source_image.convert("RGB")
        gray = image.convert("L").resize((64, 64))
        gray_pixels = list(gray.get_flattened_data())
        mean = sum(gray_pixels) / len(gray_pixels)
        clipped = sum(value < 8 or value > 247 for value in gray_pixels) / len(gray_pixels)
        exposure = max(0.0, 1.0 - abs(mean - 127.5) / 127.5 - clipped * 0.65)
        edge_variance = ImageStat.Stat(gray.filter(ImageFilter.FIND_EDGES)).var[0]
        sharpness = min(1.0, 1.0 - exp(-edge_variance / 900.0))
        detail = min(1.0, gray.entropy() / 8.0)
        color_histogram = _normalized_color_histogram(image)
        difference_hash = _difference_hash(image)
        width, height = image.size

    vision_evidence = vision.inspect(path)
    subject_score = max(
        vision_evidence.face_quality,
        min(1.0, vision_evidence.face_area / 0.10),
        min(1.0, vision_evidence.body_coverage / 0.30),
        vision_evidence.pose_coverage,
    )
    overall = _clamp(
        sharpness * 0.29
        + exposure * 0.17
        + detail * 0.11
        + subject_score * 0.27
        + vision_evidence.aesthetic * 0.16
    )
    frame = VideoAnalysisFrame(
        source_media_item_id=source_media_item_id,
        timestamp_seconds=timestamp_seconds,
        thumbnail_path=path,
        width=width,
        height=height,
        scores=VideoFrameScores(
            overall=overall,
            sharpness=sharpness,
            exposure=exposure,
            stability=0.5,
            detail=detail,
            face_quality=vision_evidence.face_quality,
            face_area=vision_evidence.face_area,
            body_coverage=vision_evidence.body_coverage,
            aesthetic=vision_evidence.aesthetic,
            pose_coverage=vision_evidence.pose_coverage,
            face_count=vision_evidence.face_count,
            head_yaw=vision_evidence.head_yaw,
            head_pitch=vision_evidence.head_pitch,
            head_roll=vision_evidence.head_roll,
        ),
    )
    return _MeasuredFrame(
        frame=frame,
        gray_pixels=gray_pixels,
        color_histogram=color_histogram,
        difference_hash=difference_hash,
        feature_print=vision_evidence.feature_print,
    )


def _measure_motion_and_scene_changes(frames: list[_MeasuredFrame]) -> None:
    for index, measured in enumerate(frames):
        if index == 0:
            continue
        previous = frames[index - 1]
        motion = sum(
            abs(current - prior)
            for current, prior in zip(measured.gray_pixels, previous.gray_pixels, strict=True)
        ) / (len(measured.gray_pixels) * 255.0)
        scene_change = sum(
            abs(current - prior)
            for current, prior in zip(
                measured.color_histogram,
                previous.color_histogram,
                strict=True,
            )
        ) / 2.0
        stability = _clamp(1.0 - motion / 0.24)
        measured.frame.scores.stability = stability
        measured.frame.scores.scene_change = _clamp(scene_change)
        subject_score = max(
            measured.frame.scores.face_quality,
            min(1.0, measured.frame.scores.face_area / 0.10),
            min(1.0, measured.frame.scores.body_coverage / 0.30),
            measured.frame.scores.pose_coverage,
        )
        measured.frame.scores.overall = _clamp(
            measured.frame.scores.sharpness * 0.25
            + measured.frame.scores.exposure * 0.15
            + measured.frame.scores.detail * 0.10
            + stability * 0.16
            + subject_score * 0.24
            + measured.frame.scores.aesthetic * 0.10
        )


def _assign_stable_ranges(
    frames: list[_MeasuredFrame],
    source_media_item_id: str,
    sample_fps: float,
) -> list[VideoStableRange]:
    if not frames:
        return []

    groups: list[list[_MeasuredFrame]] = []
    current: list[_MeasuredFrame] = []
    scene_index = 0
    scene_by_frame: dict[str, int] = {}
    for measured in frames:
        is_cut = bool(current) and measured.frame.scores.scene_change >= 0.34
        is_unstable = (
            measured.frame.scores.stability < 0.28
            or measured.frame.scores.sharpness < 0.08
        )
        if is_cut or (is_unstable and len(current) >= 2):
            groups.append(current)
            current = []
            if is_cut:
                scene_index += 1
        current.append(measured)
        scene_by_frame[measured.frame.id] = scene_index
    if current:
        groups.append(current)

    ranges: list[VideoStableRange] = []
    for group in groups:
        range_id = new_id("stable_range")
        for measured in group:
            measured.frame.stable_range_id = range_id
        ranges.append(
            VideoStableRange(
                id=range_id,
                source_media_item_id=source_media_item_id,
                start_seconds=group[0].frame.timestamp_seconds,
                end_seconds=group[-1].frame.timestamp_seconds + 1.0 / sample_fps,
                scene_index=scene_by_frame[group[0].frame.id],
                frame_ids=[measured.frame.id for measured in group],
            )
        )
    return ranges


def _propose_video_clips(
    frames: list[_MeasuredFrame],
    stable_ranges: list[VideoStableRange],
    source_media_item_id: str,
    duration_seconds: float,
) -> list[VideoClipProposal]:
    frames_by_id = {item.frame.id: item.frame for item in frames}
    proposals: list[VideoClipProposal] = []
    for stable_range in stable_ranges:
        range_start = max(0.0, stable_range.start_seconds)
        range_end = min(duration_seconds, stable_range.end_seconds)
        range_duration = range_end - range_start
        if range_duration <= 0:
            continue

        segment_count = max(1, ceil(range_duration / 8.0))
        segment_duration = range_duration / segment_count
        for segment_index in range(segment_count):
            start_seconds = range_start + segment_index * segment_duration
            end_seconds = min(range_end, start_seconds + segment_duration)
            segment_frames = [
                frames_by_id[frame_id]
                for frame_id in stable_range.frame_ids
                if frame_id in frames_by_id
                and start_seconds <= frames_by_id[frame_id].timestamp_seconds < end_seconds
            ]
            if not segment_frames:
                segment_frames = [
                    frames_by_id[frame_id]
                    for frame_id in stable_range.frame_ids
                    if frame_id in frames_by_id
                ]
            if not segment_frames:
                continue

            quality = _average(frame.scores.overall for frame in segment_frames)
            stability = _average(frame.scores.stability for frame in segment_frames)
            identity_coverage = _average(
                max(
                    frame.scores.face_quality,
                    min(1.0, frame.scores.face_area / 0.10),
                    min(1.0, frame.scores.body_coverage / 0.30),
                    frame.scores.pose_coverage,
                )
                for frame in segment_frames
            )
            scene_change = max(frame.scores.scene_change for frame in segment_frames)
            motion = _clamp(1.0 - stability)
            aesthetic = _average(frame.scores.aesthetic for frame in segment_frames)
            duration = end_seconds - start_seconds
            decision = VideoClipDecision.REVIEW
            if duration < 0.75 or quality < 0.22:
                decision = VideoClipDecision.REJECT
            elif (
                duration >= 1.25
                and quality >= 0.42
                and identity_coverage >= 0.30
                and scene_change < 0.50
            ):
                decision = VideoClipDecision.KEEP

            reasons = [
                f"{duration:.1f}s stable visual range",
                f"{round(identity_coverage * 100)}% subject coverage",
                f"{round(quality * 100)}% visual quality",
            ]
            if motion >= 0.55:
                reasons.append("high motion needs review")
            if scene_change >= 0.50:
                reasons.append("scene transition inside range")
            proposals.append(
                VideoClipProposal(
                    source_media_item_id=source_media_item_id,
                    stable_range_ids=[stable_range.id],
                    start_seconds=start_seconds,
                    end_seconds=end_seconds,
                    decision=decision,
                    scores=VideoClipScores(
                        quality=quality,
                        stability=stability,
                        identity_coverage=identity_coverage,
                        motion=motion,
                        scene_change=scene_change,
                        aesthetic=aesthetic,
                    ),
                    reasons=reasons,
                )
            )
    return proposals


def _average(values: Any) -> float:
    materialized = list(values)
    if not materialized:
        return 0.0
    return _clamp(sum(materialized) / len(materialized))


def _select_keepers(frames: list[_MeasuredFrame], max_keeper_count: int) -> None:
    if not frames:
        return

    selected: list[_MeasuredFrame] = []
    frame_interval = (
        frames[1].frame.timestamp_seconds - frames[0].frame.timestamp_seconds
        if len(frames) > 1
        else 1.0
    )
    analyzed_duration = frames[-1].frame.timestamp_seconds + frame_interval
    frames_by_range: dict[str, list[_MeasuredFrame]] = {}
    for measured in frames:
        frames_by_range.setdefault(measured.frame.stable_range_id or "unassigned", []).append(measured)
    keeper_limit = min(
        max_keeper_count,
        max(len(frames_by_range), ceil(analyzed_duration / 1.25)),
    )

    eligible = [frame for frame in frames if frame.frame.scores.overall >= 0.22]
    represented_ranges: set[str] = set()
    while eligible and len(selected) < keeper_limit:
        ranked: list[tuple[float, _MeasuredFrame, float]] = []
        for candidate in eligible:
            if _closest_duplicate(candidate, selected) is not None:
                continue
            diversity = _minimum_visual_distance(candidate, selected)
            range_id = candidate.frame.stable_range_id or "unassigned"
            range_bonus = 0.14 if range_id not in represented_ranges else 0.0
            selection_score = (
                candidate.frame.scores.overall * 0.62
                + diversity * 0.28
                + range_bonus
            )
            ranked.append((selection_score, candidate, diversity))
        if not ranked:
            break
        _score, keeper, diversity = max(
            ranked,
            key=lambda item: (item[0], item[1].frame.scores.overall),
        )
        keeper.frame.scores.diversity = diversity
        keeper.frame.decision = VideoFrameDecision.KEEPER
        keeper.frame.reasons = _selection_reasons(keeper.frame)
        selected.append(keeper)
        represented_ranges.add(keeper.frame.stable_range_id or "unassigned")
        eligible.remove(keeper)

    cluster_counter = 0
    selected_ids = {item.frame.id for item in selected}
    for measured in frames:
        if measured.frame.id in selected_ids:
            continue
        duplicate = _closest_duplicate(measured, selected)
        if duplicate is not None:
            if duplicate.frame.duplicate_cluster_id is None:
                cluster_counter += 1
                duplicate.frame.duplicate_cluster_id = f"duplicate_cluster_{cluster_counter:04d}"
            measured.frame.decision = VideoFrameDecision.DUPLICATE
            measured.frame.duplicate_of_frame_id = duplicate.frame.id
            measured.frame.duplicate_cluster_id = duplicate.frame.duplicate_cluster_id
            measured.frame.reasons = ["near duplicate"]
        else:
            measured.frame.decision = VideoFrameDecision.REJECTED
            measured.frame.reasons = [
                "low visual quality"
                if measured.frame.scores.overall < 0.22
                else "coverage limit"
            ]


def _closest_duplicate(
    candidate: _MeasuredFrame,
    selected: list[_MeasuredFrame],
) -> _MeasuredFrame | None:
    for keeper in selected:
        hash_distance = (candidate.difference_hash ^ keeper.difference_hash).bit_count()
        if hash_distance <= 5:
            return keeper
        time_gap = abs(candidate.frame.timestamp_seconds - keeper.frame.timestamp_seconds)
        if candidate.feature_print is not None and keeper.feature_print is not None:
            try:
                distance = candidate.feature_print.computeDistanceToFeaturePrintObservation_error_(
                    keeper.feature_print,
                    None,
                )
            except Exception:
                distance = 1.0
            if float(distance) <= 0.16 or (time_gap <= 0.75 and float(distance) <= 0.42):
                return keeper
    return None


def _minimum_visual_distance(
    candidate: _MeasuredFrame,
    selected: list[_MeasuredFrame],
) -> float:
    if not selected:
        return 1.0
    return min(_visual_distance(candidate, keeper) for keeper in selected)


def _visual_distance(left: _MeasuredFrame, right: _MeasuredFrame) -> float:
    feature_distance: float | None = None
    if left.feature_print is not None and right.feature_print is not None:
        try:
            feature_distance = _clamp(
                float(
                    left.feature_print.computeDistanceToFeaturePrintObservation_error_(
                        right.feature_print,
                        None,
                    )
                )
                / 0.9
            )
        except Exception:
            feature_distance = None
    color_distance = _clamp(
        sum(
            abs(current - prior)
            for current, prior in zip(
                left.color_histogram,
                right.color_histogram,
                strict=True,
            )
        )
        / 0.55
    )
    framing_distance = _clamp(
        abs(left.frame.scores.face_area - right.frame.scores.face_area) * 6.0
        + abs(left.frame.scores.body_coverage - right.frame.scores.body_coverage) * 2.0
        + abs(left.frame.scores.pose_coverage - right.frame.scores.pose_coverage)
    )
    time_distance = _clamp(
        abs(left.frame.timestamp_seconds - right.frame.timestamp_seconds) / 4.0
    )
    if feature_distance is None:
        return _clamp(color_distance * 0.50 + framing_distance * 0.30 + time_distance * 0.20)
    return _clamp(
        feature_distance * 0.50
        + color_distance * 0.24
        + framing_distance * 0.18
        + time_distance * 0.08
    )


def _selection_reasons(frame: VideoAnalysisFrame) -> list[str]:
    ranked = [
        (frame.scores.face_quality, "clear face"),
        (min(1.0, frame.scores.body_coverage / 0.30), "useful body coverage"),
        (frame.scores.sharpness, "sharp detail"),
        (frame.scores.stability, "stable range"),
        (frame.scores.diversity, "distinct visual coverage"),
        (frame.scores.aesthetic, "strong composition"),
        (frame.scores.exposure, "balanced exposure"),
    ]
    reasons = [label for score, label in sorted(ranked, reverse=True) if score >= 0.55]
    return reasons[:3] or ["best frame in range"]


def _normalized_color_histogram(image: Image.Image) -> list[float]:
    resized = image.resize((48, 48))
    histogram = resized.histogram()
    buckets: list[float] = []
    for channel in range(3):
        channel_histogram = histogram[channel * 256 : (channel + 1) * 256]
        for start in range(0, 256, 32):
            buckets.append(float(sum(channel_histogram[start : start + 32])))
    total = sum(buckets) or 1.0
    return [value / total for value in buckets]


def _difference_hash(image: Image.Image) -> int:
    pixels = list(image.convert("L").resize((9, 8)).get_flattened_data())
    value = 0
    for row in range(8):
        offset = row * 9
        for column in range(8):
            value = (value << 1) | int(pixels[offset + column] > pixels[offset + column + 1])
    return value


def _vision_pose_coverage(pose: Any, vision: Any) -> float:
    try:
        points, _error = pose.recognizedPointsForGroupKey_error_(
            vision.VNHumanBodyPoseObservationJointsGroupNameAll,
            None,
        )
    except Exception:
        return 0.0
    confidences = [float(point.confidence()) for point in points.values()]
    if not confidences:
        return 0.0
    visible = sum(confidence >= 0.25 for confidence in confidences) / len(confidences)
    return _clamp(visible * 0.70 + sum(confidences) / len(confidences) * 0.30)


def _optional_face_angle(face: Any | None, method_name: str) -> float | None:
    if face is None:
        return None
    try:
        value = getattr(face, method_name)()
        return float(value) if value is not None else None
    except Exception:
        return None


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, float(value)))
