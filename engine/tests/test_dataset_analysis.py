from types import SimpleNamespace

from PIL import Image

from lorasuite_engine.dataset_analysis import DatasetImageAnalyzer
from lorasuite_engine.models import IdentityFace, NormalizedRect


class FakeIdentityEngine:
    def analyze(self, _path):
        return [
            SimpleNamespace(
                face=IdentityFace(
                    index=0,
                    confidence=0.94,
                    bounding_box=NormalizedRect(
                        x=0.3,
                        y=0.18,
                        width=0.28,
                        height=0.34,
                    ),
                    landmarks=[],
                )
            )
        ]


def test_portable_analysis_uses_identity_detector_when_vision_is_unavailable(tmp_path):
    image_path = tmp_path / "portrait.jpg"
    Image.new("RGB", (640, 960), color=(120, 96, 82)).save(image_path)

    evidence = DatasetImageAnalyzer(identity_engine=FakeIdentityEngine()).analyze(
        image_path
    )

    assert evidence.face_count == 1
    assert evidence.face_area > 0.09
    assert evidence.face_quality == 0.94
    assert "opencv-yunet" in evidence.analyzer
