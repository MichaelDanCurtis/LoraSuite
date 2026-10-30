const HELPER_VERSION = "lorasuite-session-helper-v0";

export function buildInstagramHelperPayload(snapshot) {
  const sourceUrl = snapshot.canonicalHref || snapshot.locationHref;
  const mediaType = hasVideo(snapshot) ? "video" : "image";
  const bestImage = choosePosterImage(snapshot);
  const bestVideo = chooseVideo(snapshot);

  return {
    helper_version: HELPER_VERSION,
    scanned_url: snapshot.locationHref,
    media: [
      {
        id: instagramMediaId(sourceUrl),
        source_url: sourceUrl,
        display_name: displayName(snapshot),
        media_type: mediaType,
        poster_url: bestImage?.src,
        thumbnail_url: bestImage?.src,
        download_url: mediaType === "video" ? bestVideo?.src : undefined,
        width: bestImage?.width || undefined,
        height: bestImage?.height || undefined,
        duration: optionalNumber(
          snapshot.metas["video:duration"] || snapshot.metas["og:video:duration"],
        ),
      },
    ],
  };
}

function hasVideo(snapshot) {
  return Boolean(snapshot.metas["og:video"] || snapshot.videos?.length);
}

function chooseVideo(snapshot) {
  const openGraphVideo = snapshot.metas["og:video"];
  if (openGraphVideo) {
    return { src: openGraphVideo };
  }
  return snapshot.videos?.find((video) => video.src);
}

function choosePosterImage(snapshot) {
  const openGraphImage = snapshot.metas["og:image"];
  if (openGraphImage) {
    return {
      src: openGraphImage,
      width: optionalNumber(snapshot.metas["og:image:width"]),
      height: optionalNumber(snapshot.metas["og:image:height"]),
    };
  }

  return [...(snapshot.images || [])]
    .filter((image) => image.src)
    .sort((left, right) => imageArea(right) - imageArea(left))[0];
}

function imageArea(image) {
  return (optionalNumber(image.width) || 0) * (optionalNumber(image.height) || 0);
}

function displayName(snapshot) {
  return (
    snapshot.metas["og:title"] ||
    snapshot.metas["twitter:title"] ||
    snapshot.documentTitle ||
    instagramMediaId(snapshot.canonicalHref || snapshot.locationHref)
  );
}

function instagramMediaId(sourceUrl) {
  try {
    const url = new URL(sourceUrl);
    const parts = url.pathname.split("/").filter(Boolean);
    const kind = parts[0] || "post";
    const code = parts[1] || "unknown";
    return `instagram_${kind}_${code}`;
  } catch {
    return "instagram_unknown";
  }
}

function optionalNumber(value) {
  if (value === undefined || value === null || value === "") {
    return undefined;
  }
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : undefined;
}
