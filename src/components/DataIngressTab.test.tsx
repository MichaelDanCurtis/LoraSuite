import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { DataIngressTab } from "./DataIngressTab";
import type { EngineClient } from "../lib/api";
import type { IngressCandidate, IngressJob } from "../lib/types";

describe("DataIngressTab", () => {
  it("shows deferred original downloads in the ingress job table", async () => {
    const user = userEvent.setup();
    const candidate: IngressCandidate = {
      id: "candidate_video",
      source_kind: "instagram",
      source_locator: "https://www.instagram.com/reel/example/",
      display_name: "example reel",
      media_type: "video",
      duration: 9.5,
      status: "ready",
      selected: true,
      metadata_json: {
        download_url: "https://cdninstagram.example/video.mp4",
      },
    };
    const completedJob = {
      id: "job_1",
      source_kind: "instagram",
      candidate_ids: [candidate.id],
      candidate_count: 1,
      selected_count: 1,
      imported_count: 0,
      deferred_count: 1,
      skipped_count: 0,
      failed_count: 0,
      status: "complete",
      progress_message: "Ingress complete; original downloads deferred",
      errors: [],
      deferred_candidates: [],
      imported_media_items: [],
      created_at: "2026-07-08T00:00:00Z",
    } as IngressJob;
    const engine: EngineClient = {
      importLocal: vi.fn(),
      scanLocalIngress: vi.fn(),
      scanInstagramBrowserUrl: vi.fn(),
      scanInstagramHelperPayload: vi.fn().mockResolvedValue({
        id: "scan_1",
        candidates: [candidate],
        errors: [],
      }),
      listIngressCandidates: vi.fn(),
      createIngressJob: vi.fn().mockResolvedValue({
        ...completedJob,
        status: "queued",
        progress_message: "Queued",
      }),
      listIngressJobs: vi.fn(),
      getIngressJob: vi.fn().mockResolvedValue(completedJob),
      exportRunComfyImage: vi.fn(),
    };

    render(
      <DataIngressTab
        engine={engine}
        mediaItems={[]}
        onMediaItemsImported={vi.fn()}
      />,
    );

    await user.click(screen.getByRole("button", { name: "Instagram Source" }));
    await user.click(screen.getByRole("button", { name: "Scan Instagram Helper Payload" }));
    await user.click(await screen.findByRole("button", { name: "Confirm Ingest" }));

    const jobsTable = await screen.findByRole("table");
    expect(within(jobsTable).getByRole("columnheader", { name: "Deferred" })).toBeInTheDocument();
    expect(within(jobsTable).getAllByRole("cell", { name: "1" })).toHaveLength(2);
    expect(
      screen.getByText("Ingress complete; original downloads deferred: 0 imported, 1 deferred, 0 failed."),
    ).toBeInTheDocument();
  });
});
