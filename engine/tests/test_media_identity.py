from lorasuite_engine.media_identity import (
    canonical_candidate_key,
    canonical_identity_metadata,
    deterministic_candidate_id,
    normalized_source_url,
)
from lorasuite_engine.models import MediaType, SourceKind


def test_instagram_surface_id_variants_resolve_to_one_candidate_identity():
    source_url = "https://www.instagram.com/reel/SAME123/"
    first = {"platform_media_id": "123456_999", "source_url": source_url}
    second = {"platform_media_id": "123456", "source_url": source_url}

    assert canonical_candidate_key(
        SourceKind.INSTAGRAM, first, source_url, MediaType.VIDEO
    ) == canonical_candidate_key(
        SourceKind.INSTAGRAM, second, source_url, MediaType.VIDEO
    )
    assert deterministic_candidate_id(
        SourceKind.INSTAGRAM, first, source_url, MediaType.VIDEO
    ) == deterministic_candidate_id(
        SourceKind.INSTAGRAM, second, source_url, MediaType.VIDEO
    )


def test_x_post_assets_share_bundle_without_colliding_with_each_other():
    source_url = "https://x.com/example/status/12345"
    first = {"platform_media_id": "x_12345_0", "source_url": source_url}
    second = {"platform_media_id": "x_12345_1", "source_url": source_url}

    first_identity = canonical_identity_metadata(
        SourceKind.X_TWITTER, first, source_url, MediaType.IMAGE
    )
    second_identity = canonical_identity_metadata(
        SourceKind.X_TWITTER, second, source_url, MediaType.IMAGE
    )

    assert first_identity["source_bundle_key"] == "x_twitter:post:12345"
    assert second_identity["source_bundle_key"] == "x_twitter:post:12345"
    assert first_identity["canonical_candidate_key"] != second_identity["canonical_candidate_key"]


def test_provider_namespace_prevents_cross_platform_id_collision():
    instagram = deterministic_candidate_id(
        SourceKind.INSTAGRAM,
        {"platform_media_id": "12345"},
        "12345",
        MediaType.IMAGE,
    )
    tiktok = deterministic_candidate_id(
        SourceKind.TIKTOK,
        {"platform_media_id": "tiktok_12345"},
        "12345",
        MediaType.VIDEO,
    )

    assert instagram != tiktok


def test_source_url_normalization_removes_tracking_and_fragments():
    assert normalized_source_url(
        "http://www.instagram.com/reel/ABC/?utm_source=test&b=2&a=1#fragment"
    ) == "https://instagram.com/reel/ABC?a=1&b=2"
