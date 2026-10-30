import importlib.util
from pathlib import Path
import pytest


def module(name):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(name + ".py"))
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


def test_buckets_keep_pixel_budget_and_divisibility():
    pilot = module("h3_cloud_pilot")
    for width, height in [(1125, 2300), (5000, 3000), (512, 512), (360, 640)]:
        w, h = pilot.bucket_size(width, height)
        assert w % 32 == h % 32 == 0
        assert w * h <= 512 * 512
        assert abs(w / h - width / height) < .1


def test_preparation_rejects_changed_proposal(tmp_path):
    pilot = module("h3_cloud_pilot")
    source = tmp_path / "proposal.json"
    source.write_text("{}")
    with pytest.raises(ValueError, match="Proposal changed"):
        pilot.prepare(source, tmp_path / "package")
    assert not (tmp_path / "package").exists()


def test_watchdog_exact_pod_stop_not_process_kill():
    guard = module("h3_pilot_watchdog")
    request = guard.stop_request("testpod123", "fake-test-key")
    assert request.full_url == "https://rest.runpod.io/v1/pods/testpod123/stop"
    assert request.method == "POST"
    assert request.data == b"{}"
    with pytest.raises(ValueError):
        guard.stop_request("../other", "fake")
    with pytest.raises(ValueError):
        guard.stop_request("testpod123", "")
