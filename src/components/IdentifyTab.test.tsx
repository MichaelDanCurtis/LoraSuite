import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { IdentifyTab } from "./IdentifyTab";
import type { MediaItem } from "../lib/types";

describe("IdentifyTab", () => {
  const mediaItems: MediaItem[] = [
    {
      id: "media_portrait",
      raw_path: "/tmp/vault/raw/portrait.png",
      media_type: "image",
      width: 768,
      height: 1024,
      status: "new",
    },
  ];

  it("shows target candidates sent from Curate", () => {
    render(<IdentifyTab mediaItems={mediaItems} assetUrl={(path) => `/asset/${path}`} />);

    expect(screen.getByRole("heading", { name: "Identify" })).toBeInTheDocument();
    expect(screen.getByText("1 target candidate")).toBeInTheDocument();
    expect(screen.getByText("portrait.png")).toBeInTheDocument();
  });

  it("tracks first-pass identification intent per candidate", async () => {
    const user = userEvent.setup();
    const assetUrl = vi.fn((path: string) => `/asset/${path}`);

    render(<IdentifyTab mediaItems={mediaItems} assetUrl={assetUrl} />);

    await user.selectOptions(screen.getByLabelText("Identity intent for portrait.png"), "face");

    expect(screen.getByText("Face crops")).toBeInTheDocument();
    expect(screen.getByText("1")).toBeInTheDocument();
    expect(assetUrl).toHaveBeenCalledWith("/tmp/vault/raw/portrait.png");
  });
});
