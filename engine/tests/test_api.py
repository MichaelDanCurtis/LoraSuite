import hashlib
from pathlib import Path

from PIL import Image

import lorasuite_engine.api as api_module
from lorasuite_engine.api import create_app
from lorasuite_engine.models import IngressCandidate, IngressScanResult, MediaType


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def test_health_endpoint_reports_ok(client):
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "lorasuite-engine"}


def test_engine_allows_vite_browser_origin(client):
    origin = "http://127.0.0.1:5173"

    preflight = client.options(
        "/ingress/instagram/browser-scan",
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )
    response = client.get("/health", headers={"Origin": origin})

    assert preflight.status_code == 200
    assert preflight.headers["access-control-allow-origin"] == origin
    assert response.headers["access-control-allow-origin"] == origin


def test_vault_asset_endpoint_serves_files_under_vault(client, tmp_path):
    preview_path = tmp_path / "vault" / "previews" / "thumb.jpg"
    preview_path.parent.mkdir(parents=True)
    Image.new("RGB", (11, 13), color=(20, 40, 60)).save(preview_path)

    response = client.get("/assets/file", params={"path": str(preview_path)})

    assert response.status_code == 200
    assert response.content == preview_path.read_bytes()
    assert response.headers["content-type"] == "image/jpeg"


def test_vault_asset_endpoint_rejects_files_outside_vault(client, tmp_path):
    outside_path = tmp_path / "outside.jpg"
    Image.new("RGB", (11, 13), color=(20, 40, 60)).save(outside_path)

    response = client.get("/assets/file", params={"path": str(outside_path)})

    assert response.status_code == 404


def test_create_app_uses_env_vault_root(monkeypatch, tmp_path):
    vault_root = tmp_path / "env-vault"
    monkeypatch.setenv("LORASUITE_VAULT_ROOT", str(vault_root))

    app = create_app()

    assert app.state.vault_root == vault_root


def test_import_local_image_endpoint_copies_file_and_returns_media_items(client, tmp_path):
    image_path = tmp_path / "api-image.png"
    Image.new("RGB", (17, 29), color=(93, 10, 47)).save(image_path)
    expected_sha256 = file_sha256(image_path)

    response = client.post("/vault/import/local", json={"paths": [str(image_path)]})

    assert response.status_code == 200
    payload = response.json()
    assert payload["errors"] == []
    assert len(payload["media_items"]) == 1
    media_item = payload["media_items"][0]
    raw_path = Path(media_item["raw_path"])
    assert raw_path.name == f"{expected_sha256}.png"
    assert raw_path.read_bytes() == image_path.read_bytes()
    assert media_item["media_type"] == "image"
    assert media_item["sha256"] == expected_sha256
    assert media_item["width"] == 17
    assert media_item["height"] == 29
    assert media_item["metadata_json"]["original_path"] == str(image_path)


def test_import_local_endpoint_returns_errors_for_invalid_paths(client, tmp_path):
    missing_path = tmp_path / "missing.png"

    response = client.post("/vault/import/local", json={"paths": [str(missing_path)]})

    assert response.status_code == 200
    payload = response.json()
    assert payload["media_items"] == []
    assert payload["errors"][0]["path"] == str(missing_path)
    assert payload["errors"][0]["code"] == "missing_path"
    assert not (tmp_path / "vault" / "raw").exists()
    assert not (tmp_path / "vault" / "vault.json").exists()


def test_runcomfy_export_endpoint(client, tmp_path):
    frame = tmp_path / "frame.png"
    Image.new("RGB", (24, 24), color=(40, 50, 60)).save(frame)
    output_dir = tmp_path / "export"

    response = client.post(
        "/exports/runcomfy-image",
        json={
            "frames": [str(frame)],
            "output_dir": str(output_dir),
            "caption_template": "person trigger_token",
            "source_segment_ids": ["segment-1"],
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["export_type"] == "runcomfy_image"
    assert body["output_path"] == str(output_dir)
    assert body["manifest_path"] == str(output_dir / "manifest.json")
    assert body["source_segment_ids"] == ["segment-1"]
    assert body["status"] == "complete"
    assert (output_dir / "images" / "000001.png").exists()
    assert (output_dir / "images" / "000001.txt").read_text(
        encoding="utf-8"
    ) == "person trigger_token\n"


def test_runcomfy_export_endpoint_returns_400_for_webp(client, tmp_path):
    webp = tmp_path / "frame.webp"
    webp.write_bytes(b"fake")

    response = client.post(
        "/exports/runcomfy-image",
        json={
            "frames": [str(webp)],
            "output_dir": str(tmp_path / "export"),
            "caption_template": "person trigger_token",
            "source_segment_ids": [],
        },
    )

    assert response.status_code == 400
    assert "WebP is not supported" in response.json()["detail"]


def test_runcomfy_export_endpoint_returns_400_for_empty_frames(client, tmp_path):
    response = client.post(
        "/exports/runcomfy-image",
        json={
            "frames": [],
            "output_dir": str(tmp_path / "export"),
            "caption_template": "person trigger_token",
            "source_segment_ids": [],
        },
    )

    assert response.status_code == 400
    assert "At least one frame is required" in response.json()["detail"]


def test_local_ingress_scan_endpoint_returns_candidates(client, tmp_path):
    image_path = tmp_path / "scan-image.png"
    Image.new("RGB", (31, 37), color=(80, 90, 100)).save(image_path)

    response = client.post("/ingress/local/scan", json={"roots": [str(image_path)]})

    assert response.status_code == 200
    payload = response.json()
    assert len(payload["candidates"]) == 1
    candidate = payload["candidates"][0]
    assert candidate["display_name"] == "scan-image.png"
    assert candidate["status"] == "ready"
    assert candidate["selected"] is True
    assert candidate["thumbnail_path"]


def test_instagram_helper_scan_endpoint_returns_poster_candidates(client, tmp_path):
    poster = tmp_path / "api-poster.jpg"
    Image.new("RGB", (44, 66), color=(80, 20, 140)).save(poster)

    response = client.post(
        "/ingress/instagram/helper-scan",
        json={
            "payload": {
                "helper_version": "fixture",
                "media": [
                    {
                        "id": "ig_api_video",
                        "source_url": "https://www.instagram.com/reel/api/",
                        "display_name": "api reel",
                        "media_type": "video",
                        "poster_path": str(poster),
                    }
                ],
            },
            "include_video_posters_as_image_candidates": True,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert len(body["candidates"]) == 3
    assert body["candidates"][0]["source_kind"] == "instagram"
    assert body["candidates"][1]["media_type"] == "image"
    assert body["candidates"][2]["media_type"] == "audio"


def test_instagram_helper_scan_endpoint_stores_poster_candidates_for_jobs(
    client, tmp_path
):
    poster = tmp_path / "api-job-poster.jpg"
    Image.new("RGB", (44, 66), color=(30, 120, 80)).save(poster)
    scan = client.post(
        "/ingress/instagram/helper-scan",
        json={
            "payload": {
                "helper_version": "fixture",
                "media": [
                    {
                        "id": "ig_api_job_video",
                        "source_url": "https://www.instagram.com/reel/api-job/",
                        "display_name": "api job reel",
                        "media_type": "video",
                        "poster_path": str(poster),
                    }
                ],
            }
        },
    ).json()
    poster_candidate = [
        candidate
        for candidate in scan["candidates"]
        if candidate["media_type"] == "image"
    ][0]

    response = client.post(
        "/ingress/jobs",
        json={
            "source_kind": "instagram",
            "candidate_ids": [poster_candidate["id"]],
            "options": {},
        },
    )

    assert response.status_code == 200
    job = response.json()
    detail = client.get(f"/ingress/jobs/{job['id']}").json()
    assert detail["status"] == "complete"
    assert detail["imported_count"] == 1
    assert detail["imported_media_items"][0]["metadata_json"]["original_path"] == (
        poster_candidate["metadata_json"]["local_import_path"]
    )


def test_ingress_candidates_endpoint_filters_instagram_candidates(client, tmp_path):
    local_image = tmp_path / "local-candidate.png"
    Image.new("RGB", (12, 18), color=(10, 40, 90)).save(local_image)
    client.post("/ingress/local/scan", json={"roots": [str(local_image)]})

    poster = tmp_path / "instagram-poster.jpg"
    Image.new("RGB", (44, 66), color=(30, 120, 80)).save(poster)
    client.post(
        "/ingress/instagram/helper-scan",
        json={
            "payload": {
                "helper_version": "fixture",
                "media": [
                    {
                        "id": "ig_filter_video",
                        "source_url": "https://www.instagram.com/reel/filter/",
                        "display_name": "filter reel",
                        "media_type": "video",
                        "poster_path": str(poster),
                    }
                ],
            }
        },
    )

    response = client.get("/ingress/candidates", params={"source_kind": "instagram"})

    assert response.status_code == 200
    body = response.json()
    assert len(body["candidates"]) == 3
    assert {candidate["source_kind"] for candidate in body["candidates"]} == {
        "instagram"
    }
    assert body["errors"] == []


def test_instagram_browser_scan_endpoint_stores_thumbnail_candidates(
    client, monkeypatch
):
    def fake_scan(url, vault_root, *, browser, limit):
        assert url == "https://www.instagram.com/reel/browser/"
        assert browser == "chrome"
        assert limit == 8
        return IngressScanResult(
            candidates=[
                IngressCandidate(
                    source_kind=api_module.SourceKind.INSTAGRAM,
                    source_locator=url,
                    display_name="browser reel",
                    media_type=MediaType.VIDEO,
                    selected=False,
                )
            ]
        )

    monkeypatch.setattr(api_module, "scan_instagram_url_with_browser_cookies", fake_scan)

    response = client.post(
        "/ingress/instagram/browser-scan",
        json={"url": "https://www.instagram.com/reel/browser/", "browser": "chrome", "limit": 8},
    )

    assert response.status_code == 200
    body = response.json()
    assert len(body["candidates"]) == 1
    listed = client.get("/ingress/candidates", params={"source_kind": "instagram"}).json()
    assert listed["candidates"][0]["display_name"] == "browser reel"


def test_ingress_job_endpoint_processes_selected_candidates(client, tmp_path):
    image_path = tmp_path / "job-image.png"
    Image.new("RGB", (31, 37), color=(80, 90, 100)).save(image_path)
    scan = client.post("/ingress/local/scan", json={"roots": [str(image_path)]}).json()
    candidate_id = scan["candidates"][0]["id"]

    response = client.post(
        "/ingress/jobs",
        json={"source_kind": "local", "candidate_ids": [candidate_id], "options": {}},
    )

    assert response.status_code == 200
    job = response.json()
    detail = client.get(f"/ingress/jobs/{job['id']}").json()
    assert detail["status"] == "complete"
    assert detail["imported_count"] == 1
    assert detail["imported_media_items"][0]["metadata_json"]["original_path"] == str(
        image_path
    )


def test_ingress_jobs_endpoint_lists_recent_jobs(client, tmp_path):
    image_path = tmp_path / "listed-image.png"
    Image.new("RGB", (12, 14), color=(10, 20, 30)).save(image_path)
    scan = client.post("/ingress/local/scan", json={"roots": [str(image_path)]}).json()
    candidate_id = scan["candidates"][0]["id"]
    client.post("/ingress/jobs", json={"source_kind": "local", "candidate_ids": [candidate_id]})

    response = client.get("/ingress/jobs")

    assert response.status_code == 200
    assert response.json()[0]["source_kind"] == "local"
