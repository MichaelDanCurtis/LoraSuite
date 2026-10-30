from __future__ import annotations

from dataclasses import dataclass
from math import exp
from pathlib import Path
from typing import Any

from PIL import Image, ImageFilter, ImageOps, ImageStat


@dataclass
class DatasetImageEvidence:
    quality_score: float
    face_quality: float
    face_area: float
    face_count: int
    body_coverage: float
    pose_coverage: float
    aesthetic_score: float
    head_yaw: float | None
    head_pitch: float | None
    head_roll: float | None
    descriptor: list[float]
    feature_print: Any | None
    analyzer: str


class DatasetImageAnalyzer:
    def __init__(self, identity_engine: Any | None = None) -> None:
        self.identity_engine = identity_engine
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

    def analyze(self, path: Path) -> DatasetImageEvidence:
        portable = _portable_evidence(path)
        identity = _identity_evidence(path, portable, self.identity_engine)
        if not self.available or self.NSURL is None or self.Vision is None:
            return identity

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
            aesthetic_request = (
                self.Vision.VNCalculateImageAestheticsScoresRequest.alloc().init()
            )
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
            if not succeeded:
                return identity
        except Exception:
            return identity

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
        vision_face_area = (
            float(
                primary_face.boundingBox().size.width
                * primary_face.boundingBox().size.height
            )
            if primary_face is not None
            else 0.0
        )
        vision_face_quality = max(
            (float(observation.faceCaptureQuality()) for observation in qualities),
            default=0.0,
        )
        face_count = max(len(faces), identity.face_count)
        face_area = max(vision_face_area, identity.face_area)
        face_quality = max(vision_face_quality, identity.face_quality)
        body_coverage = max(
            (
                float(human.confidence())
                * float(human.boundingBox().size.width * human.boundingBox().size.height)
                for human in humans
            ),
            default=0.0,
        )
        pose_coverage = max((_pose_coverage(pose, self.Vision) for pose in poses), default=0.0)
        aesthetic_score = portable.aesthetic_score
        if aesthetics:
            try:
                aesthetic_score = _clamp((float(aesthetics[0].overallScore()) + 1.0) / 2.0)
            except Exception:
                pass

        subject_score = max(
            face_quality,
            min(1.0, face_area / 0.10),
            min(1.0, body_coverage / 0.30),
            pose_coverage,
        )
        quality_score = _clamp(
            portable.quality_score * 0.56
            + subject_score * 0.28
            + aesthetic_score * 0.16
        )
        return DatasetImageEvidence(
            quality_score=quality_score,
            face_quality=face_quality,
            face_area=face_area,
            face_count=face_count,
            body_coverage=body_coverage,
            pose_coverage=pose_coverage,
            aesthetic_score=aesthetic_score,
            head_yaw=_optional_angle(primary_face, "yaw"),
            head_pitch=_optional_angle(primary_face, "pitch"),
            head_roll=_optional_angle(primary_face, "roll"),
            descriptor=portable.descriptor,
            feature_print=features[0] if features else None,
            analyzer=(
                "apple-vision+opencv-yunet-dataset-v2"
                if identity.face_count > 0
                else "apple-vision-dataset-v1"
            ),
        )


def feature_similarity(left: DatasetImageEvidence, right: DatasetImageEvidence) -> float | None:
    if left.feature_print is None or right.feature_print is None:
        return None
    try:
        distance = float(
            left.feature_print.computeDistanceToFeaturePrintObservation_error_(
                right.feature_print,
                None,
            )
        )
    except Exception:
        return None
    return _clamp(1.0 - distance / 1.15)


def descriptor_distance(left: DatasetImageEvidence, right: DatasetImageEvidence) -> float:
    return _clamp(
        sum(abs(a - b) for a, b in zip(left.descriptor, right.descriptor, strict=True))
        / 2.0
    )


def _portable_evidence(path: Path) -> DatasetImageEvidence:
    with Image.open(path) as source_image:
        image = ImageOps.exif_transpose(source_image).convert("RGB")
        gray = image.convert("L").resize((64, 64))
        pixels = list(gray.get_flattened_data())
        mean = sum(pixels) / len(pixels)
        clipped = sum(value < 8 or value > 247 for value in pixels) / len(pixels)
        exposure = max(0.0, 1.0 - abs(mean - 127.5) / 127.5 - clipped * 0.65)
        edge_variance = ImageStat.Stat(gray.filter(ImageFilter.FIND_EDGES)).var[0]
        sharpness = min(1.0, 1.0 - exp(-edge_variance / 900.0))
        detail = min(1.0, gray.entropy() / 8.0)
        descriptor = _descriptor(image)
    quality_score = _clamp(sharpness * 0.46 + exposure * 0.32 + detail * 0.22)
    return DatasetImageEvidence(
        quality_score=quality_score,
        face_quality=0.0,
        face_area=0.0,
        face_count=0,
        body_coverage=0.0,
        pose_coverage=0.0,
        aesthetic_score=0.5,
        head_yaw=None,
        head_pitch=None,
        head_roll=None,
        descriptor=descriptor,
        feature_print=None,
        analyzer="portable-image-dataset-v1",
    )


def _identity_evidence(
    path: Path,
    portable: DatasetImageEvidence,
    identity_engine: Any | None,
) -> DatasetImageEvidence:
    if identity_engine is None:
        return portable
    try:
        faces = identity_engine.analyze(path)
    except Exception:
        return portable
    if not faces:
        return portable

    face_area = max(
        result.face.bounding_box.width * result.face.bounding_box.height
        for result in faces
    )
    face_quality = max(float(result.face.confidence) for result in faces)
    subject_score = max(face_quality, min(1.0, face_area / 0.10))
    quality_score = _clamp(
        portable.quality_score * 0.56
        + subject_score * 0.28
        + portable.aesthetic_score * 0.16
    )
    return DatasetImageEvidence(
        quality_score=quality_score,
        face_quality=face_quality,
        face_area=face_area,
        face_count=len(faces),
        body_coverage=portable.body_coverage,
        pose_coverage=portable.pose_coverage,
        aesthetic_score=portable.aesthetic_score,
        head_yaw=None,
        head_pitch=None,
        head_roll=None,
        descriptor=portable.descriptor,
        feature_print=portable.feature_print,
        analyzer="opencv-yunet-dataset-v1",
    )


def _descriptor(image: Image.Image) -> list[float]:
    resized = image.resize((48, 48))
    histogram = resized.histogram()
    color_buckets: list[float] = []
    for channel in range(3):
        channel_histogram = histogram[channel * 256 : (channel + 1) * 256]
        for start in range(0, 256, 32):
            color_buckets.append(float(sum(channel_histogram[start : start + 32])))
    color_total = sum(color_buckets) or 1.0
    color_buckets = [value / color_total for value in color_buckets]

    gray_histogram = resized.convert("L").histogram()
    gray_buckets = [
        float(sum(gray_histogram[start : start + 16])) for start in range(0, 256, 16)
    ]
    gray_total = sum(gray_buckets) or 1.0
    return [*color_buckets, *(value / gray_total for value in gray_buckets)]


def _pose_coverage(pose: Any, vision: Any) -> float:
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
    confidence = sum(confidences) / len(confidences)
    return _clamp(visible * 0.7 + confidence * 0.3)


def _optional_angle(face: Any | None, method_name: str) -> float | None:
    if face is None:
        return None
    try:
        value = getattr(face, method_name)()
        return float(value) if value is not None else None
    except Exception:
        return None


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, float(value)))
