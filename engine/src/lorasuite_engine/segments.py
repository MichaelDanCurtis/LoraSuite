from math import isfinite

from lorasuite_engine.models import Segment, SegmentCreate


def validate_segment_range(start_seconds: float, end_seconds: float) -> None:
    if not isfinite(start_seconds) or not isfinite(end_seconds):
        raise ValueError("segment seconds must be finite")
    if start_seconds < 0:
        raise ValueError("start_seconds must be zero or greater")
    if end_seconds <= start_seconds:
        raise ValueError("end_seconds must be greater than start_seconds")


def create_segment(payload: SegmentCreate) -> Segment:
    validate_segment_range(payload.start_seconds, payload.end_seconds)
    return Segment(**payload.model_dump())


def guidance_for_segment(segment: SegmentCreate) -> list[str]:
    validate_segment_range(segment.start_seconds, segment.end_seconds)
    guidance: list[str] = []
    duration = segment.end_seconds - segment.start_seconds

    if segment.use_for_image:
        guidance.append(
            "Extract sparse keyframes from stable visual ranges and dedupe near-identical frames."
        )
    else:
        guidance.append("Image export is off for this segment.")

    if segment.use_for_video:
        guidance.append(f"Keep the clip coherent; selected duration is {duration:.1f} seconds.")
    else:
        guidance.append("Video export is off for this segment.")

    if segment.use_for_voice:
        guidance.append("Prefer clean speech with one speaker and low background noise.")
    else:
        guidance.append("Voice export is off for this segment.")

    return guidance
