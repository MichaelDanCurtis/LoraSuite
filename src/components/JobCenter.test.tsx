import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { JobCenter } from "./JobCenter";

describe("JobCenter", () => {
  it("loads persistent work on demand and exposes supported job actions", async () => {
    const user = userEvent.setup();
    const retrieval = {
      id: "social_1",
      status: "running",
      request: { provider: "instagram" },
      progress_message: "Retrieving the next 100",
      created_at: "2026-08-08T00:00:00Z",
    };
    const engine = {
      listSocialAcquisitionJobs: vi.fn().mockResolvedValue([retrieval]),
      listIngressJobs: vi.fn().mockResolvedValue([]),
      listProcessingJobs: vi.fn().mockResolvedValue([]),
      listCaptionJobs: vi.fn().mockResolvedValue([]),
      listTrainingRuns: vi.fn().mockResolvedValue([]),
      listRunPodBundleUploadJobs: vi.fn().mockResolvedValue([]),
      cancelSocialAcquisitionJob: vi.fn().mockResolvedValue({ ...retrieval, status: "canceled" }),
    };

    render(<JobCenter engine={engine as never} />);
    expect(engine.listSocialAcquisitionJobs).not.toHaveBeenCalled();
    await user.click(screen.getByRole("button", { name: "Job Center" }));

    expect(await screen.findByText(/Retrieving the next 100/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Cancel" }));
    await waitFor(() => expect(engine.cancelSocialAcquisitionJob).toHaveBeenCalledWith(retrieval.id));
  });
});
