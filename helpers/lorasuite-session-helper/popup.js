import { buildInstagramHelperPayload } from "./src/instagram-page.js";
import { assertNoTokenLikeKeys } from "./src/payload-safety.js";

const scanButton = document.querySelector("#scan");
const engineUrlInput = document.querySelector("#engine-url");
const statusElement = document.querySelector("#status");

scanButton.addEventListener("click", scanCurrentPage);

async function scanCurrentPage() {
  try {
    setStatus("Scanning current tab.");
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    if (!tab?.id || !tab.url?.startsWith("https://www.instagram.com/")) {
      setStatus("Open an Instagram post or reel before scanning.");
      return;
    }

    const [injection] = await chrome.scripting.executeScript({
      target: { tabId: tab.id },
      func: collectInstagramPageSnapshot,
    });
    const payload = buildInstagramHelperPayload(injection.result);
    await attachPosterDataUrls(payload);
    assertNoTokenLikeKeys(payload);

    const engineUrl = engineUrlInput.value.replace(/\/$/, "");
    const response = await fetch(`${engineUrl}/ingress/instagram/helper-scan`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ payload }),
    });

    if (!response.ok) {
      const text = await response.text();
      throw new Error(text || `Engine returned ${response.status}`);
    }

    const result = await response.json();
    setStatus(`Sent ${result.candidates.length} candidate(s). Load them in LoraSuite.`);
  } catch (error) {
    setStatus(error instanceof Error ? error.message : "Scan failed.");
  }
}

async function attachPosterDataUrls(payload) {
  for (const media of payload.media) {
    const posterUrl = media.poster_url || media.thumbnail_url;
    if (!posterUrl) continue;
    const dataUrl = await fetchPosterDataUrl(posterUrl);
    if (dataUrl) {
      media.poster_data_url = dataUrl;
    }
  }
}

async function fetchPosterDataUrl(url) {
  const response = await fetch(url, { credentials: "omit" });
  if (!response.ok) return undefined;

  const blob = await response.blob();
  if (!["image/jpeg", "image/jpg", "image/png"].includes(blob.type)) {
    return undefined;
  }
  if (blob.size > 5 * 1024 * 1024) {
    return undefined;
  }

  return await new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.addEventListener("load", () => resolve(String(reader.result)));
    reader.addEventListener("error", () => reject(reader.error));
    reader.readAsDataURL(blob);
  });
}

function setStatus(message) {
  statusElement.textContent = message;
}

function collectInstagramPageSnapshot() {
  const metas = {};
  for (const meta of document.querySelectorAll("meta[property], meta[name]")) {
    const key = meta.getAttribute("property") || meta.getAttribute("name");
    const content = meta.getAttribute("content");
    if (key && content) {
      metas[key] = content;
    }
  }

  const canonicalHref =
    document.querySelector('link[rel="canonical"]')?.href || window.location.href;

  const images = Array.from(document.images)
    .map((image) => ({
      src: image.currentSrc || image.src,
      width: image.naturalWidth || image.width || undefined,
      height: image.naturalHeight || image.height || undefined,
    }))
    .filter((image) => image.src);

  const videos = Array.from(document.querySelectorAll("video"))
    .map((video) => ({
      src: video.currentSrc || video.src,
      poster: video.poster || undefined,
      width: video.videoWidth || undefined,
      height: video.videoHeight || undefined,
      duration: Number.isFinite(video.duration) ? video.duration : undefined,
    }))
    .filter((video) => video.src || video.poster);

  return {
    locationHref: window.location.href,
    documentTitle: document.title,
    canonicalHref,
    metas,
    images,
    videos,
  };
}
