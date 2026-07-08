import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { CurateSearchTab } from "./CurateSearchTab";
import type { MediaItem } from "../lib/types";

describe("CurateSearchTab", () => {
  const mediaItems: MediaItem[] = [
    {
      id: "media_portrait",
      raw_path: "/tmp/vault/raw/portrait.png",
      media_type: "image",
      width: 768,
      height: 1024,
      status: "new",
      metadata_json: {
        original_path: "/Volumes/Training/MarySue/portrait.png",
      },
    },
    {
      id: "media_voice",
      raw_path: "/tmp/vault/raw/voice.m4a",
      media_type: "audio",
      duration: 12.4,
      status: "new",
    },
  ];

  it("searches imported media by path and metadata", async () => {
    const user = userEvent.setup();

    render(<CurateSearchTab mediaItems={mediaItems} assetUrl={(path) => `/asset/${path}`} />);

    await user.type(screen.getByLabelText("Search media"), "MarySue");

    expect(screen.getByText("portrait.png")).toBeInTheDocument();
    expect(screen.queryByText("voice.m4a")).not.toBeInTheDocument();
    expect(screen.getByText("1 visible")).toBeInTheDocument();
  });

  it("filters by media type and tracks selected dataset items", async () => {
    const user = userEvent.setup();
    const assetUrl = vi.fn((path: string) => `/asset/${path}`);

    render(<CurateSearchTab mediaItems={mediaItems} assetUrl={assetUrl} />);

    await user.selectOptions(screen.getByLabelText("Media type"), "audio");

    expect(screen.queryByText("portrait.png")).not.toBeInTheDocument();
    expect(screen.getByText("voice.m4a")).toBeInTheDocument();

    await user.click(screen.getByLabelText("Select for dataset: voice.m4a"));

    expect(screen.getByText("1 selected")).toBeInTheDocument();
    expect(assetUrl).toHaveBeenCalledWith("/tmp/vault/raw/portrait.png");
  });
});
