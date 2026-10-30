import json
from pathlib import Path
from build_h3_pilot_review import build


def test_review_waits_for_two_verified_clips(tmp_path):
    protocol = {"scenes": [["face", "A clothed portrait <script>"]], "seeds": [714],
                "conditions": ["baseline-a", "step-500"], "proposal_sha256": "test"}
    (tmp_path / "protocol.json").write_text(json.dumps(protocol))
    baseline = tmp_path / "baseline-a-face-714"
    baseline.mkdir()
    (baseline / "result.json").write_text('{"verified_decode":true}')
    build(tmp_path)
    assert '"pairs": []' in (tmp_path / "review.html").read_text()
    adapter = tmp_path / "step-500-face-714"
    adapter.mkdir()
    (adapter / "result.json").write_text('{"verified_decode":true}')
    build(tmp_path)
    html = (tmp_path / "review.html").read_text()
    assert '"id": "face-714-step-500"' in html
    assert "A clothed portrait <script>" not in html
    assert "object-fit:contain" in html
    assert "Not rated / not visible" in html
