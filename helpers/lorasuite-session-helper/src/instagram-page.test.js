import { describe, expect, it } from "vitest";

import { buildInstagramHelperPayload } from "./instagram-page.js";
import { assertNoTokenLikeKeys } from "./payload-safety.js";

describe("buildInstagramHelperPayload", () => {
  it("builds a sanitized reel payload from page metadata", () => {
    const payload = buildInstagramHelperPayload({
      locationHref: "https://www.instagram.com/reel/CODE/",
      documentTitle: "Example Reel",
      canonicalHref: "https://www.instagram.com/reel/CODE/",
      metas: {
        "og:title": "Example Reel Caption",
        "og:image": "https://cdninstagram.example/poster.jpg",
        "og:video": "https://cdninstagram.example/video.mp4",
        "video:duration": "9.5",
      },
      images: [
        {
          src: "https://cdninstagram.example/small.jpg",
          width: 320,
          height: 320,
        },
      ],
      videos: [],
    });

    assertNoTokenLikeKeys(payload);

    expect(payload.helper_version).toBe("lorasuite-session-helper-v0");
    expect(payload.media).toHaveLength(1);
    expect(payload.media[0]).toMatchObject({
      id: "instagram_reel_CODE",
      source_url: "https://www.instagram.com/reel/CODE/",
      display_name: "Example Reel Caption",
      media_type: "video",
      poster_url: "https://cdninstagram.example/poster.jpg",
      duration: 9.5,
    });
    expect(JSON.stringify(payload)).not.toContain("cookie");
    expect(JSON.stringify(payload)).not.toContain("token");
  });

  it("uses the largest page image when open graph image is missing", () => {
    const payload = buildInstagramHelperPayload({
      locationHref: "https://www.instagram.com/p/PHOTO/",
      documentTitle: "Photo Post",
      canonicalHref: "https://www.instagram.com/p/PHOTO/",
      metas: {},
      images: [
        { src: "https://cdninstagram.example/small.jpg", width: 240, height: 240 },
        { src: "https://cdninstagram.example/large.jpg", width: 1080, height: 1350 },
      ],
      videos: [],
    });

    expect(payload.media[0]).toMatchObject({
      id: "instagram_p_PHOTO",
      media_type: "image",
      poster_url: "https://cdninstagram.example/large.jpg",
      width: 1080,
      height: 1350,
    });
  });
});
